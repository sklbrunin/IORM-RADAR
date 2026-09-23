"""Regressões da rodada v8 — busca de editais persistente, com cache e sem gastar a API para reexibir.

Caso real de referência (Miguelópolis, Prosas):
https://prosas.com.br/editais/19173-edital-001-2026-fomento-a-projetos-culturais-miguel-polis
"""
from __future__ import annotations

import html as _html
import json
import sqlite3
from datetime import date, timedelta

import pytest

from processamento import busca_editais, busca_providers, editais, fila_enriquecimento, links_editais

URL_MIGUELOPOLIS = "https://prosas.com.br/editais/19173-edital-001-2026-fomento-a-projetos-culturais-miguel-polis"
TITULO_PROSAS = "Prosas | Edital - EDITAL 001/2026- FOMENTO A PROJETOS CULTURAIS"

PERFIL = {
    "cidades": ["Guaíra", "Ipuã", "Miguelópolis", "Orlândia"], "estados": ["SP"],
    "temas": ["cultura", "dança", "educação"], "palavras_chave": [], "programas": [], "territorios": [],
}


def _html_prosas(inicio: date, fim: date, *, andamento=True, encerrada=False, prorrogada=False) -> str:
    """Página no formato real do Prosas: o objeto da oportunidade vai dentro do HTML, com aspas escapadas."""
    oportunidade = {
        "id": 19173, "nome": "EDITAL 001/2026- FOMENTO A PROJETOS CULTURAIS -MIGUELÓPOLIS",
        "descricao": ("<p>Olá, agentes culturais do Município de MIGUELÓPOLIS!</p><p>1.3 Valor total do edital "
                      "O valor total deste edital é de 90.000,00 (Noventa Mil Reais) Cada um dos 4 (Quatro) projetos "
                      "receberá R$2.250,00. Para se inscrever neste Edital as Pessoas Físicas deverão ser residentes "
                      "no município de MIGUELÓPOLIS há pelo menos 2(Dois) ano.</p>"),
        "inicio_inscricoes": f"{inicio.isoformat()}T12:00:36.000-03:00",
        "encerramento_das_inscricoes": f"{fim.isoformat()}T17:00:00.000-03:00",
        "prorrogacao_ok": prorrogada, "subscription_in_progress": andamento, "subscription_not_started": False,
        "subscription_closed": encerrada,
        "culturas": [{"id": 2, "nome": "Dança"}, {"id": 1, "nome": "Circo"}],
        "publico_alvos": [{"id": 1, "nome": "Infância e Adolescência"}],
    }
    escapado = _html.escape(json.dumps(oportunidade, ensure_ascii=False), quote=True)
    return (f"<html><head><title>{TITULO_PROSAS}</title></head><body>EDITAL 001/2026 FOMENTO A PROJETOS CULTURAIS "
            f"MIGUELÓPOLIS <div ng-init=\"x={escapado}\"></div></body></html>")


class ProviderFalso(busca_providers.SearchProvider):
    """Conta as chamadas recebidas; devolve resultados conforme um dicionário {trecho da consulta: [resultados]}."""

    nome = "ProviderTeste"

    def __init__(self, respostas: dict | None = None):
        self.respostas = respostas or {}
        self.chamadas: list[tuple] = []
        self.ultimo_erro = None

    def disponivel(self):
        return True

    def buscar(self, query, num_resultados=5, inicio=0, recencia=None):
        self.chamadas.append((query, inicio, recencia))
        for trecho, resultados in self.respostas.items():
            if trecho in query:
                return resultados[inicio: inicio + num_resultados]
        return []


def _res(titulo, url, trecho=None):
    return busca_providers.ResultadoBusca(titulo=titulo, url=url, trecho=trecho)


@pytest.fixture
def conexao():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    editais.criar_tabelas(conn)
    fila_enriquecimento.criar_tabelas(conn)
    yield conn
    conn.close()


