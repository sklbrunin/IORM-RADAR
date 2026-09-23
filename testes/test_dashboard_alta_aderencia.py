"""Dashboard v9: "Editais com alta aderência" mostra TODOS os editais que cumprem a regra (ABERTO + nota >= 7,0 + >= 3
critérios), com botões de chave única e estável. Também cobre a causa real do "só 1 aparece": o edital Funarte tinha
território e elegibilidade escritos no texto da página, mas o extrator não os lia — ficava com 2 critérios e caía fora."""
from __future__ import annotations

import shutil
import sqlite3
import textwrap
from datetime import date, timedelta
from pathlib import Path

import pytest

from processamento import editais, links_editais

RAIZ = Path(__file__).resolve().parent.parent
BANCO = RAIZ / "dados" / "iorm_radar.db"


# ------------------------------------------------------------------ extração literal (causa raiz)
def _pagina_prosas(descricao_html: str) -> str:
    import json

    obj = {"id": 17663, "nome": "Programa X", "descricao": descricao_html, "inicio_inscricoes": "2026-03-30T00:00:00",
           "encerramento_das_inscricoes": "2027-04-30T23:59:00", "subscription_in_progress": True,
           "culturas": [], "publico_alvos": []}
    import html as _html

    escapado = _html.escape(json.dumps(obj, ensure_ascii=False), quote=True)
    return f'<html><body><div ng-init="x={escapado}"></div></body></html>'


def test_extrator_le_territorio_nacional_e_proponentes_do_texto_da_pagina():
    html_ = _pagina_prosas("<p>As propostas poderão contemplar ações provenientes de todo o território nacional, em vários formatos.</p>"
                           "<p><b>Poderão ser proponentes:</b> Pessoas Jurídicas de direito privado, com ou sem fins lucrativos, e MEIs.</p>")
    dados = links_editais.extrair_dados_estruturados(html_)
    assert dados is not None
    assert "todo o território nacional" in dados["territorio_trecho"]
    assert dados["elegibilidade"].startswith("Poderão ser proponentes") and "sem fins lucrativos" in dados["elegibilidade"]


def test_extrator_nao_inventa_territorio_quando_a_pagina_nao_diz():
    html_ = _pagina_prosas("<p>Seleção de projetos culturais no município de Miguelópolis.</p>")
    dados = links_editais.extrair_dados_estruturados(html_)
    assert dados["territorio_trecho"] is None and dados["elegibilidade"] is None


def test_trecho_de_territorio_nao_comeca_nem_termina_no_meio_de_palavra():
    texto = "Início " + "palavra " * 30 + "propostas de todo o Brasil " + "final " * 30
    dados = links_editais.extrair_dados_estruturados(_pagina_prosas(texto))
    trecho = dados["territorio_trecho"].strip("…")
    assert "todo o Brasil" in trecho and trecho.split()[0] in {"palavra", "propostas"} and trecho.split()[-1] in {"final", "palavra"}


def test_registrar_verificacao_preenche_territorio_e_requisitos_sem_sobrescrever(tmp_path):
    conexao = sqlite3.connect(tmp_path / "t.db")
    conexao.row_factory = sqlite3.Row
    editais.criar_tabelas(conexao)
    editais.migrar_colunas_novas(conexao)
    eid = editais.criar_edital(conexao, {"titulo": "Edital X", "url": "https://prosas.com.br/editais/1-x",
                                         "data_encerramento": (date.today() + timedelta(days=60)).isoformat()})
    dados = {"encerramento": None, "territorio_trecho": "…de todo o Brasil…", "elegibilidade": "Poderão ser proponentes: OSC."}
    verificacao = {"status": "PAGINA_ESPECIFICA_CONFIRMADA", "dados_estruturados": dados}
    editais.registrar_verificacao(conexao, eid, verificacao)
    linha = conexao.execute("SELECT territorio, requisitos FROM editais WHERE id = ?", (eid,)).fetchone()
    assert "Nacional" in linha["territorio"] and linha["requisitos"].startswith("Poderão")
    conexao.execute("UPDATE editais SET territorio = 'Guaíra (SP)' WHERE id = ?", (eid,))
    editais.registrar_verificacao(conexao, eid, verificacao)
    assert conexao.execute("SELECT territorio FROM editais WHERE id = ?", (eid,)).fetchone()[0] == "Guaíra (SP)"


def test_edital_com_texto_nacional_passa_a_ter_4_criterios_e_qualifica():
    perfil = {"temas": ["teatro", "dança"], "palavras_chave": ["cultura"], "cidades": ["Guaíra"], "estados": ["SP"], "programas": []}
    base = {"titulo": "Programa Funarte Aberta - Teatro", "descricao": "Ocupação cultural de teatro e dança",
            "data_encerramento": (date.today() + timedelta(days=90)).isoformat()}
    antes = editais.calcular_aderencia(dict(base), perfil)
    depois = editais.calcular_aderencia({**base, "territorio": "Nacional — …de todo o Brasil…",
                                         "requisitos": "Poderão ser proponentes: Pessoas Jurídicas de direito privado, com ou sem fins lucrativos."}, perfil)
    assert antes["criterios_avaliados"] == 2 and depois["criterios_avaliados"] == 4
    assert depois["nota_final"] >= 7.0


