"""Projetos do IORM × edital (v9): adequação temática determinística, separada da elegibilidade, com persistência."""
from __future__ import annotations

import shutil
import sqlite3
import textwrap
from datetime import date, timedelta
from pathlib import Path

import pytest

from processamento import editais, osc, projetos_editais as P

RAIZ = Path(__file__).resolve().parent.parent
BANCO = RAIZ / "dados" / "iorm_radar.db"


def _programa(id_, nome, tema=None, **extra):
    return {"id": id_, "nome": nome, "tema": tema, "descricao": None, "publico": None, "faixa_etaria": None,
            "cidade": None, "estado": "SP", "objetivos": None, "status": "ATIVO", **extra}


def _perfil(programas=None):
    """Perfil no formato de osc.carregar_perfil_completo, com o mesmo desenho do Cérebro real (programas só com nome + tema)."""
    programas = programas if programas is not None else [
        _programa(1, "Música: A Linguagem Universal", "Música"),
        _programa(2, "Usina da Dança", "Dança"),
        _programa(3, "Artes e Cultura", "Teatro e literatura"),
        _programa(6, "Profissionalizando Pessoas", "Qualificação profissional"),
    ]
    territorios = [{"tipo": "cidade", "valor": v, "prioritario": 1} for v in ("Guaíra", "Ipuã", "Miguelópolis", "Orlândia")]
    territorios.append({"tipo": "estado", "valor": "SP", "prioritario": 0})
    return {"territorios": territorios, "cidades": ["Guaíra", "Ipuã", "Miguelópolis", "Orlândia"], "estados": ["SP"],
            "temas": ["arte", "cultura", "dança"], "palavras_chave": ["juventude"], "programas": programas, "mecanismos": ["Lei Rouanet"]}


def _edital(**campos):
    base = {"id": 1, "titulo": "Edital de fomento", "descricao": "", "area_tematica": None, "territorio": None, "publico": None,
            "requisitos": None, "texto_resumo": None}
    return {**base, **campos}


def _por_nome(resultado, nome):
    return next(p for p in resultado["projetos"] if p["nome"] == nome)


# ------------------------------------------------------------------ casos de regra
def test_edital_cultural_de_danca_relaciona_usina_da_danca_e_nao_forca_projeto_sem_relacao():
    edital = _edital(titulo="Edital de Dança e Teatro", territorio="Guaíra (SP)",
                     descricao="Apoio a projetos culturais de dança e teatro com oficinas para a comunidade.")
    r = P.analisar(edital, _perfil())
    assert _por_nome(r, "Usina da Dança")["nivel"] == P.NIVEL_ALTA
    assert _por_nome(r, "Artes e Cultura")["nivel"] == P.NIVEL_ALTA  # teatro declarado no título
    assert _por_nome(r, "Profissionalizando Pessoas")["nivel"] == P.NIVEL_NAO_IDENTIFICADA


def test_edital_nao_cultural_nao_forca_relacao_com_nenhum_projeto():
    edital = _edital(titulo="Chamada para equipamentos hospitalares", descricao="Aquisição de leitos e equipamentos de saúde.",
                     territorio="Nacional")
    r = P.analisar(edital, _perfil())
    assert all(p["nivel"] == P.NIVEL_NAO_IDENTIFICADA for p in r["projetos"])
    assert P.carregar_analise  # sanidade da API


def test_programa_com_dados_insuficientes_nao_recebe_conclusao_inventada():
    perfil = _perfil([_programa(9, "Projeto Futuro")])  # só o nome, sem tema/descrição
    r = P.analisar(_edital(titulo="Edital de dança", area_tematica="Dança", territorio="Nacional"), perfil)
    p = r["projetos"][0]
    assert p["nivel"] == P.NIVEL_NAO_IDENTIFICADA and p["dados_insuficientes"]
    assert "não há dados suficientes" in p["justificativa"].lower()