def _pagina_miguelopolis(hoje=None, **kw):
    hoje = hoje or date.today()
    conteudo = _html_prosas(hoje - timedelta(days=1), hoje + timedelta(days=16), **kw)
    return lambda url: (200, url, conteudo)


def _provider_miguelopolis():
    return ProviderFalso({"site:prosas.com.br/editais Miguelópolis": [_res(TITULO_PROSAS, URL_MIGUELOPOLIS,
                                                                            "Município de Miguelópolis abre edital de fomento")]})


# ------------------------------------------------------------------ plano de busca (cobertura)
def test_plano_tem_consulta_por_municipio_no_prosas_e_nao_e_fixo_em_miguelopolis():
    plano = busca_editais.montar_plano_de_busca(PERFIL, max_consultas=20)
    consultas = [p["consulta"] for p in plano]
    ano = editais.hoje_brasil().year
    assert f"site:prosas.com.br/editais Miguelópolis {ano}" in consultas
    for cidade in PERFIL["cidades"]:  # geral: uma por município do Cérebro da OSC
        assert any(cidade in c and "prosas.com.br/editais" in c for c in consultas)
    outro = busca_editais.montar_plano_de_busca({**PERFIL, "cidades": ["Cidade Nova"]}, max_consultas=20)
    assert any("Cidade Nova" in p["consulta"] for p in outro) and not any("Miguelópolis" in p["consulta"] for p in outro)


def test_plano_respeita_o_teto_e_prioriza_municipio_no_prosas():
    plano = busca_editais.montar_plano_de_busca(PERFIL, max_consultas=5)
    assert len(plano) == 5 and all(p["prioridade"] == 0 for p in plano[:4])
    assert len(busca_editais.montar_plano_de_busca(PERFIL, max_consultas=100)) <= 11 + 5


def test_plano_usa_fontes_cadastradas_alem_das_ja_cobertas():
    fontes = [{"url": "https://produtos.prosas.com.br/editais"}, {"url": "https://editais.exemplo.org.br/lista"}]
    plano = busca_editais.montar_plano_de_busca(PERFIL, fontes_extra=fontes, max_consultas=50)
    extras = [p for p in plano if p["prioridade"] == 3]
    assert len(extras) == 1 and "site:editais.exemplo.org.br" in extras[0]["consulta"]  # o Prosas já estava coberto


# ------------------------------------------------------------------ caso Miguelópolis: persistir, situação, sem duplicar
def test_miguelopolis_e_encontrado_persistido_com_prazo_e_valor_da_pagina(conexao):
    provider = _provider_miguelopolis()
    rel = busca_editais.executar_busca(conexao, PERFIL, provider, buscador=_pagina_miguelopolis())
    assert rel["novos"] == 1 and rel["verificados"] == 1 and rel["resultados_unicos"] == 1
    e = conexao.execute("SELECT * FROM editais WHERE url = ?", (URL_MIGUELOPOLIS,)).fetchone()
    assert e is not None
    assert e["origem_descoberta"] == "AUTOMATICA" and "prosas.com.br" in e["fonte"]
    assert e["municipios_detectados"] == "Miguelópolis" and e["territorio"] == "Miguelópolis (SP)"
    assert e["tipo"] == "EDITAL" and "FOMENTO A PROJETOS CULTURAIS" in e["titulo"]
    # dados estruturados da página: prazo, abertura, valor total, áreas, público, elegibilidade
    assert e["prazo_origem"] == "FONTE_ESTRUTURADA"
    assert e["data_encerramento"] == (date.today() + timedelta(days=16)).isoformat()
    assert e["data_abertura"] == (date.today() - timedelta(days=1)).isoformat()
    assert e["valor_numerico"] == 90000.0 and "90.000,00" in e["valor_texto"]
    assert "Dança" in e["area_tematica"] and "Infância" in e["publico"]
    assert "Pessoas Físicas" in e["requisitos"]  # elegibilidade literal (a OSC precisa conferir)
    assert e["link_status"] == links_editais.STATUS_ESPECIFICA
    assert editais.situacao_efetiva(e)[0] == "ABERTO"


