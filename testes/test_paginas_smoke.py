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