def test_edital_sem_texto_nao_gera_conclusao():
    r = P.analisar(_edital(titulo="", descricao=""), _perfil())
    assert all(p["nivel"] == P.NIVEL_NAO_IDENTIFICADA and p["dados_insuficientes"] for p in r["projetos"])


def test_incompatibilidade_de_territorio_reduz_o_nivel_e_e_explicada():
    base = dict(titulo="Edital de Dança", area_tematica="Dança", descricao="Oficinas de dança.")
    compat = _por_nome(P.analisar(_edital(**base, territorio="Guaíra (SP)"), _perfil()), "Usina da Dança")
    incompat = _por_nome(P.analisar(_edital(**base, territorio="Belo Horizonte (MG)"), _perfil()), "Usina da Dança")
    assert compat["nivel"] == P.NIVEL_ALTA and incompat["nivel"] == P.NIVEL_MEDIA
    assert any("Território incompatível" in e for e in incompat["evidencias"])
    assert "reduzido" in incompat["justificativa"]


def test_edital_nacional_e_compativel_com_o_territorio_do_iorm():
    assert P.avaliar_territorio("Nacional — “todo o Brasil”", _perfil())["estado"] == "NACIONAL"
    assert P.avaliar_territorio(None, _perfil())["estado"] == "DESCONHECIDO"


def test_elegibilidade_fica_separada_do_nivel_tematico_e_nunca_diz_que_pode_participar():
    base = dict(titulo="Edital de Dança", area_tematica="Dança", territorio="Guaíra (SP)")
    sem = P.analisar(_edital(**base), _perfil())
    com = P.analisar(_edital(**base, requisitos="Poderão participar somente Pessoas Físicas residentes no município."), _perfil())
    assert _por_nome(sem, "Usina da Dança")["nivel"] == _por_nome(com, "Usina da Dança")["nivel"]  # elegibilidade não mexe no tema
    eleg = com["elegibilidade"]
    assert eleg["status"] == P.ELEG_RESTRICAO and "pessoas físicas" in eleg["resumo"].lower()
    assert eleg["aviso"] == "Elegibilidade precisa ser conferida no edital."
    assert "pode participar" not in eleg["resumo"].lower()
    assert sem["elegibilidade"]["status"] == P.ELEG_NAO_IDENTIFICADA


def test_elegibilidade_com_pessoa_juridica_continua_exigindo_conferencia():
    eleg = P.avaliar_elegibilidade(_edital(requisitos="Poderão ser proponentes: Pessoas Jurídicas de direito privado, com ou sem fins "
                                                        "lucrativos, com CNAE ligado à cultura."))
    assert eleg["status"] == P.ELEG_MENCIONA_PJ and any("CNAE" in a for a in eleg["alertas"]) and eleg["aviso"]


def test_edital_multiarea_nao_da_nivel_alto_por_uma_unica_linguagem():
    areas = "Circo, Dança, Teatro, Música Popular, Audiovisual, Literatura, Artes Visuais"
    r = P.analisar(_edital(titulo="Edital de fomento à cultura", area_tematica=areas, territorio="Guaíra (SP)"), _perfil())
    assert _por_nome(r, "Usina da Dança")["nivel"] == P.NIVEL_MEDIA
    assert _por_nome(r, "Artes e Cultura")["nivel"] == P.NIVEL_ALTA  # dois temas em comum (teatro + literatura)


def test_citacao_isolada_no_corpo_do_texto_nao_conta_como_tema_do_edital():
    edital = _edital(titulo="Edital de fomento a oficinas", territorio="Guaíra (SP)",
                     descricao="Agente cultural é quem cria manifestações, como artistas, músicos e escritores.")
    r = P.analisar(edital, _perfil())
    assert _por_nome(r, "Música: A Linguagem Universal")["nivel"] in (P.NIVEL_BAIXA, P.NIVEL_NAO_IDENTIFICADA)


def test_resultado_e_deterministico():
    edital = _edital(titulo="Edital de Dança", area_tematica="Dança", territorio="Guaíra (SP)")
    assert P.analisar(edital, _perfil()) == P.analisar(edital, _perfil())