def test_miguelopolis_aparece_em_abertos_e_na_alta_aderencia_sem_nova_api(conexao):
    provider = _provider_miguelopolis()
    busca_editais.executar_busca(conexao, PERFIL, provider, buscador=_pagina_miguelopolis())
    chamadas = len(provider.chamadas)
    todos = editais.listar_editais(conexao)  # "sair da aba e voltar": só banco
    grupos = editais.agrupar_por_situacao(todos)
    assert [e["url"] for e in grupos["abertos"]] == [URL_MIGUELOPOLIS]
    itens = editais.abertos_com_aderencia(todos, {**PERFIL, "programas": [{"publico": "crianças e adolescentes"}]})
    assert itens and itens[0]["aderencia"]["criterios_avaliados"] >= 3
    assert len(provider.chamadas) == chamadas  # reexibir não chama o provedor


def test_segunda_busca_usa_cache_nao_chama_api_e_nao_duplica(conexao):
    provider = _provider_miguelopolis()
    primeira = busca_editais.executar_busca(conexao, PERFIL, provider, buscador=_pagina_miguelopolis())
    assert primeira["chamadas_api"] == primeira["consultas_planejadas"] > 0 and primeira["consultas_do_cache"] == 0
    chamadas_antes = len(provider.chamadas)
    segunda = busca_editais.executar_busca(conexao, PERFIL, provider, buscador=_pagina_miguelopolis())
    assert len(provider.chamadas) == chamadas_antes  # ZERO chamadas novas ao provedor
    assert segunda["chamadas_api"] == 0 and segunda["consultas_do_cache"] == primeira["consultas_planejadas"]
    assert segunda["novos"] == 0 and segunda["ja_existentes"] == 1
    assert conexao.execute("SELECT COUNT(*) FROM editais WHERE url = ?", (URL_MIGUELOPOLIS,)).fetchone()[0] == 1


def test_so_atualizar_busca_chama_o_provedor_de_novo(conexao):
    provider = _provider_miguelopolis()
    busca_editais.executar_busca(conexao, PERFIL, provider, buscador=_pagina_miguelopolis())
    n = len(provider.chamadas)
    forcada = busca_editais.executar_busca(conexao, PERFIL, provider, forcar=True, buscador=_pagina_miguelopolis())
    assert len(provider.chamadas) == 2 * n and forcada["forcada"] and forcada["chamadas_api"] == n
    assert conexao.execute("SELECT COUNT(*) FROM editais").fetchone()[0] == 1  # nada duplicado


def test_cache_expirado_volta_a_consultar(conexao):
    provider = _provider_miguelopolis()
    agora = editais.datetime.now(editais.timezone.utc)
    busca_editais.executar_busca(conexao, PERFIL, provider, buscador=_pagina_miguelopolis(), agora=agora)
    n = len(provider.chamadas)
    busca_editais.executar_busca(conexao, PERFIL, provider, buscador=_pagina_miguelopolis(),
                                 agora=agora + timedelta(days=busca_editais.CACHE_DIAS + 1))
    assert len(provider.chamadas) == 2 * n


def test_relatorio_fica_gravado_e_o_cache_e_persistente(conexao):
    provider = _provider_miguelopolis()
    busca_editais.executar_busca(conexao, PERFIL, provider, buscador=_pagina_miguelopolis())
    rel = busca_editais.ultima_execucao(conexao)
    assert rel["novos"] == 1 and rel["por_municipio"] == {"Miguelópolis": 1} and "prosas.com.br" in rel["por_fonte"]
    assert busca_editais.situacao_do_cache(conexao)["consultas_validas"] == rel["consultas_planejadas"]
    assert conexao.execute("SELECT SUM(chamadas_api) FROM busca_editais_cache").fetchone()[0] == rel["chamadas_api"]


