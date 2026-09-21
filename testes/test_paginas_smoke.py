"""Teste de fumaça das páginas: renderiza cada página do Streamlit de verdade
(streamlit.testing.AppTest) contra uma CÓPIA do banco e exige que nenhuma
levante exceção. Pega o tipo de erro que só aparece com dado real (NaN,
coluna vazia, etc.) — foi assim que o NaN em e-mail de Contatos apareceu.

Usa cópia do banco para não escrever no banco real. Pula se não houver banco.
"""
from __future__ import annotations

import shutil
import textwrap
from pathlib import Path

import pandas as pd
import pytest

RAIZ = Path(__file__).resolve().parent.parent
BANCO = RAIZ / "dados" / "iorm_radar.db"

pytestmark = pytest.mark.skipif(not BANCO.exists(), reason="banco de dados real não disponível")

PAGINAS = [
    "dashboard", "cerebro_osc", "radar_empresas", "radar_editais", "contatos", "crm", "oportunidades",
    "rotina_diaria", "configuracoes",
]


def _rodar_pagina(modulo: str, banco_copia: Path):
    from streamlit.testing.v1 import AppTest

    script = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, r"{RAIZ}")
        from pathlib import Path
        from paginas import _shared
        _shared.CAMINHO_DB = Path(r"{banco_copia}")
        _shared.garantir_tabelas_novas()
        from paginas import {modulo}
        {modulo}.render()
    """)
    return AppTest.from_string(script, default_timeout=120).run()


@pytest.fixture(scope="module")
def banco_copia(tmp_path_factory) -> Path:
    destino = tmp_path_factory.mktemp("banco") / "iorm_radar.db"
    shutil.copy(BANCO, destino)
    return destino


@pytest.mark.parametrize("modulo", PAGINAS)
def test_pagina_renderiza_sem_excecao(modulo, banco_copia):
    app = _rodar_pagina(modulo, banco_copia)
    assert not app.exception, [e.value for e in app.exception]


def test_canais_da_empresa_aceita_email_ausente():
    """Regressão: e-mail vazio vem como NaN do pandas (truthy) e derrubava a página."""
    from paginas import contatos

    df = pd.DataFrame([
        {"empresa_id": 1, "empresa": "A", "cidade": "Guaíra", "estado": "SP", "site": None, "linkedin": None,
         "instagram": None, "email": float("nan"), "telefone": None, "nivel_confianca": "MEDIO", "fonte": "x"},
        {"empresa_id": 2, "empresa": "B", "cidade": "Guaíra", "estado": "SP", "site": None, "linkedin": None,
         "instagram": None, "email": "financeiro@b.com.br", "telefone": None, "nivel_confianca": "MEDIO", "fonte": "x"},
    ])
    tabela = contatos._tabela_canais_empresa(df).set_index("Empresa")
    assert tabela.loc["A", "Área do e-mail"] == "—"
    assert tabela.loc["A", "E-mail institucional"] == "Não disponível"
    assert tabela.loc["B", "Área do e-mail"] != "—"

# ------------------------------------------------------------------ v7: edital aberto no Dashboard → ficha no Radar de Editais
@pytest.fixture
def banco_com_edital_aberto(tmp_path):
    """Cópia do banco real + um edital ABERTO (prazo futuro relativo a hoje). Nunca toca o banco real."""
    import sqlite3
    from datetime import date, timedelta

    destino = tmp_path / "iorm_radar.db"
    shutil.copy(BANCO, destino)
    conn = sqlite3.connect(destino)
    conn.row_factory = sqlite3.Row
    from processamento import editais

    editais.criar_tabelas(conn)
    eid = editais.criar_edital(conn, {
        "titulo": "Chamada de Fomento à Cultura e Dança em Guaíra", "organizacao_promotora": "Secretaria X (teste)",
        "url": "https://prefeitura.exemplo/chamada", "fonte": "teste automatizado", "territorio": "Guaíra, Ipuã (SP)",
        "data_encerramento": (date.today() + timedelta(days=45)).isoformat(), "area_tematica": "Cultura e dança",
        "valor_numerico": 1573345.5, "publico": "crianças e adolescentes", "requisitos": "Aberto a OSC sem fins lucrativos",
        "descricao": "Apoio a projetos de cultura, música e dança.",
    })
    conn.commit()
    conn.close()
    return destino, eid


def _rodar_pagina_com_estado(modulo: str, banco: Path, estado: dict | None = None):
    from streamlit.testing.v1 import AppTest

    script = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, r"{RAIZ}")
        from pathlib import Path
        from paginas import _shared
        _shared.CAMINHO_DB = Path(r"{banco}")
        _shared.garantir_tabelas_novas()
        from paginas import {modulo}
        {modulo}.render()
    """)
    at = AppTest.from_string(script, default_timeout=120)
    for chave, valor in (estado or {}).items():
        at.session_state[chave] = valor
    return at.run()