def test_modulo_nao_tem_nenhum_edital_fixo_no_codigo():
    codigo = (RAIZ / "processamento" / "projetos_editais.py").read_text(encoding="utf-8").lower()
    assert "miguel" not in codigo and "usina" not in codigo and "funarte" not in codigo


# ------------------------------------------------------------------ persistência
@pytest.fixture
def conexao(tmp_path):
    con = sqlite3.connect(tmp_path / "t.db")
    con.row_factory = sqlite3.Row
    editais.criar_tabelas(con)
    editais.migrar_colunas_novas(con)
    P.criar_tabelas(con)
    return con


def _novo_edital(con, **extra):
    eid = editais.criar_edital(con, {"titulo": "Edital de Dança", "url": "https://prosas.com.br/editais/1-x", "area_tematica": "Dança",
                                     "territorio": "Guaíra (SP)", "data_encerramento": (date.today() + timedelta(days=40)).isoformat(), **extra})
    return dict(con.execute("SELECT * FROM editais WHERE id = ?", (eid,)).fetchone())


def test_analise_e_salva_sem_duplicar_e_so_recalcula_quando_algo_mudou(conexao):
    edital, perfil = _novo_edital(conexao), _perfil()
    assert P.analisar_e_salvar(conexao, edital, perfil) is True
    assert P.analisar_e_salvar(conexao, edital, perfil) is False  # mesmo hash: nada a refazer
    assert P.analisar_e_salvar(conexao, edital, perfil, forcar=True) is True  # forçado: recalcula, não duplica
    linhas = conexao.execute("SELECT COUNT(*) FROM editais_projetos WHERE edital_id = ?", (edital["id"],)).fetchone()[0]
    assert linhas == len(perfil["programas"])
    assert conexao.execute("SELECT COUNT(*) FROM editais_analise").fetchone()[0] == 1


def test_mudanca_no_cerebro_da_osc_recalcula_e_projeto_removido_sai_da_analise(conexao):
    edital = _novo_edital(conexao)
    P.analisar_e_salvar(conexao, edital, _perfil())
    perfil2 = _perfil([_programa(2, "Usina da Dança", "Dança")])  # sobrou um projeto só
    assert P.analisar_e_salvar(conexao, edital, perfil2) is True
    nomes = [p["nome"] for p in P.carregar_analise(conexao, edital["id"])["projetos"]]
    assert nomes == ["Usina da Dança"]


def test_mudanca_no_edital_recalcula(conexao):
    edital, perfil = _novo_edital(conexao), _perfil()
    P.analisar_e_salvar(conexao, edital, perfil)
    conexao.execute("UPDATE editais SET territorio = 'Belo Horizonte (MG)' WHERE id = ?", (edital["id"],))
    atualizado = dict(conexao.execute("SELECT * FROM editais WHERE id = ?", (edital["id"],)).fetchone())
    assert P.analisar_e_salvar(conexao, atualizado, perfil) is True
    assert P.carregar_analise(conexao, edital["id"])["territorio_estado"] == "INCOMPATIVEL"


def test_carregar_analise_devolve_relacionados_primeiro_e_versao(conexao):
    edital = _novo_edital(conexao)
    P.analisar_e_salvar(conexao, edital, _perfil())
    analise = P.carregar_analise(conexao, edital["id"])
    assert [p["nivel"] for p in analise["projetos"]] == sorted((p["nivel"] for p in analise["projetos"]), key=lambda n: -P._ORDEM[n])
    assert analise["relacionados"] and all(p["nivel"] in ("ALTA", "MEDIA") for p in analise["relacionados"])
    assert analise["versao"] == P.VERSAO_ANALISE and analise["projetos"][0]["versao"] == P.VERSAO_ANALISE
    assert analise["projetos"][0]["criterios"], "o detalhamento ('Ver como foi calculado') precisa estar salvo"