# ------------------------------------------------------------------ editais vencidos / sem prazo / encerrados
def _persistir(conexao, titulo, url, trecho=None, pagina=None):
    provider = ProviderFalso({"site:prosas.com.br/editais Guaíra": [_res(titulo, url, trecho)]})
    buscador = pagina or (lambda u: (200, u, f"<html><title>{titulo}</title><body>{titulo}</body></html>"))
    busca_editais.executar_busca(conexao, PERFIL, provider, buscador=buscador)
    return conexao.execute("SELECT * FROM editais WHERE url = ?", (url,)).fetchone()


def test_edital_de_2025_e_encerrado_fica_no_historico_e_nao_entra_em_abertos_nem_alta_aderencia(conexao):
    ano_anterior = editais.hoje_brasil().year - 1
    e = _persistir(conexao, f"Edital de Fomento à Cultura {ano_anterior}", f"https://prosas.com.br/editais/111-edital-cultura-{ano_anterior}")
    situacao, motivo = editais.situacao_efetiva(e)
    assert situacao == "ENCERRADO" and str(ano_anterior) in motivo
    grupos = editais.agrupar_por_situacao(editais.listar_editais(conexao))
    assert e["id"] in [x["id"] for x in grupos["encerrados"]] and not grupos["abertos"]
    assert editais.abertos_com_aderencia(editais.listar_editais(conexao), PERFIL, nota_minima=1.0) == []


def test_edital_sem_prazo_confiavel_e_nao_confirmado(conexao):
    e = _persistir(conexao, "Chamamento público de cultura", "https://prosas.com.br/editais/222-chamamento-de-cultura")
    assert editais.situacao_efetiva(e)[0] == "NAO_CONFIRMADO"
    assert [x["id"] for x in editais.agrupar_por_situacao(editais.listar_editais(conexao))["nao_confirmados"]] == [e["id"]]


def test_pagina_dizendo_encerrado_e_encerrado(conexao):
    titulo = "Edital de apoio a projetos culturais"
    pagina = lambda u: (200, u, f"<html><title>{titulo}</title><body>{titulo}. As inscrições estão encerradas.</body></html>")
    e = _persistir(conexao, titulo, "https://prosas.com.br/editais/333-apoio-a-projetos", pagina=pagina)
    assert editais.situacao_efetiva(e)[0] == "ENCERRADO"


def test_prazo_futuro_com_link_e_aberto_e_prazo_passado_e_encerrado():
    base = {"titulo": "Edital X", "url": "https://x.gov.br/edital-x", "origem_descoberta": "AUTOMATICA"}
    hoje = editais.hoje_brasil()
    assert editais.situacao_efetiva({**base, "data_encerramento": (hoje + timedelta(days=3)).isoformat()})[0] == "ABERTO"
    assert editais.situacao_efetiva({**base, "data_encerramento": (hoje - timedelta(days=1)).isoformat()})[0] == "ENCERRADO"


def test_ano_anterior_no_titulo_nao_vence_prazo_confirmado_pela_equipe():
    base = {"titulo": "Edital 2025 prorrogado", "url": "https://x.gov.br/edital-2025", "prazo_origem": "CONFIRMADO_PELA_EQUIPE",
            "data_encerramento": (editais.hoje_brasil() + timedelta(days=10)).isoformat()}
    assert editais.situacao_efetiva(base)[0] == "ABERTO"


def test_ano_no_titulo_igual_ou_maior_que_o_atual_nao_marca_como_historico():
    ano = editais.hoje_brasil().year
    assert editais.situacao_efetiva({"titulo": f"Edital {ano - 1}/{ano}", "url": "https://x.gov.br/e"})[0] == "NAO_CONFIRMADO"


def test_hoje_nao_e_fixo_no_codigo():
    assert abs((editais.hoje_brasil() - date.today()).days) <= 1


