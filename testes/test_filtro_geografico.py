"""Filtros de Estado e Cidade acima da tabela do Radar de Prospecção: só recortam a exibição."""
from __future__ import annotations

import re
import shutil
import sqlite3
import textwrap
from pathlib import Path

import pandas as pd
import pytest

from paginas import radar_empresas

RAIZ = Path(__file__).resolve().parent.parent
BANCO = RAIZ / "dados" / "iorm_radar.db"

DF = pd.DataFrame({
    "estado": ["SP", "SP", "MG", "MG", "BA", None],
    "cidade": ["Guaíra", "Ipuã", "Uberaba", "Belo Horizonte", "Salvador", "Sem UF"],
    "razao_social": list("ABCDEF"),
})


def test_padrao_brasil_todo_e_todas_as_cidades_nao_filtra_nada():
    saida = radar_empresas.aplicar_filtro_geografico(DF, radar_empresas.OPCAO_BRASIL_TODO, radar_empresas.OPCAO_TODAS_CIDADES)
    assert len(saida) == len(DF)


def test_filtra_por_estado_e_por_cidade_sem_alterar_o_original():
    copia = DF.copy()
    mg = radar_empresas.aplicar_filtro_geografico(DF, "MG", radar_empresas.OPCAO_TODAS_CIDADES)
    assert list(mg["razao_social"]) == ["C", "D"]
    uberaba = radar_empresas.aplicar_filtro_geografico(DF, "MG", "Uberaba")
    assert list(uberaba["razao_social"]) == ["C"]
    assert radar_empresas.aplicar_filtro_geografico(DF, "SP", "Uberaba").empty  # cidade de outro estado não aparece
    pd.testing.assert_frame_equal(DF, copia)  # o DataFrame de origem não é tocado


# ------------------------------------------------------------------ página real
@pytest.fixture(scope="module")
def banco_copia(tmp_path_factory):
    if not BANCO.exists():
        pytest.skip("banco real não disponível")
    destino = tmp_path_factory.mktemp("geo") / "iorm_radar.db"
    shutil.copy(BANCO, destino)
    return destino


def _app(banco_copia: Path):
    from streamlit.testing.v1 import AppTest

    corpo = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, r"{RAIZ}")
        from pathlib import Path
        from paginas import _shared
        _shared.CAMINHO_DB = Path(r"{banco_copia}")
        _shared.garantir_tabelas_novas()
        _shared.injetar_css()
        from paginas import radar_empresas
        radar_empresas.render()
    """)
    app = AppTest.from_string(corpo, default_timeout=180).run()
    assert not app.exception, [e.value for e in app.exception]
    return app


def _contagem(app) -> int:
    texto = next(c.value for c in app.caption if "após os filtros (barra lateral e Estado/Cidade)" in c.value)
    return int(re.match(r"([\d.]+)", texto).group(1).replace(".", ""))


def _metricas(app) -> dict:
    return {m.label: m.value for m in app.metric}


def test_filtros_aparecem_com_os_padroes_e_listas_dinamicas(banco_copia):
    app = _app(banco_copia)
    estado, cidade = app.selectbox(key="geo_estado"), app.selectbox(key="geo_cidade")
    assert estado.value == "Brasil todo" and cidade.value == "Todas as cidades"
    assert estado.options[0] == "Brasil todo" and "SP" in estado.options and "MG" in estado.options
    assert cidade.options[0] == "Todas as cidades" and "Guaíra" in cidade.options


def test_escolher_estado_limita_as_cidades_e_a_tabela_sem_mexer_nas_metricas(banco_copia):
    conexao = sqlite3.connect(banco_copia)
    esperado_mg = conexao.execute("SELECT COUNT(*) FROM empresas WHERE estado = 'MG'").fetchone()[0]
    cidades_mg = {l[0] for l in conexao.execute("SELECT DISTINCT cidade FROM empresas WHERE estado = 'MG' AND cidade IS NOT NULL")}
    conexao.close()
    app = _app(banco_copia)
    total_antes, metricas_antes = _contagem(app), _metricas(app)
    app.selectbox(key="geo_estado").select("MG").run()
    assert not app.exception, [e.value for e in app.exception]
    assert set(app.selectbox(key="geo_cidade").options) == {"Todas as cidades"} | cidades_mg
    assert 0 < _contagem(app) <= esperado_mg and _contagem(app) < total_antes
    assert _metricas(app) == metricas_antes  # os contadores da base não mudam com o filtro de exibição


def test_escolher_cidade_filtra_e_trocar_de_estado_volta_a_cidade_para_todas(banco_copia):
    app = _app(banco_copia)
    app.selectbox(key="geo_estado").select("SP").run()
    app.selectbox(key="geo_cidade").select("Guaíra").run()
    guaira = _contagem(app)
    app.selectbox(key="geo_estado").select("MG").run()
    assert not app.exception, [e.value for e in app.exception]
    assert app.selectbox(key="geo_cidade").value == "Todas as cidades"
    app.selectbox(key="geo_estado").select("Brasil todo").run()
    assert _contagem(app) > guaira


def test_o_banco_nao_e_alterado_pela_pagina(banco_copia):
    antes = banco_copia.read_bytes()
    conexao = sqlite3.connect(banco_copia)
    linhas_antes = {t: conexao.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("empresas", "incentivos", "contatos")}
    conexao.close()
    app = _app(banco_copia)
    app.selectbox(key="geo_estado").select("MG").run()
    conexao = sqlite3.connect(banco_copia)
    linhas_depois = {t: conexao.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("empresas", "incentivos", "contatos")}
    conexao.close()
    assert linhas_antes == linhas_depois and len(antes) > 0