def test_dashboard_mostra_cartao_de_edital_aberto_com_valor_em_real(banco_com_edital_aberto):
    banco, eid = banco_com_edital_aberto
    app = _rodar_pagina_com_estado("dashboard", banco)
    assert not app.exception, [e.value for e in app.exception]
    rotulos = [b.label for b in app.button]
    assert "Chamada de Fomento à Cultura e Dança em Guaíra" in rotulos  # título completo, clicável
    assert "Abrir ficha completa →" in rotulos
    texto = " ".join(m.value for m in app.markdown)
    assert "R$ 1.573.345,50" in texto and "Secretaria X (teste)" in texto


def test_dashboard_contadores_da_base_batem_com_o_banco(banco_com_edital_aberto):
    banco, _ = banco_com_edital_aberto
    app = _rodar_pagina_com_estado("dashboard", banco)
    metricas_tela = {m.label: m.value for m in app.metric}
    import sqlite3

    total = sqlite3.connect(banco).execute("SELECT COUNT(*) FROM empresas").fetchone()[0]
    assert metricas_tela["Empresas na base"] == f"{total:,}".replace(",", ".")
    prospects = int(metricas_tela["Prospects"].replace(".", ""))
    cruzada = int(metricas_tela["Linha Cruzada"].replace(".", ""))
    assert prospects + cruzada >= total and prospects <= total  # só passa de `total` com prospecção reaberta


def test_editais_com_foco_abre_a_ficha_do_edital_pedido(banco_com_edital_aberto):
    banco, eid = banco_com_edital_aberto
    app = _rodar_pagina_com_estado("radar_editais", banco, {"edital_em_foco": eid})
    assert not app.exception, [e.value for e in app.exception]
    abertos = [e for e in app.expander if e.label.startswith("Chamada de Fomento à Cultura e Dança em Guaíra")]
    assert abertos, [e.label for e in app.expander]
    assert "Aderência" in abertos[0].label and "até" in abertos[0].label  # título + nota + prazo, sem cortes
    corpo = " ".join(m.value for m in app.markdown)
    assert "Link direto de inscrição não localizado" in corpo  # sem link falso de inscrição


def test_editais_padrao_lista_so_abertos_e_registro_de_teste_fica_no_historico(banco_com_edital_aberto):
    banco, _ = banco_com_edital_aberto
    app = _rodar_pagina_com_estado("radar_editais", banco)
    assert not app.exception, [e.value for e in app.exception]
    metricas_tela = {m.label: m.value for m in app.metric}
    assert int(metricas_tela["Abertos"]) >= 1
    assert app.expander[0].label.startswith("Chamada de Fomento à Cultura e Dança em Guaíra")  # a aba padrão mostra o aberto primeiro
    import sqlite3

    tem_teste = sqlite3.connect(banco).execute(
        "SELECT COUNT(*) FROM editais WHERE origem_descoberta = 'TESTE_NAO_REAL'").fetchone()[0]
    rotulos = " | ".join(e.label for e in app.expander)
    if tem_teste:  # registro de teste continua guardado, mas só na aba de histórico — nunca entre os abertos
        assert "Edital Municipal de Cultura e Dança 2026" in rotulos
        assert int(metricas_tela["Encerrados e histórico"]) >= tem_teste