def test_prorrogacao_na_pagina_vira_sugestao_e_a_decisao_da_equipe_prevalece(conexao):
    hoje = date.today()
    pagina = _pagina_miguelopolis(prorrogada=True)
    e = _persistir_miguelopolis(conexao, pagina)
    assert e["data_encerramento"] is None and e["prazo_sugerido"] == (hoje + timedelta(days=16)).isoformat()
    assert editais.situacao_efetiva(e)[0] == "NAO_CONFIRMADO"


def _persistir_miguelopolis(conexao, pagina):
    busca_editais.executar_busca(conexao, PERFIL, _provider_miguelopolis(), buscador=pagina)
    return conexao.execute("SELECT * FROM editais WHERE url = ?", (URL_MIGUELOPOLIS,)).fetchone()


# ------------------------------------------------------------------ deduplicação e filtros
def test_dedup_por_url_canonica_ignora_utm_barra_final_e_www():
    a = "https://www.prosas.com.br/editais/1-x/?utm_source=google&fbclid=1"
    b = "http://prosas.com.br/editais/1-x"
    assert busca_editais.canonicalizar_url(a) == busca_editais.canonicalizar_url(b)


def test_resultados_repetidos_em_consultas_diferentes_viram_um_registro(conexao):
    url = "https://prosas.com.br/editais/444-edital-de-danca"
    repetido = _res("Edital de Dança", url + "/?utm_source=x")
    provider = ProviderFalso({"site:prosas.com.br/editais": [repetido], "site:gov.br": [_res("Edital de Dança", url)]})
    rel = busca_editais.executar_busca(conexao, PERFIL, provider, verificar=False)
    assert conexao.execute("SELECT COUNT(*) FROM editais").fetchone()[0] == 1 and rel["resultados_unicos"] == 1


def test_descarta_portal_generico_perfil_de_osc_e_o_que_nao_e_edital(conexao):
    provider = ProviderFalso({"site:prosas.com.br/editais": [
        _res("Central de Editais", "https://produtos.prosas.com.br/editais"),
        _res("TEATRO MAQUINA", "https://mapaosc.ipea.gov.br/detalhar/444271"),
        _res("Prefeito inaugura praça", "https://noticias.exemplo.com/prefeito-inaugura-praca"),
        _res("Edital de Circo", "https://prosas.com.br/editais/555-edital-de-circo"),
    ]})
    rel = busca_editais.executar_busca(conexao, PERFIL, provider, verificar=False)
    assert rel["novos"] == 1 and rel["descartados"] == {"portal_generico": 1, "perfil_de_osc": 1, "nao_parece_edital": 1}
    assert [r["titulo"] for r in conexao.execute("SELECT titulo FROM editais")] == ["Edital de Circo"]


def test_nao_cria_link_de_inscricao_que_nao_existe(conexao):
    e = _persistir(conexao, "Edital de Teatro", "https://prosas.com.br/editais/666-edital-de-teatro")
    assert e["url_inscricao"] is None


# ------------------------------------------------------------------ cobertura: paginação, teto, cota, erro
def test_paginacao_pede_a_segunda_pagina_quando_a_primeira_vem_cheia(conexao):
    resultados = [_res(f"Edital {i} de cultura", f"https://prosas.com.br/editais/{1000 + i}-edital-{i}") for i in range(14)]
    provider = ProviderFalso({"site:prosas.com.br/editais Guaíra": resultados})
    rel = busca_editais.executar_busca(conexao, PERFIL, provider, paginas=3, verificar=False, max_consultas=1)
    inicios = [c[1] for c in provider.chamadas]
    assert inicios == [0, 10]  # 2ª página trouxe 4 (< 10): não pede a 3ª
    assert rel["resultados_brutos"] == 14 and rel["novos"] == 14  # 14 > os 15 de antes só com paginação/múltiplas consultas


