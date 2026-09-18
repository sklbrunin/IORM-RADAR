"""IORM Radar — Inteligência de Captação.

Ponto de entrada da dashboard (Streamlit multipage nativo). Cada página
mora em paginas/*.py; a lógica de negócio mora em processamento/*.py.
Este arquivo só carrega configuração e monta a navegação — não tem
regra de negócio nenhuma.

Como rodar:
    streamlit run app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

RAIZ_PROJETO = Path(__file__).resolve().parent
if str(RAIZ_PROJETO) not in sys.path:
    sys.path.insert(0, str(RAIZ_PROJETO))

load_dotenv(RAIZ_PROJETO / ".env")  # carrega SERPAPI_API_KEY etc., se existir — nunca obrigatório

from paginas import _shared  # noqa: E402
from paginas import (  # noqa: E402
    cerebro_osc, configuracoes, contatos, crm, dashboard, oportunidades, radar_editais, radar_empresas, rotina_diaria,
)

st.set_page_config(page_title="IORM Radar", page_icon="🎯", layout="wide")
_shared.injetar_css()
_shared.marca_sidebar()

if not _shared.CAMINHO_DB.exists():
    st.error(
        f"Banco de dados não encontrado em `{_shared.CAMINHO_DB}`.\n\n"
        "Rode a coleta primeiro: `python coleta/coleta_salic.py --uf SP` (veja o README)."
    )
    st.stop()

_shared.garantir_tabelas_novas()

pagina = st.navigation(
    {
        "Visão Geral": [
            st.Page(dashboard.render, title="Dashboard", icon="🏠", default=True, url_path="dashboard"),
        ],
        "Inteligência": [
            st.Page(cerebro_osc.render, title="Cérebro da OSC", icon="🧠", url_path="cerebro-osc"),
            st.Page(radar_empresas.render, title="Radar de Empresas", icon="🎯", url_path="radar-empresas"),
            st.Page(radar_editais.render, title="Radar de Editais", icon="📋", url_path="radar-editais"),
            st.Page(contatos.render, title="Contatos", icon="📇", url_path="contatos"),
        ],
        "Captação": [
            st.Page(crm.render, title="Pipeline", icon="🤝", url_path="pipeline"),
            st.Page(oportunidades.render, title="Oportunidades", icon="⭐", url_path="oportunidades"),
        ],
        "Sistema": [
            st.Page(rotina_diaria.render, title="Rotina diária", icon="🔁", url_path="rotina-diaria"),
            st.Page(configuracoes.render, title="Configurações", icon="⚙️", url_path="configuracoes"),
        ],
    }
)
pagina.run()