def test_reanalisar_todos_cobre_todos_os_editais(conexao):
    _novo_edital(conexao)
    _novo_edital(conexao, titulo="Outro edital de teatro", url="https://prosas.com.br/editais/2-y", area_tematica="Teatro")
    assert P.reanalisar_todos(conexao, _perfil()) == 2
    assert P.reanalisar_todos(conexao, _perfil()) == 0


# ------------------------------------------------------------------ dados reais do Cérebro da OSC
@pytest.fixture(scope="module")
def banco_real(tmp_path_factory):
    if not BANCO.exists():
        pytest.skip("banco real não disponível")
    destino = tmp_path_factory.mktemp("pe") / "iorm_radar.db"
    shutil.copy(BANCO, destino)
    con = sqlite3.connect(destino)
    con.row_factory = sqlite3.Row
    return con


def test_miguelopolis_relaciona_usina_da_danca_e_artes_e_cultura_a_partir_do_cerebro_real(banco_real):
    edital = banco_real.execute("SELECT * FROM editais WHERE titulo LIKE '%MIGUEL%' AND origem_descoberta != 'TESTE' LIMIT 1").fetchone()
    if edital is None:
        pytest.skip("edital de Miguelópolis não está no banco")
    perfil = osc.carregar_perfil_completo(banco_real, osc.obter_osc_principal(banco_real)["id"])
    analise = P.analisar(dict(edital), perfil)
    relacionados = {p["nome"] for p in analise["projetos"] if p["nivel"] in P.NIVEIS_RELACIONADOS}
    assert {"Usina da Dança", "Artes e Cultura"} <= relacionados
    assert _por_nome(analise, "Profissionalizando Pessoas")["nivel"] == P.NIVEL_NAO_IDENTIFICADA
    assert analise["elegibilidade"]["status"] == P.ELEG_RESTRICAO  # a página exige Pessoas Físicas residentes
    assert analise["elegibilidade"]["aviso"] == "Elegibilidade precisa ser conferida no edital."


def test_todos_os_editais_existentes_continuam_sendo_analisados(banco_real):
    perfil = osc.carregar_perfil_completo(banco_real, osc.obter_osc_principal(banco_real)["id"])
    total = banco_real.execute("SELECT COUNT(*) FROM editais").fetchone()[0]
    assert P.reanalisar_todos(banco_real, perfil, forcar=True) == total
    assert banco_real.execute("SELECT COUNT(*) FROM editais_projetos").fetchone()[0] == total * len(perfil["programas"])


def test_ficha_do_edital_mostra_projetos_relacionados_e_elegibilidade_separada(banco_real, tmp_path):
    from streamlit.testing.v1 import AppTest

    alvo = banco_real.execute("SELECT id FROM editais WHERE titulo LIKE '%MIGUEL%' AND origem_descoberta != 'TESTE' LIMIT 1").fetchone()
    if alvo is None:
        pytest.skip("edital de Miguelópolis não está no banco")
    banco_real.commit()
    caminho = banco_real.execute("PRAGMA database_list").fetchone()[2]
    corpo = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, r"{RAIZ}")
        from pathlib import Path
        import streamlit as st
        from paginas import _shared
        _shared.CAMINHO_DB = Path(r"{caminho}")
        _shared.garantir_tabelas_novas()
        _shared.injetar_css()
        st.session_state["edital_em_foco"] = {alvo['id']}
        from paginas import radar_editais
        radar_editais.render()
    """)
    app = AppTest.from_string(corpo, default_timeout=120).run()
    assert not app.exception, [e.value for e in app.exception]
    texto = " ".join(m.value for m in app.markdown)
    assert "Projetos do IORM relacionados" in texto and "Usina da Dança" in texto and "Artes e Cultura" in texto
    assert "Elegibilidade da OSC" in texto and "Elegibilidade precisa ser conferida no edital." in texto
    assert any("Ver como foi calculado" in e.label for e in app.expander)