def test_muito_mais_cobertura_que_o_limite_antigo_de_15_resultados(conexao):
    respostas = {}
    for i, cidade in enumerate(PERFIL["cidades"]):
        respostas[f"site:prosas.com.br/editais {cidade}"] = [
            _res(f"Edital {cidade} {n}", f"https://prosas.com.br/editais/{i}{n:03d}-edital-{cidade.lower()}-{n}") for n in range(8)]
    rel = busca_editais.executar_busca(conexao, PERFIL, ProviderFalso(respostas), verificar=False)
    assert rel["novos"] == 32 and rel["por_municipio"] == {c: 8 for c in PERFIL["cidades"]}
    assert rel["consultas_planejadas"] >= 8  # vs 3 consultas × 5 resultados do desenho antigo


def test_recencia_e_repassada_ao_provedor(conexao):
    provider = ProviderFalso()
    busca_editais.executar_busca(conexao, PERFIL, provider, verificar=False, max_consultas=2)
    assert all(c[2] == "y" for c in provider.chamadas)


def test_provedor_antigo_sem_inicio_e_recencia_continua_funcionando(conexao):
    class Antigo(busca_providers.SearchProvider):
        nome = "Antigo"
        chamadas = 0

        def disponivel(self):
            return True

        def buscar(self, query, num_resultados=5):
            Antigo.chamadas += 1
            return []

    busca_editais.executar_busca(conexao, PERFIL, Antigo(), verificar=False, max_consultas=2)
    assert Antigo.chamadas == 2


class SerpApiFalsa(ProviderFalso):
    nome = "SerpApi"


def test_orcamento_mensal_da_serpapi_e_respeitado_e_o_uso_e_registrado(conexao, monkeypatch):
    monkeypatch.setenv("SERPAPI_LIMITE_MENSAL", "3")
    provider = SerpApiFalsa()
    rel = busca_editais.executar_busca(conexao, PERFIL, provider, verificar=False, max_consultas=10)
    assert len(provider.chamadas) == 3 and rel["chamadas_api"] == 3 and rel["orcamento_esgotado"]
    assert fila_enriquecimento.uso_mes(conexao, "SerpApi") == 3
    n = len(provider.chamadas)  # sem orçamento, mas as 3 já feitas estão em cache: reexibir continua funcionando
    rel2 = busca_editais.executar_busca(conexao, PERFIL, provider, verificar=False, max_consultas=3)
    assert len(provider.chamadas) == n and rel2["chamadas_api"] == 0 and not rel2["orcamento_esgotado"]


def test_erro_do_provedor_interrompe_e_nao_grava_cache_de_erro(conexao):
    class ComErro(ProviderFalso):
        def buscar(self, query, num_resultados=5, inicio=0, recencia=None):
            self.chamadas.append(query)
            self.ultimo_erro = "A SerpApi retornou um erro: teste"
            return []

    provider = ComErro()
    rel = busca_editais.executar_busca(conexao, PERFIL, provider, verificar=False)
    assert len(provider.chamadas) == 1 and rel["erros"] and rel["novos"] == 0
    assert conexao.execute("SELECT COUNT(*) FROM busca_editais_cache").fetchone()[0] == 0


def test_sem_provedor_configurado_nao_chama_nada(conexao):
    rel = busca_editais.executar_busca(conexao, PERFIL, busca_providers.FilaManualProvider(), verificar=False)
    assert rel["chamadas_api"] == 0 and rel["erros"]


# ------------------------------------------------------------------ verificação do caso real (rede; pula se offline)
def _rede_ok() -> bool:
    try:
        import requests

        return requests.get("https://prosas.com.br", timeout=8).status_code < 500
    except Exception:
        return False


