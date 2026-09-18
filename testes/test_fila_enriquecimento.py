import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from processamento import banco, contact_providers as cp, crm, fila_enriquecimento as fila, metricas

AGORA = datetime(2026, 9, 18, 8, 0, tzinfo=timezone.utc)

CNPJS = ["11444777000161", "11222333000181", "45997418000153", "34028316000103", "00000000000191", "60701190000104"]
TERRITORIOS = [{"tipo": "cidade", "valor": "Guaíra"}, {"tipo": "regiao_proxima", "valor": "Barretos"}]


class ProviderFalso(cp.ContactProvider):
    """Provedor de teste: nunca usa rede. Pode falhar, ser ignorado ou gravar um contato."""

    def __init__(self, nome="Falso", modo="ok", gastar=0):
        self.nome, self.modo, self.gastar = nome, modo, gastar

    def enriquecer(self, empresa, **opcoes):
        r = cp.ResultadoProvider(provider=self.nome, chamadas_api=self.gastar)
        if self.modo == "erro":
            r.erros.append(f"{self.nome}: falha simulada")
        elif self.modo == "ignorar":
            r.ignorado_motivo = "sem CNPJ"
        else:
            r.contatos.append(cp.ContatoEncontrado(
                tipo_contato="EMAIL_CONTATO", valor=f"contato@empresa{empresa['id']}.com.br", fonte=self.nome, url_fonte="http://x"))
        return r


class WebFalso(cp.WebSearchContactProvider):
    nome = "Busca web (SerpApi)"

    def __init__(self, gastar=3, modo="ok"):
        self.gastar, self.modo = gastar, modo

    def disponivel(self):
        return True

    def enriquecer(self, empresa, consultas=None, **opcoes):
        r = cp.ResultadoProvider(provider=self.nome, chamadas_api=self.gastar, persistido_diretamente=True,
                                 contagens_diretas={"presenca_digital": 1, "evidencias": 0, "contatos": 0})
        if self.modo == "erro":
            r.erros.append("A SerpApi demorou demais")
        return r


@pytest.fixture
def conexao(monkeypatch):
    monkeypatch.setenv("SERPAPI_LIMITE_MENSAL", "100")
    monkeypatch.setenv("SERPAPI_RESERVA_MANUAL", "20")
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    banco.criar_tabelas(conn)
    banco.criar_tabelas_enriquecimento(conn)
    crm.criar_tabelas(conn)
    fila.criar_tabelas(conn)

    def empresa(i, nome, cidade, cnpj=None, projeto=None):
        eid, _ = banco.obter_ou_criar_empresa(conn, {"cnpj": cnpj, "razao_social": nome, "nome_fantasia": None,
                                                       "cidade": cidade, "estado": "SP", "status": None})
        banco.inserir_ou_atualizar_incentivo(conn, {
            "empresa_id": eid, "fonte": "SALIC", "tipo_incentivo": "Lei Rouanet", "projeto": projeto, "ano": 2020,
            "valor": 1000.0 * (i + 1), "uf": "SP", "cidade": cidade, "url_fonte": f"https://x/{i}",
            "coletado_em": "2026-01-01", "nivel_confianca": "ALTO"})
        return eid

    empresa(0, "Guaíra Prospect A", "Guaíra", CNPJS[0])
    empresa(1, "Barretos Prospect B", "Barretos", CNPJS[1])
    empresa(2, "Osasco Prospect C", "Osasco", CNPJS[2])
    empresa(3, "Parceira do IORM", "Guaíra", CNPJS[3], projeto="Usina da Dança 2019")  # Linha Cruzada
    empresa(4, "Sem CNPJ Ltda", "Guaíra", None)
    conn.commit()
    yield conn
    conn.close()


def df(conexao):
    return metricas.mesclar_empresas_e_enriquecimento(
        metricas.carregar_empresas(conexao, territorios=TERRITORIOS), metricas.carregar_enriquecimento(conexao))


def nomes(selecao):
    return [f["razao_social"] for f in selecao["fila"]]


# ------------------------------------------------------------ seleção
def test_fila_exclui_linha_cruzada_e_sem_cnpj(conexao):
    s = fila.selecionar_fila(conexao, df(conexao), 30, agora=AGORA)
    assert "Parceira do IORM" not in nomes(s) and "Sem CNPJ Ltda" not in nomes(s)
    assert sorted(nomes(s)) == ["Barretos Prospect B", "Guaíra Prospect A", "Osasco Prospect C"]