# ------------------------------------------------------------------ Dashboard com N editais
def _copia(tmp_path_factory) -> Path:
    if not BANCO.exists():
        pytest.skip("banco real não disponível")
    destino = tmp_path_factory.mktemp("dash") / "iorm_radar.db"
    shutil.copy(BANCO, destino)
    return destino


def _preparar(destino: Path, quantidade: int) -> list[int]:
    """Cópia do banco com SOMENTE `quantidade` editais abertos e de alta aderência (sintéticos, datas relativas)."""
    conexao = sqlite3.connect(destino)
    conexao.row_factory = sqlite3.Row
    conexao.execute("DELETE FROM editais")
    conexao.commit()
    ids = []
    for i in range(quantidade):
        ids.append(editais.criar_edital(conexao, {
            "titulo": f"Edital sintético {i + 1} de teatro e dança", "url": f"https://prosas.com.br/editais/{9000 + i}-teste",
            "descricao": "Seleção de propostas de teatro, dança e cultura", "territorio": "Nacional", "publico": "Jovens",
            "requisitos": "Poderão participar associações sem fins lucrativos (OSC).", "valor_numerico": 50000.0,
            "valor_texto": "R$ 50.000,00", "data_encerramento": (date.today() + timedelta(days=60)).isoformat(),
            "situacao_inscricao": "ABERTO", "tipo": "EDITAL", "prazo_origem": "FONTE_ESTRUTURADA",
        }))
    conexao.close()
    return ids


def _dashboard(banco: Path):
    from streamlit.testing.v1 import AppTest

    corpo = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, r"{RAIZ}")
        from pathlib import Path
        from paginas import _shared
        _shared.CAMINHO_DB = Path(r"{banco}")
        _shared.garantir_tabelas_novas()
        _shared.injetar_css()
        from paginas import dashboard
        dashboard.render()
    """)
    app = AppTest.from_string(corpo, default_timeout=120).run()
    assert not app.exception, [e.value for e in app.exception]
    return app


def _titulos(app) -> list[str]:
    return sorted(b.key for b in app.button if b.key and b.key.startswith("dash_edital_titulo_"))


@pytest.mark.parametrize("quantidade", [1, 2, 3])
def test_dashboard_mostra_todos_os_editais_de_alta_aderencia(quantidade, tmp_path_factory):
    destino = _copia(tmp_path_factory)
    ids = _preparar(destino, quantidade)
    app = _dashboard(destino)
    assert _titulos(app) == sorted(f"dash_edital_titulo_{i}" for i in ids)
    aberturas = sorted(b.key for b in app.button if b.key and b.key.startswith("dash_edital_abrir_"))
    assert aberturas == sorted(f"dash_edital_abrir_{i}" for i in ids)


def test_dashboard_com_mais_de_seis_pagina_explicitamente_e_ver_todos_mostra_tudo(tmp_path_factory):
    destino = _copia(tmp_path_factory)
    ids = _preparar(destino, 8)
    app = _dashboard(destino)
    assert len(_titulos(app)) == 6
    assert any("mostrando 6 de 8" in c.value for c in app.caption)
    app.button(key="dash_editais_alternar_lista").click().run()
    assert sorted(_titulos(app)) == sorted(f"dash_edital_titulo_{i}" for i in ids)


def test_clicar_no_titulo_abre_a_ficha_do_edital_correto(tmp_path_factory):
    destino = _copia(tmp_path_factory)
    ids = _preparar(destino, 2)
    app = _dashboard(destino)
    alvo = ids[1]
    app.button(key=f"dash_edital_titulo_{alvo}").click().run()
    assert app.session_state["edital_em_foco"] == alvo


def test_regra_de_alta_aderencia_nao_foi_afrouxada():
    from paginas import dashboard

    assert dashboard.LIMIAR_ADERENCIA_ALTA == 7.0 and dashboard.CRITERIOS_MINIMOS == 3


def test_edital_com_poucos_criterios_continua_fora_da_alta_aderencia(tmp_path_factory):
    destino = _copia(tmp_path_factory)
    conexao = sqlite3.connect(destino)
    conexao.execute("DELETE FROM editais")
    conexao.commit()
    editais.criar_edital(conexao, {"titulo": "Edital de teatro sem dados", "url": "https://prosas.com.br/editais/9999-x",
                                   "descricao": "Teatro", "data_encerramento": (date.today() + timedelta(days=60)).isoformat(),
                                   "situacao_inscricao": "ABERTO", "prazo_origem": "FONTE_ESTRUTURADA"})
    conexao.close()
    assert _titulos(_dashboard(destino)) == []


# ------------------------------------------------------------------ dados reais
def test_os_dois_editais_abertos_reais_aparecem_no_dashboard(tmp_path_factory):
    destino = _copia(tmp_path_factory)
    conexao = sqlite3.connect(destino)
    conexao.row_factory = sqlite3.Row
    reais = {e["id"]: e["titulo"] for e in editais.agrupar_por_situacao(editais.listar_editais(conexao))["abertos"]}
    conexao.close()
    if not {116, 124} <= set(reais):
        pytest.skip("os dois editais reais (Funarte 116 e Miguelópolis 124) não estão mais abertos")
    app = _dashboard(destino)
    assert {"dash_edital_titulo_116", "dash_edital_titulo_124"} <= set(_titulos(app))