@pytest.mark.skipif(not _rede_ok(), reason="sem acesso à internet para conferir a página pública do Prosas")
def test_pagina_real_de_miguelopolis_traz_prazo_valor_e_municipio():
    r = links_editais.verificar_link(URL_MIGUELOPOLIS, "EDITAL 001/2026 – FOMENTO A PROJETOS CULTURAIS – MIGUELÓPOLIS")
    assert r["status"] == links_editais.STATUS_ESPECIFICA
    d = r["dados_estruturados"]
    assert d is not None, "a página deixou de trazer o objeto estruturado — revisar links_editais.extrair_dados_estruturados"
    assert "MIGUELÓPOLIS" in d["nome"].upper() and d["encerramento"] == "2026-10-09" and d["inicio"] == "2026-09-23"
    assert d["valor_total_texto"] == "90.000,00"
    assert busca_editais.detectar_municipios(d["nome"], PERFIL["cidades"]) == ["Miguelópolis"]


# ------------------------------------------------------------------ detecção de município
@pytest.mark.parametrize("texto", [
    "EDITAL 001/2026 – FOMENTO A PROJETOS CULTURAIS – MIGUELÓPOLIS", URL_MIGUELOPOLIS, "prefeitura de miguelopolis",
])
def test_detecta_miguelopolis_em_titulo_url_e_sem_acento(texto):
    assert busca_editais.detectar_municipios(texto, PERFIL["cidades"]) == ["Miguelópolis"]


def test_nao_detecta_municipio_ausente():
    assert busca_editais.detectar_municipios("Edital de São Paulo", PERFIL["cidades"]) == []

# ------------------------------------------------------------------ cadastro pelo link (edital recebido pela equipe)
def test_cadastrar_por_url_miguelopolis_salva_e_le_prazo_valor_e_municipio(conexao):
    r = busca_editais.cadastrar_por_url(conexao, URL_MIGUELOPOLIS, PERFIL, buscador=_pagina_miguelopolis())
    assert r["novo"] and r["situacao"] == "ABERTO" and "MIGUELÓPOLIS" in r["titulo"].upper()
    e = conexao.execute("SELECT * FROM editais WHERE id = ?", (r["id"],)).fetchone()
    assert e["territorio"] == "Miguelópolis (SP)" and e["valor_numerico"] == 90000.0
    assert e["data_encerramento"] == (date.today() + timedelta(days=16)).isoformat() and e["prazo_origem"] == "FONTE_ESTRUTURADA"
    assert e["url_inscricao"] is None and e["origem_descoberta"] == "MANUAL"


def test_cadastrar_por_url_nao_duplica_e_a_busca_reconhece_o_mesmo_edital(conexao):
    busca_editais.cadastrar_por_url(conexao, URL_MIGUELOPOLIS, PERFIL, buscador=_pagina_miguelopolis())
    segundo = busca_editais.cadastrar_por_url(conexao, URL_MIGUELOPOLIS + "/?utm_source=whatsapp", PERFIL, buscador=_pagina_miguelopolis())
    assert segundo["novo"] is False
    rel = busca_editais.executar_busca(conexao, PERFIL, _provider_miguelopolis(), buscador=_pagina_miguelopolis())
    assert rel["novos"] == 0 and rel["ja_existentes"] == 1
    assert conexao.execute("SELECT COUNT(*) FROM editais").fetchone()[0] == 1


def test_cadastrar_por_url_erros_claros(conexao):
    with pytest.raises(ValueError, match="http"):
        busca_editais.cadastrar_por_url(conexao, "prosas sem esquema", PERFIL)
    with pytest.raises(ValueError, match="HTTP 404"):
        busca_editais.cadastrar_por_url(conexao, "https://x.gov.br/nada", PERFIL, buscador=lambda u: (404, u, ""))

    def cai(u):
        raise TimeoutError("sem resposta")

    with pytest.raises(ValueError, match="abrir a página"):
        busca_editais.cadastrar_por_url(conexao, "https://x.gov.br/e", PERFIL, buscador=cai)
    with pytest.raises(ValueError, match="título"):
        busca_editais.cadastrar_por_url(conexao, "https://x.gov.br/e", PERFIL, buscador=lambda u: (200, u, "<html><body>oi</body></html>"))
    assert conexao.execute("SELECT COUNT(*) FROM editais").fetchone()[0] == 0  # nada é salvo quando dá erro