def test_fila_prioriza_regiao_e_deixa_fora_da_regiao_por_ultimo(conexao):
    s = fila.selecionar_fila(conexao, df(conexao), 30, agora=AGORA)
    assert nomes(s)[0] == "Guaíra Prospect A" and nomes(s)[-1] == "Osasco Prospect C"


def test_fila_respeita_filtro_geografico(conexao):
    s = fila.selecionar_fila(conexao, df(conexao), 30, incluir_fora_da_regiao=False, agora=AGORA)
    assert "Osasco Prospect C" not in nomes(s)


def test_fila_respeita_a_meta_e_explica_quando_ha_menos_elegiveis(conexao):
    assert len(fila.selecionar_fila(conexao, df(conexao), 2, agora=AGORA)["fila"]) == 2
    s = fila.selecionar_fila(conexao, df(conexao), 30, agora=AGORA)
    assert "Apenas 3 empresa(s) elegível(is) para a meta de 30" in s["motivo_menos_que_meta"]


def test_fila_pula_quem_ja_foi_pesquisado(conexao):
    eid = conexao.execute("SELECT id FROM empresas WHERE razao_social = 'Guaíra Prospect A'").fetchone()[0]
    banco.registrar_pesquisa(conexao, {"empresa_id": eid, "executado_em": "2026-01-01", "quantidade_fontes": 1, "quantidade_contatos": 0,
                                         "quantidade_redes": 0, "quantidade_evidencias": 0, "status": "SUCESSO", "observacoes": None})
    assert "Guaíra Prospect A" not in nomes(fila.selecionar_fila(conexao, df(conexao), 30, agora=AGORA))


# ------------------------------------------------------------ execução
def test_execucao_completa_grava_e_classifica(conexao):
    web = WebFalso(gastar=3)
    r = fila.executar(conexao, df(conexao), [ProviderFalso("Receita", gastar=1), web], meta=30, agora=lambda: AGORA, dormir=lambda s: None)
    assert r["processadas"] == 3 and r["sucesso"] == 3 and r["falha"] == 0
    assert conexao.execute("SELECT COUNT(*) FROM contatos").fetchone()[0] == 3
    assert conexao.execute("SELECT COUNT(*) FROM historico_pesquisa").fetchone()[0] == 3  # última pesquisa registrada
    assert "Apenas 3" in r["observacao"]
    assert fila.uso_mes(conexao, "SerpApi", AGORA) == 9


def test_provedor_com_erro_gera_falha_e_agenda_nova_tentativa(conexao):
    r = fila.executar(conexao, df(conexao), [ProviderFalso("Receita", modo="erro")], meta=30, agora=lambda: AGORA, dormir=lambda s: None)
    assert r["falha"] == 3
    est = conexao.execute("SELECT * FROM enriquecimento_estado LIMIT 1").fetchone()
    assert est["ultimo_status"] == "FALHA" and est["tentativas"] == 1
    assert datetime.fromisoformat(est["proxima_tentativa_apos"]) == AGORA + timedelta(days=1)


def test_falha_so_e_tentada_de_novo_depois_do_prazo(conexao):
    fila.executar(conexao, df(conexao), [ProviderFalso(modo="erro")], meta=30, agora=lambda: AGORA, dormir=lambda s: None)
    assert fila.selecionar_fila(conexao, df(conexao), 30, agora=AGORA + timedelta(hours=2))["fila"] == []
    s = fila.selecionar_fila(conexao, df(conexao), 30, agora=AGORA + timedelta(days=1, minutes=1))
    assert len(s["fila"]) == 3 and all(f["tipo_fila"] == "RETENTATIVA" for f in s["fila"])


def test_apos_3_tentativas_nao_tenta_mais(conexao):
    for dia in range(3):
        t = AGORA + timedelta(days=5 * dia)
        fila.executar(conexao, df(conexao), [ProviderFalso(modo="erro")], meta=30, agora=lambda t=t: t, dormir=lambda s: None)
    assert fila.selecionar_fila(conexao, df(conexao), 30, agora=AGORA + timedelta(days=60))["fila"] == []


