"""Descoberta nacional de empresas (v9): provedores, níveis, deduplicação com proveniência, candidatas sem CNPJ, cotas e Rotina diária.

Os provedores REAIS (Apollo, Lusha, Snov, SerpApi) são testados aqui com respostas SIMULADAS: isso prova a leitura da resposta,
o tratamento de erro e a deduplicação — NÃO prova que a chamada funciona contra o serviço real (isso depende de chave/plano)."""
from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from processamento import banco, descoberta_empresas as D, fila_enriquecimento, metricas, osc, rotina_etapas
from processamento.descoberta_empresas import EmpresaDescoberta as E

RAIZ = Path(__file__).resolve().parent.parent
BANCO = RAIZ / "dados" / "iorm_radar.db"

PERFIL = {"cidades": ["Guaíra", "Ipuã", "Miguelópolis", "Orlândia"], "estados": ["SP"], "territorios": [], "temas": [], "palavras_chave": [],
          "programas": [], "mecanismos": []}


def cnpj_valido(base: str) -> str:
    """Completa 12 dígitos com os dois verificadores (algoritmo oficial)."""
    def dv(numeros: str, pesos: list[int]) -> str:
        resto = sum(int(n) * p for n, p in zip(numeros, pesos)) % 11
        return str(0 if resto < 2 else 11 - resto)
    b = base.zfill(12)[:12]
    d1 = dv(b, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    d2 = dv(b + d1, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return b + d1 + d2


@pytest.fixture(autouse=True)
def _ambiente(monkeypatch):
    for var in ("APOLLO_API_KEY", "LUSHA_API_KEY", "SNOV_CLIENT_ID", "SNOV_CLIENT_SECRET", "SERPAPI_API_KEY", "EMPRESAS_NOVAS_POR_DIA",
                "LIMITE_POR_PROVIDER", "DESCOBERTA_MAX_CHAMADAS"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(D, "_estado_inicial_salic", lambda uf: ({}, False))  # nunca lê o estado real da coleta diária


@pytest.fixture
def con(tmp_path):
    conexao = banco.conectar(tmp_path / "t.db")
    banco.criar_tabelas(conexao)
    banco.criar_tabelas_enriquecimento(conexao)
    D.criar_tabelas(conexao)
    osc.criar_tabelas(conexao)
    return conexao


class Resposta:
    def __init__(self, status=200, corpo=None):
        self.status_code, self._corpo = status, corpo if corpo is not None else {}

    def json(self):
        return self._corpo

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class Falso(D.CompanyDiscoveryProvider):
    """Provedor roteirizado: `roteiro(consulta)` devolve lista de empresas, ou levanta uma exceção do contrato."""
    variaveis_credencial = ()

    def __init__(self, nome, roteiro, niveis=(1, 2, 3, 4), creditos=0.0):
        super().__init__(http=lambda *a, **k: None)
        self.nome, self.rotulo, self._roteiro, self.niveis_suportados, self._creditos = nome, nome, roteiro, niveis, creditos
        self.consultas: list[D.Consulta] = []

    def buscar(self, consulta):
        self.consultas.append(consulta)
        empresas = self._roteiro(consulta)
        return D.ResultadoBusca(empresas, chamadas=1, creditos=self._creditos, esgotado=True)


def _rodar(con, providers, **kw):
    return D.executar_descoberta(con, providers, PERFIL, reconciliar=False, **kw)


def _n(con, sql="SELECT COUNT(*) FROM empresas", *args):
    return con.execute(sql, args).fetchone()[0]


# ------------------------------------------------------------------ níveis e alcance nacional
def test_niveis_da_regiao_para_o_brasil():
    n1, n2, n3, n4 = (D.montar_consultas(PERFIL, n) for n in (1, 2, 3, 4))
    assert [c.cidade for c in n1] == PERFIL["cidades"] and all(c.uf == "SP" for c in n1)
    assert [c.uf for c in n2] == ["SP"]
    assert "SP" not in [c.uf for c in n3] and {"MG", "PR", "BA"} <= {c.uf for c in n3}
    assert len(n4) == 1 and n4[0].uf is None and n4[0].cidade is None


def test_descobre_empresas_fora_de_sao_paulo_e_a_regiao_vem_primeiro(con):
    def roteiro(c):
        if c.nivel == 3 and c.uf in ("MG", "PR", "BA"):
            return [E(nome=f"Indústria {c.uf} Ltda", cnpj=cnpj_valido({"MG": "111", "PR": "222", "BA": "333"}[c.uf] + "00001"),
                      cidade="Cidade Teste", estado=c.uf)]
        return []

    p = Falso("Nacional", roteiro)
    r = _rodar(con, [p], meta=10)
    estados = {l[0] for l in con.execute("SELECT estado FROM empresas")}
    assert {"MG", "PR", "BA"} <= estados and r["totais"]["novas_confirmadas"] == 3
    niveis = [c.nivel for c in p.consultas]
    assert niveis == sorted(niveis) and niveis[0] == 1  # do mais perto para o mais longe


def test_meta_diaria_e_respeitada_e_a_busca_para_ao_atingi_la(con, monkeypatch):
    monkeypatch.setenv("EMPRESAS_NOVAS_POR_DIA", "3")
    contador = iter(range(1, 1000))
    p = Falso("Muitas", lambda c: [E(nome=f"Empresa {i} Ltda", cnpj=cnpj_valido(str(next(contador) + 500)), cidade="X", estado="MG") for i in range(5)])
    r = _rodar(con, [p])
    assert r["meta"] == 3 and r["totais"]["novas_total"] == 3 and _n(con) == 3 and r["status"] == "CONCLUIDO"


def test_limite_por_provider_e_configuravel(con, monkeypatch):
    monkeypatch.setenv("LIMITE_POR_PROVIDER_LIMITADO", "2")
    seq = iter(range(1, 1000))
    p = Falso("Limitado", lambda c: [E(nome=f"Alfa {i} Ltda", cnpj=cnpj_valido(str(next(seq) + 900)), cidade="X", estado="SP") for i in range(6)])
    r = _rodar(con, [p], meta=50)
    assert r["providers"]["Limitado"]["novas_confirmadas"] == 2 and _n(con) == 2


# ------------------------------------------------------------------ deduplicação e proveniência
def _http_apollo(corpo=None, status=200):
    return lambda metodo, url, **k: Resposta(status, corpo if corpo is not None else {})


def test_mesma_empresa_em_apollo_lusha_e_snov_vira_UMA_com_tres_origens(con, monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "x"); monkeypatch.setenv("LUSHA_API_KEY", "x")
    monkeypatch.setenv("SNOV_CLIENT_ID", "x"); monkeypatch.setenv("SNOV_CLIENT_SECRET", "x")

    def http(metodo, url, **k):
        if "apollo" in url:
            return Resposta(200, {"organizations": [{"id": "ap1", "name": "Usina Boa Vista S.A.", "primary_domain": "usinaboavista.com.br",
                                                      "website_url": "https://www.usinaboavista.com.br", "state": "Minas Gerais", "city": "Uberaba"}],
                                  "pagination": {"total_pages": 1}})
        if "lusha" in url:
            return Resposta(200, {"data": [{"id": "lu9", "name": "USINA BOA VISTA", "domain": "usinaboavista.com.br",
                                            "location": {"city": "Uberaba", "state": "Minas Gerais"}}]})
        if "oauth" in url:
            return Resposta(200, {"access_token": "t"})
        return Resposta(200, {"companies": [{"id": "sn5", "name": "Usina Boavista", "domain": "www.usinaboavista.com.br"}]})

    provs = [D.ApolloDiscoveryProvider(http), D.LushaDiscoveryProvider(http), D.SnovDiscoveryProvider(http)]
    r = _rodar(con, provs, meta=20, niveis=(3,))
    assert _n(con) == 1, "mesma empresa em três provedores = uma só linha"
    origens = {l[0] for l in con.execute("SELECT provider FROM empresas_origens")}
    assert origens == {"Apollo", "Lusha", "Snov"}
    assert r["providers"]["Apollo"]["novas_candidatas"] == 1 and r["providers"]["Lusha"]["existentes"] >= 1 and r["providers"]["Snov"]["existentes"] >= 1
    linha = con.execute("SELECT cnpj, estagio_cadastro, dominio FROM empresas").fetchone()
    assert linha["cnpj"] is None and linha["estagio_cadastro"] == "CANDIDATA" and linha["dominio"] == "usinaboavista.com.br"


def test_empresa_existente_nao_e_duplicada_e_recebe_apenas_uma_nova_origem(con):
    cnpj = cnpj_valido("123456")
    con.execute("INSERT INTO empresas (cnpj, razao_social, cidade, estado, criado_em, atualizado_em) VALUES (?, 'Alfa Comércio Ltda', 'Guaíra', 'SP', 'x', 'x')", (cnpj,))
    con.commit()
    antes = con.execute("SELECT * FROM empresas").fetchone()
    p = Falso("Prov", lambda c: [E(nome="ALFA COMERCIO", cnpj=cnpj, cidade="Guaíra", estado="SP", site="https://alfa.com.br", id_externo="z1")])
    r = _rodar(con, [p], meta=5, niveis=(2,))
    assert _n(con) == 1 and r["totais"]["existentes"] == 1 and r["totais"]["novas_total"] == 0
    depois = con.execute("SELECT * FROM empresas").fetchone()
    assert depois["razao_social"] == antes["razao_social"] and depois["cidade"] == antes["cidade"]  # nada sobrescrito
    assert depois["dominio"] == "alfa.com.br"  # campo que estava vazio foi preenchido
    assert _n(con, "SELECT COUNT(*) FROM empresas_origens") == 1


def test_dedupe_por_nome_mais_local_sem_cnpj(con):
    con.execute("INSERT INTO empresas (razao_social, cidade, estado, criado_em, atualizado_em) VALUES ('Padaria Central Ltda', 'Franca', 'SP', 'x', 'x')")
    con.commit()
    p = Falso("Prov", lambda c: [E(nome="Padaria Central", cidade="Franca", estado="SP")])
    _rodar(con, [p], meta=5, niveis=(2,))
    assert _n(con) == 1


def test_cnpjs_diferentes_com_mesmo_dominio_nao_sao_fundidos(con):
    a, b = cnpj_valido("100000"), cnpj_valido("200000")
    con.execute("INSERT INTO empresas (cnpj, razao_social, cidade, estado, dominio, criado_em, atualizado_em) VALUES (?, 'Grupo X Matriz', 'Franca', 'SP', 'grupox.com.br', 'x', 'x')", (a,))
    con.commit()
    p = Falso("Prov", lambda c: [E(nome="Grupo X Filial", cnpj=b, cidade="Franca", estado="SP", site="grupox.com.br")])
    r = _rodar(con, [p], meta=5, niveis=(2,))
    assert _n(con) == 2 and r["totais"]["existentes"] == 0


def test_nome_muito_parecido_apenas_sinaliza_possivel_duplicata_sem_fundir_nem_apagar(con):
    con.execute("INSERT INTO empresas (razao_social, cidade, estado, criado_em, atualizado_em) VALUES ('Transportadora Rodovia Norte Ltda', 'Uberaba', 'MG', 'x', 'x')")
    con.commit()
    p = Falso("Prov", lambda c: [E(nome="Transportadora Rodovia Norte S/A", cidade="Uberlandia", estado="MG")] if c.uf == "MG" else [])
    r = _rodar(con, [p], meta=5, niveis=(3,))
    assert _n(con) == 2 and r["totais"]["possiveis_duplicatas"] == 1
    nova = con.execute("SELECT * FROM empresas ORDER BY id DESC LIMIT 1").fetchone()
    assert nova["possivel_duplicata_de"] == 1 and nova["estagio_cadastro"] == "CANDIDATA"


def test_rodar_duas_vezes_com_o_mesmo_resultado_nao_duplica_nada(con):
    p = Falso("Prov", lambda c: [E(nome="Empresa Repetida", cnpj=cnpj_valido("777"), cidade="X", estado="RS", id_externo="r1")])
    _rodar(con, [p], meta=5, niveis=(3,))
    con.execute("DELETE FROM descoberta_estado"); con.commit()  # força repetir a mesma consulta
    _rodar(con, [p], meta=5, niveis=(3,))
    assert _n(con) == 1 and _n(con, "SELECT COUNT(*) FROM empresas_origens") == 1


# ------------------------------------------------------------------ descoberta ≠ relacionamento
def test_empresa_da_linha_cruzada_nao_volta_como_nova_e_o_relacionamento_e_preservado(con):
    cnpj = cnpj_valido("424242")
    con.execute("""INSERT INTO empresas (cnpj, razao_social, cidade, estado, criado_em, atualizado_em, relacionamento_iorm, relacionamento_tipo,
                   relacionamento_fonte) VALUES (?, 'Parceira Cultural Ltda', 'Guaíra', 'SP', 'x', 'x', 1, 'AUTOMATICO', 'incentivo')""", (cnpj,))
    con.commit()
    p = Falso("Prov", lambda c: [E(nome="Parceira Cultural", cnpj=cnpj, cidade="Guaíra", estado="SP")])
    r = _rodar(con, [p], meta=5)
    linha = con.execute("SELECT relacionamento_iorm, relacionamento_tipo, relacionamento_fonte FROM empresas").fetchone()
    assert (linha[0], linha[1], linha[2]) == (1, "AUTOMATICO", "incentivo") and _n(con) == 1 and r["totais"]["novas_total"] == 0


def test_descoberta_nunca_marca_relacionamento_com_o_iorm(con):
    p = Falso("Prov", lambda c: [E(nome="Empresa Nova Ltda", cnpj=cnpj_valido("31337"), cidade="Guaíra", estado="SP")])
    _rodar(con, [p], meta=5)
    assert _n(con, "SELECT COUNT(*) FROM empresas WHERE relacionamento_iorm = 1") == 0
    codigo = (RAIZ / "processamento" / "descoberta_empresas.py").read_text(encoding="utf-8").lower()
    assert "set relacionamento" not in codigo and "relacionamento_iorm =" not in codigo.replace("relacionamento_iorm = 1", "")


# ------------------------------------------------------------------ candidatas (sem CNPJ)
def test_empresa_sem_cnpj_e_candidata_nao_e_prospect_e_nao_entra_na_fila(con):
    p = Falso("Prov", lambda c: [E(nome="Mercado Sem Cnpj", site="mercadosemcnpj.com.br", cidade="Salvador", estado="BA")] if c.uf == "BA" else [])
    _rodar(con, [p], meta=5, niveis=(3,))
    linha = con.execute("SELECT cnpj, estagio_cadastro FROM empresas").fetchone()
    assert linha["cnpj"] is None and linha["estagio_cadastro"] == "CANDIDATA"
    df = metricas.carregar_empresas(con)
    assert not bool(df.iloc[0]["eh_prospect"]) and bool(df.iloc[0]["candidata"])
    assert D.contar_candidatas(con) == 1
    fila = fila_enriquecimento.selecionar_fila(con, df.assign(prioridade_prospeccao=0), 5)
    assert fila["fila"] == []


def test_cnpj_invalido_do_provedor_e_descartado_nunca_inventado_nem_consertado(con):
    p = Falso("Prov", lambda c: [E(nome="Empresa Cnpj Ruim", cnpj="12345678000100", site="ruim.com.br", cidade="X", estado="SP")])
    _rodar(con, [p], meta=5, niveis=(2,))
    assert con.execute("SELECT cnpj FROM empresas").fetchone()[0] is None


def test_dados_insuficientes_sao_rejeitados_e_contados(con):
    itens = [E(nome="Sem Local Nenhum"), E(nome="ab", cnpj=None, site="x.com.br"), E(nome="", cnpj=cnpj_valido("5"))]
    r = _rodar(con, [Falso("Prov", lambda c: itens)], meta=5, niveis=(2,))
    assert r["totais"]["rejeitadas"] == 3 and _n(con) == 0


def test_promover_candidata_exige_cnpj_valido_e_vira_prospect(con):
    _rodar(con, [Falso("Prov", lambda c: [E(nome="Candidata Ltda", site="candidata.com.br", cidade="Recife", estado="PE")] if c.uf == "PE" else [])],
           meta=5, niveis=(3,))
    eid = con.execute("SELECT id FROM empresas").fetchone()[0]
    assert not D.promover_candidata(con, eid, "11111111111111")["ok"]  # dígitos verificadores inválidos
    assert not D.promover_candidata(con, eid)["ok"]  # sem CNPJ e sem justificativa
    assert D.promover_candidata(con, eid, cnpj_valido("8888"))["ok"]
    assert bool(metricas.carregar_empresas(con).iloc[0]["eh_prospect"])
    assert not D.promover_candidata(con, eid, cnpj_valido("8888"))["ok"]  # já confirmada


def test_cnpj_ja_usado_por_outra_empresa_bloqueia_a_promocao(con):
    cnpj = cnpj_valido("9999")
    con.execute("INSERT INTO empresas (cnpj, razao_social, criado_em, atualizado_em) VALUES (?, 'Dona do CNPJ', 'x', 'x')", (cnpj,))
    con.execute("INSERT INTO empresas (razao_social, cidade, estado, estagio_cadastro, criado_em, atualizado_em) VALUES ('Candidata', 'X', 'SP', 'CANDIDATA', 'x', 'x')")
    con.commit()
    assert not D.promover_candidata(con, 2, cnpj)["ok"]


# ------------------------------------------------------------------ disponibilidade, credencial e cota
def test_provedor_sem_credencial_e_pulado_e_nunca_chamado(con):
    chamado = []
    apollo = D.ApolloDiscoveryProvider(lambda *a, **k: chamado.append(1) or Resposta())
    r = _rodar(con, [apollo], meta=5)
    assert r["providers"]["Apollo"]["status"] == D.STATUS_SEM_CREDENCIAL and not chamado
    assert "APOLLO_API_KEY" in r["providers"]["Apollo"]["detalhe"] and "API_KEY" in apollo.status()["motivo"]
    assert r["status"] == "FALHOU"  # nenhum provedor disponível: a rotina não finge que descobriu algo


def test_chave_recusada_ou_plano_gratuito_vira_sem_credencial_e_os_outros_continuam(con, monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "chave-de-plano-gratis")
    apollo = D.ApolloDiscoveryProvider(_http_apollo(status=403))  # docs: "somente planos pagos"
    bom = Falso("Bom", lambda c: [E(nome="Empresa Boa", cnpj=cnpj_valido("4545"), cidade="X", estado="MG")] if c.uf == "MG" else [])
    r = _rodar(con, [apollo, bom], meta=5)
    assert r["providers"]["Apollo"]["status"] == D.STATUS_SEM_CREDENCIAL and "plano" in r["providers"]["Apollo"]["detalhe"]
    assert r["providers"]["Bom"]["novas_confirmadas"] == 1 and _n(con) == 1 and r["status"] == "PARCIAL"


def test_provedor_sem_cota_fica_sem_cota_e_os_demais_continuam(con, monkeypatch):
    monkeypatch.setenv("LUSHA_API_KEY", "x")
    lusha = D.LushaDiscoveryProvider(lambda *a, **k: Resposta(429))
    bom = Falso("Bom", lambda c: [E(nome="Empresa Boa", cnpj=cnpj_valido("4646"), cidade="X", estado="PR")] if c.uf == "PR" else [])
    r = _rodar(con, [lusha, bom], meta=5)
    assert r["providers"]["Lusha"]["status"] == D.STATUS_SEM_COTA and r["providers"]["Bom"]["novas_confirmadas"] == 1


def test_todos_sem_cota_da_status_sem_cota(con, monkeypatch):
    monkeypatch.setenv("LUSHA_API_KEY", "x")
    r = _rodar(con, [D.LushaDiscoveryProvider(lambda *a, **k: Resposta(429))], meta=5)
    assert r["status"] == "SEM_COTA"


def test_provedor_indisponivel_ou_com_bug_nao_derruba_a_rotina(con):
    def quebra(c):
        raise ValueError("bug")
    def fora(c):
        raise D.ProvedorIndisponivel("serviço fora do ar")
    bom = Falso("Bom", lambda c: [E(nome="Empresa Ok", cnpj=cnpj_valido("4747"), cidade="X", estado="GO")] if c.uf == "GO" else [])
    r = _rodar(con, [Falso("Bug", quebra), Falso("Fora", fora), bom], meta=5)
    assert r["providers"]["Bug"]["status"] == D.STATUS_ERRO and r["providers"]["Fora"]["status"] == D.STATUS_INDISPONIVEL
    assert r["providers"]["Bom"]["novas_confirmadas"] == 1


def test_provedor_desligado_nao_e_chamado(con):
    p = Falso("Desligavel", lambda c: [E(nome="Nunca Deve Entrar", cnpj=cnpj_valido("1"), cidade="X", estado="SP")])
    D.definir_habilitado(con, "Desligavel", False)
    r = _rodar(con, [p], meta=5)
    assert not p.consultas and r["providers"]["Desligavel"]["status"] == D.STATUS_DESABILITADO and _n(con) == 0


def test_serpapi_maps_vem_desligado_por_padrao_e_respeita_a_reserva_da_cota(con, monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "x"); monkeypatch.setenv("SERPAPI_LIMITE_MENSAL", "100"); monkeypatch.setenv("SERPAPI_RESERVA_MANUAL", "20")
    maps = D.SerpApiMapsDiscoveryProvider(lambda *a, **k: pytest.fail("não podia chamar a API"))
    assert not D.provider_habilitado(con, maps)
    D.definir_habilitado(con, "SerpApi", True)
    fila_enriquecimento.registrar_uso(con, "SerpApi", 80)  # 100 - 20 de reserva - 80 usadas = 0
    assert maps.status(con)["estado"] == D.STATUS_SEM_COTA
    r = _rodar(con, [maps], meta=5)
    assert r["providers"]["SerpApi"]["status"] == D.STATUS_SEM_COTA


def test_credito_e_evento_sao_registrados_a_cada_chamada(con, monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "x")
    corpo = {"organizations": [{"id": "1", "name": "Empresa A", "primary_domain": "a.com.br"}, {"id": "2", "name": "Empresa B", "primary_domain": "b.com.br"}],
             "pagination": {"total_pages": 1}}
    r = _rodar(con, [D.ApolloDiscoveryProvider(_http_apollo(corpo))], meta=10, niveis=(4,))
    ev = con.execute("SELECT provider, operacao, quantidade, creditos, sucesso FROM uso_api_eventos").fetchall()
    assert len(ev) == 1 and ev[0]["provider"] == "Apollo" and ev[0]["quantidade"] == 2 and ev[0]["creditos"] == 1 and ev[0]["sucesso"] == 1
    assert fila_enriquecimento.uso_mes(con, "Apollo") == 1 and D.creditos_do_mes(con, "Apollo") == 1
    assert r["providers"]["Apollo"]["creditos"] == 1


def test_erro_tambem_gera_evento_com_sucesso_zero(con, monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "x")
    _rodar(con, [D.ApolloDiscoveryProvider(_http_apollo(status=403))], meta=5)
    assert con.execute("SELECT sucesso, detalhe FROM uso_api_eventos").fetchone()[0] == 0


def test_teto_mensal_por_provedor_e_respeitado(con, monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "x"); monkeypatch.setenv("DESCOBERTA_LIMITE_MENSAL_APOLLO", "1")
    fila_enriquecimento.registrar_uso(con, "Apollo", 1)
    apollo = D.ApolloDiscoveryProvider(lambda *a, **k: pytest.fail("teto atingido: não podia chamar"))
    assert apollo.status(con)["estado"] == D.STATUS_SEM_COTA and _rodar(con, [apollo], meta=5)["providers"]["Apollo"]["status"] == D.STATUS_SEM_COTA


# ------------------------------------------------------------------ leitura das respostas dos provedores reais
def test_provedores_pagos_montam_a_requisicao_documentada_e_enviam_a_chave_so_no_cabecalho(monkeypatch):
    monkeypatch.setenv("APOLLO_API_KEY", "SEGREDO-APOLLO"); monkeypatch.setenv("LUSHA_API_KEY", "SEGREDO-LUSHA")
    vistos = []

    def http(metodo, url, **k):
        vistos.append((metodo, url, k))
        return Resposta(200, {"organizations": []} if "apollo" in url else {"data": []})

    D.ApolloDiscoveryProvider(http).buscar(D.Consulta(1, "SP", "Guaíra", limite=25))
    D.LushaDiscoveryProvider(http).buscar(D.Consulta(3, "MG", limite=25))
    (m1, u1, k1), (m2, u2, k2) = vistos
    assert (m1, u1) == ("POST", "https://api.apollo.io/api/v1/mixed_companies/search") and k1["headers"]["x-api-key"] == "SEGREDO-APOLLO"
    assert k1["json"]["organization_locations"] == ["Guaíra, São Paulo, Brazil"]
    assert (m2, u2) == ("POST", "https://api.lusha.com/prospecting/company/search") and k2["headers"]["api_key"] == "SEGREDO-LUSHA"
    assert {"country": "Brazil", "state": "Minas Gerais"} in k2["json"]["filters"]["companies"]["include"]["locations"]
    assert "SEGREDO" not in str(k1["json"]) + str(k2["json"]) + u1 + u2  # chave nunca na URL/corpo


def test_serpapi_maps_le_local_results_sem_cnpj_e_sem_deduzir_cidade_da_consulta(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "x")
    corpo = {"local_results": [{"title": "Cooperativa Agro", "website": "https://coopagro.com.br", "place_id": "P1", "type": "Cooperativa",
                                "address": "Rua A, 10 - Orlândia - SP, 14620-000"}, {"title": "Sem Endereço", "place_id": "P2"}]}
    r = D.SerpApiMapsDiscoveryProvider(lambda *a, **k: Resposta(200, corpo)).buscar(D.Consulta(1, "SP", "Orlândia"))
    a, b = r.empresas
    assert (a.cidade, a.estado, a.cnpj) == ("Orlândia", "SP", None) and (b.cidade, b.estado) == (None, None)
    assert r.creditos == 1


def test_serpapi_maps_sem_resultados_nao_e_erro(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "x")
    r = D.SerpApiMapsDiscoveryProvider(lambda *a, **k: Resposta(200, {"error": "Google Maps hasn't returned any results for this query."})).buscar(D.Consulta(2, "SP"))
    assert r.empresas == [] and r.esgotado


def test_snov_sem_formato_de_resultado_reconhecido_se_declara_indisponivel_e_nao_inventa(con, monkeypatch):
    monkeypatch.setenv("SNOV_CLIENT_ID", "x"); monkeypatch.setenv("SNOV_CLIENT_SECRET", "y")
    http = lambda metodo, url, **k: Resposta(200, {"access_token": "t"} if "oauth" in url else {"task_hash": "abc"})
    r = _rodar(con, [D.SnovDiscoveryProvider(http)], meta=5)
    assert r["providers"]["Snov"]["status"] == D.STATUS_INDISPONIVEL and _n(con) == 0


def test_salic_herda_da_coleta_antiga_o_estado_ja_concluido_e_o_offset(con, monkeypatch):
    monkeypatch.setattr(D, "_estado_inicial_salic", lambda uf: ({"offset": 100}, True) if uf == "SP" else ({"offset": 300}, False))
    chamadas = []
    def http(metodo, url, params=None, **k):
        chamadas.append((params["UF"], params["offset"]))
        return Resposta(200, {"total": 0, "_embedded": {"incentivadores": []}})
    _rodar(con, [D.SalicDiscoveryProvider(http)], meta=5, niveis=(2, 3))
    assert all(uf != "SP" for uf, _ in chamadas)  # SP já estava concluída
    assert ("MG", 300) in chamadas  # UF em andamento retoma do offset herdado


def test_salic_le_registros_reais_com_cnpj_e_incentivo_e_atualiza_o_cursor(con):
    cnpj = cnpj_valido("5150")
    pagina = {"total": 2, "_embedded": {"incentivadores": [{"nome": "Mineradora Alfa Ltda", "cgccpf": cnpj, "UF": "MG", "municipio": "Uberaba",
                                                            "total_doado": "2500.00", "_links": {"self": "https://api.salic.cultura.gov.br/x/1"}}]}}
    provider = D.SalicDiscoveryProvider(lambda *a, **k: Resposta(200, pagina))
    r = _rodar(con, [provider], meta=5, niveis=(3,))
    assert _n(con, "SELECT COUNT(*) FROM empresas WHERE estado = 'MG' AND cnpj = ?", cnpj) == 1
    assert _n(con, "SELECT COUNT(*) FROM incentivos") >= 1 and r["providers"]["SALIC"]["novas_confirmadas"] >= 1
    assert _n(con, "SELECT COUNT(*) FROM descoberta_estado WHERE chave LIKE 'SALIC:3:MG%'") == 1


def test_reler_a_mesma_empresa_do_salic_com_outro_link_nao_conta_a_doacao_em_dobro(con):
    """Regressão de um erro real: a SALIC devolve um hash diferente no link a cada consulta; a URL sozinha deixou passar 999 repetidos."""
    cnpj = cnpj_valido("5151")
    def pagina(hash_):
        return {"total": 1, "_embedded": {"incentivadores": [{"nome": "Mineradora Beta Ltda", "cgccpf": cnpj, "UF": "MG", "municipio": "Uberaba",
                                                              "total_doado": "9000.00", "_links": {"self": f"https://api.salic.cultura.gov.br/x/{hash_}"}}]}}
    for hash_ in ("aaaa", "bbbb", "cccc"):
        con.execute("DELETE FROM descoberta_estado"); con.commit()
        _rodar(con, [D.SalicDiscoveryProvider(lambda *a, h=hash_, **k: Resposta(200, pagina(h)))], meta=5, niveis=(3,))
    assert _n(con, "SELECT COUNT(*) FROM empresas WHERE cnpj = ?", cnpj) == 1
    assert _n(con, "SELECT COUNT(*) FROM incentivos") == 1
    assert con.execute("SELECT SUM(valor) FROM incentivos").fetchone()[0] == 9000.0


def test_incentivo_diferente_da_mesma_empresa_continua_sendo_registrado(con):
    cnpj = cnpj_valido("5252")
    def rodar(valor):
        pag = {"total": 1, "_embedded": {"incentivadores": [{"nome": "Beta Dois Ltda", "cgccpf": cnpj, "UF": "MG", "municipio": "Uberaba",
                                                             "total_doado": valor, "_links": {"self": f"https://api.salic.cultura.gov.br/x/{valor}"}}]}}
        con.execute("DELETE FROM descoberta_estado"); con.commit()
        _rodar(con, [D.SalicDiscoveryProvider(lambda *a, **k: Resposta(200, pag))], meta=5, niveis=(3,))
    rodar("1000.00"); rodar("2000.00")
    assert _n(con, "SELECT COUNT(*) FROM incentivos") == 2


# ------------------------------------------------------------------ Rotina diária em etapas
def test_rotina_grava_as_quatro_etapas_com_status_e_falha_de_uma_nao_derruba_as_outras(con):
    df_vazio = lambda: metricas.carregar_empresas(con)
    p = Falso("Prov", lambda c: [E(nome="Nova Empresa", cnpj=cnpj_valido("6001"), cidade="X", estado="MG")] if c.uf == "MG" else [])
    resumo = rotina_etapas.executar_rotina(con, perfil=PERFIL, carregar_df=df_vazio, providers_descoberta=[p], providers_contato=[],
                                           meta_descoberta=5, dormir=lambda s: None)
    etapas = {e["etapa"]: e for e in rotina_etapas.etapas_do_dia(con)}
    assert list(etapas) == ["Descoberta", "Enriquecimento", "Contatos", "Editais"]
    assert etapas["Descoberta"]["status"] in ("CONCLUIDO", "PARCIAL") and "nova(s)" in etapas["Descoberta"]["detalhe"]
    assert etapas["Editais"]["status"] == "PENDENTE"
    assert resumo["etapas"]["Descoberta"] == etapas["Descoberta"]["status"]


def test_rotina_com_descoberta_falhando_ainda_executa_enriquecimento(con):
    def explode(c):
        raise D.ProvedorIndisponivel("fora")
    resumo = rotina_etapas.executar_rotina(con, perfil=PERFIL, carregar_df=lambda: metricas.carregar_empresas(con),
                                           providers_descoberta=[Falso("Fora", explode)], providers_contato=[], dormir=lambda s: None)
    e = {x["etapa"]: x["status"] for x in rotina_etapas.etapas_do_dia(con)}
    assert e["Descoberta"] == "FALHOU" and e["Enriquecimento"] in ("CONCLUIDO", "PARCIAL", "SEM_COTA") and e["Contatos"] == "CONCLUIDO"


def test_etapas_sem_execucao_aparecem_como_pendentes(con):
    assert [e["status"] for e in rotina_etapas.etapas_do_dia(con)] == ["PENDENTE"] * 4


# ------------------------------------------------------------------ situação para a interface
def test_situacao_dos_provedores_lista_todos_sem_prometer_o_que_nao_foi_validado(con):
    linhas = {l["provider"]: l for l in D.situacao_providers(con)}
    assert set(linhas) == {"SALIC", "SerpApi", "Apollo", "Lusha", "Snov"}
    assert linhas["SALIC"]["validado"] and linhas["SALIC"]["estado"] == D.STATUS_DISPONIVEL
    for nome in ("Apollo", "Lusha", "Snov"):
        assert not linhas[nome]["validado"] and linhas[nome]["estado"] == D.STATUS_SEM_CREDENCIAL and "conector do Claude" in linhas[nome]["acesso"]
    assert linhas["SerpApi"]["habilitado"] is False


# ------------------------------------------------------------------ banco real
def test_migracao_no_banco_real_nao_perde_dado_e_deixa_tudo_confirmado(tmp_path):
    if not BANCO.exists():
        pytest.skip("banco real não disponível")
    copia = tmp_path / "real.db"
    shutil.copy(BANCO, copia)
    con = banco.conectar(copia)
    antes = {t: _n(con, f"SELECT COUNT(*) FROM {t}") for t in ("empresas", "incentivos", "contatos", "editais")}
    D.criar_tabelas(con)
    D.criar_tabelas(con)  # idempotente
    depois = {t: _n(con, f"SELECT COUNT(*) FROM {t}") for t in antes}
    assert antes == depois
    assert _n(con, "SELECT COUNT(*) FROM empresas WHERE estagio_cadastro != 'CONFIRMADA'") == 0
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    df = metricas.carregar_empresas(con)
    assert int(df["eh_prospect"].sum()) + int(df["linha_cruzada"].sum()) >= len(df)  # ninguém virou candidata por engano