@pytest.mark.skipif(not _rede_ok(), reason="sem acesso à internet")
def test_cadastrar_por_url_com_a_pagina_real_de_miguelopolis(conexao):
    r = busca_editais.cadastrar_por_url(conexao, URL_MIGUELOPOLIS, PERFIL)
    e = conexao.execute("SELECT * FROM editais WHERE id = ?", (r["id"],)).fetchone()
    assert e["data_encerramento"] == "2026-10-09" and e["data_abertura"] == "2026-09-23" and e["valor_numerico"] == 90000.0
    hoje = editais.hoje_brasil()
    esperado = "ABERTO" if date(2026, 9, 23) <= hoje <= date(2026, 10, 9) else ("ENCERRADO" if hoje > date(2026, 10, 9) else "NAO_CONFIRMADO")
    assert r["situacao"] == esperado
    assert "Dança" in e["area_tematica"] and e["territorio"] == "Miguelópolis (SP)"


# ------------------------------------------------------------------ filtros de qualidade
@pytest.mark.parametrize("titulo,url,motivo", [
    ("Chamada cultural", "https://guaira.pr.gov.br/editais/chamada-cultural", "outra_uf"),
    ("Concurso Público 01/2026", "https://orlandia.sp.gov.br/editais/concurso-01-2026", "outro_tipo_de_edital"),
    ("Edital de licitação nº 5", "https://ipua.sp.gov.br/edital-licitacao-5", "outro_tipo_de_edital"),
])
def test_filtros_de_outra_uf_e_de_outro_tipo_de_edital(titulo, url, motivo):
    assert busca_editais.avaliar_resultado({"titulo": titulo, "url": url}, ["SP"]) == (False, motivo)


def test_dominio_do_mesmo_estado_e_federal_continuam_aceitos():
    assert busca_editais.avaliar_resultado({"titulo": "Edital de fomento à cultura", "url": "https://orlandia.sp.gov.br/editais/fomento-2026"}, ["SP"])[0]
    assert busca_editais.avaliar_resultado({"titulo": "Edital de fomento à cultura", "url": "https://www.gov.br/cultura/pt-br/edital-fomento-2026"}, ["SP"])[0]

@pytest.mark.parametrize("titulo,url", [
    ("Prosas | Listagem de editais", "https://prosas.com.br/editais?locale=en"),
    ("Portal do Fomento", "https://www.cultura.sp.gov.br/sec_cultura/Fomento/Portal_do_Fomento"),
    ("Edital de Abertura Nº 26/2026 - UFG", "https://sistemas.institutoverbena.ufg.edu.br/2027/ps"),
    ("Edital nº 008/2026 - Professor Efetivo", "https://cmop.exemplo.org/edital-008-2026"),
])
def test_filtra_listagens_portais_e_selecoes_de_universidades(titulo, url):
    assert busca_editais.avaliar_resultado({"titulo": titulo, "url": url}, ["SP"])[0] is False

def test_filtra_dominios_de_universidades_e_institutos_federais():
    for url in ("https://sistemas.institutoverbena.ufg.br/2027/ps", "https://www.uema.br/2026/09/edital-243/", "https://cmop.ufs.br/edital-8",
                "https://portal.ufrrj.br/edital-de-abertura"):
        assert busca_editais.avaliar_resultado({"titulo": "Edital nº 1/2026", "url": url}, ["SP"]) == (False, "outro_tipo_de_edital")
    assert busca_editais.avaliar_resultado({"titulo": "Edital de fomento à cultura", "url": "https://www.guaira.sp.gov.br/edital-pnab"}, ["SP"])[0]