def test_sem_cota_web_vira_parcial_e_nao_gasta_serpapi(conexao):
    fila.registrar_uso(conexao, "SerpApi", 80, AGORA)  # limite 100 - reserva 20 = 0 de orçamento
    r = fila.executar(conexao, df(conexao), [ProviderFalso("Receita", gastar=1), WebFalso()], meta=30, agora=lambda: AGORA, dormir=lambda s: None)
    assert r["parcial"] == 3 and r["chamadas_serpapi"] == 0
    assert fila.uso_mes(conexao, "SerpApi", AGORA) == 80
    assert "cota mensal" in conexao.execute("SELECT detalhe FROM enriquecimento_itens LIMIT 1").fetchone()[0]


def test_orcamento_web_limita_quantas_empresas_usam_busca(conexao):
    fila.registrar_uso(conexao, "SerpApi", 71, AGORA)  # sobram 100-20-71 = 9 => 3 empresas x 3 consultas
    assert fila.orcamento_serpapi(conexao, AGORA) == 9
    fila.registrar_uso(conexao, "SerpApi", 3, AGORA)  # sobram 6 => só 2 empresas
    r = fila.executar(conexao, df(conexao), [ProviderFalso("Receita", gastar=1), WebFalso(gastar=3)], meta=30, agora=lambda: AGORA, dormir=lambda s: None)
    assert r["sucesso"] == 2 and r["parcial"] == 1 and r["chamadas_serpapi"] == 6


def test_segunda_execucao_no_mesmo_dia_nao_passa_da_meta(conexao):
    fila.executar(conexao, df(conexao), [ProviderFalso("Receita")], meta=2, agora=lambda: AGORA, dormir=lambda s: None)
    r2 = fila.executar(conexao, df(conexao), [ProviderFalso("Receita")], meta=2, agora=lambda: AGORA, dormir=lambda s: None)
    assert r2["processadas"] == 0 and "já atingida" in r2["observacao"]
    assert fila.processadas_hoje(conexao, AGORA) == 2


def test_nao_duplica_contatos_ao_reprocessar(conexao):
    fila.executar(conexao, df(conexao), [ProviderFalso("Receita")], meta=30, agora=lambda: AGORA, dormir=lambda s: None)
    total = conexao.execute("SELECT COUNT(*) FROM contatos").fetchone()[0]
    fila.executar(conexao, df(conexao), [ProviderFalso("Receita")], meta=30, agora=lambda: AGORA + timedelta(days=10), dormir=lambda s: None)
    assert conexao.execute("SELECT COUNT(*) FROM contatos").fetchone()[0] == total


def test_teto_de_tempo_interrompe_e_registra(conexao):
    relogio = iter([AGORA, AGORA, AGORA + timedelta(seconds=99999)] + [AGORA + timedelta(seconds=99999)] * 50)
    r = fila.executar(conexao, df(conexao), [ProviderFalso("Receita")], meta=30, max_segundos=60,
                      agora=lambda: next(relogio), dormir=lambda s: None)
    assert r["interrompida_por"] and "teto de tempo" in r["observacao"]


def test_linha_cruzada_nunca_entra_na_execucao(conexao):
    fila.executar(conexao, df(conexao), [ProviderFalso("Receita")], meta=30, agora=lambda: AGORA, dormir=lambda s: None)
    eid = conexao.execute("SELECT id FROM empresas WHERE razao_social = 'Parceira do IORM'").fetchone()[0]
    assert conexao.execute("SELECT COUNT(*) FROM enriquecimento_itens WHERE empresa_id = ?", (eid,)).fetchone()[0] == 0


def test_resumo_admin(conexao):
    fila.executar(conexao, df(conexao), [ProviderFalso("Receita")], meta=30, agora=lambda: AGORA, dormir=lambda s: None)
    resumo = fila.resumo_admin(conexao, df(conexao), agora=AGORA)
    assert resumo["hoje"]["processadas"] == 3 and resumo["total_acumulado"] == 3
    assert resumo["ultima_execucao"]["processadas"] == 3
    assert resumo["serpapi"]["orcamento_da_rotina"] == 80
    assert len(fila.itens_de_hoje(conexao, AGORA)) == 3
