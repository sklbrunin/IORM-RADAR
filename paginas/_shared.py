"""Recursos compartilhados entre as páginas: design system (CSS),
caminhos, carregamento de dados (cacheado) e helpers de exibição.

Mantém a mesma regra de sempre: só LEITURA do banco aqui (escrita só
acontece em ações explícitas dentro de cada página, nunca no carregamento)."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

RAIZ_PROJETO = Path(__file__).resolve().parent.parent
if str(RAIZ_PROJETO) not in sys.path:
    sys.path.insert(0, str(RAIZ_PROJETO))

from processamento import (  # noqa: E402
    banco, crm, descoberta_empresas, documentos, editais, enriquecimento, filtros, fontes_dados, formatacao, geografia, incentivos_providers,
    metricas, osc, projetos_editais, relacionamento,
)

# IORM_RADAR_DB permite apontar para OUTRO banco (cópia para testes/validação); sem ela, usa o banco do projeto.
CAMINHO_DB = Path(os.environ.get("IORM_RADAR_DB") or RAIZ_PROJETO / "dados" / "iorm_radar.db")
CAMINHO_FILA_PESQUISA = RAIZ_PROJETO / "dados" / "fila_pesquisa.json"
PASTA_DOCUMENTOS_OSC = RAIZ_PROJETO / "dados" / "documentos_osc"
CAMINHO_LOGO = RAIZ_PROJETO / "assets" / "logo-iorm.png.jpeg"
# Versão com fundo transparente e recorte justo (gerada a partir da logo
# original, sem redesenhar/distorcer a marca) — usada onde a logo aparece
# sobre um fundo escuro/colorido (banner de cabeçalho), onde a versão
# JPEG com fundo branco apareceria como uma caixa branca feia.
CAMINHO_LOGO_TRANSPARENTE = RAIZ_PROJETO / "assets" / "logo-iorm-transparente.png"

def ir_para_pagina(nome: str) -> None:
    """Leva o usuário a outra página do app (nome curto, ex.: "radar_editais"). O app.py guarda as
    páginas em session_state a cada execução; se não estiverem lá (ex.: teste isolado), não faz nada."""
    pagina = (st.session_state.get("_paginas") or {}).get(nome)
    if pagina is not None:
        st.switch_page(pagina)


formatar_moeda = formatacao.formatar_moeda_br
formatar_numero = formatacao.formatar_numero_br
formatar_cnpj = formatacao.formatar_cnpj
formatar_percentual = formatacao.formatar_percentual
formatar_data = formatacao.formatar_data_br
formatar_nota = formatacao.formatar_nota
resumir_texto = formatacao.resumir_texto

CONFIG_COLUNA_EMPRESA = {"Empresa": st.column_config.TextColumn("Empresa", width="large")}

# Paleta extraída da logo real do IORM (assets/logo-iorm.png.jpeg): azul
# (primária), laranja/âmbar (destaque/ação) e verde-limão (secundária),
# sobre uma escala neutra própria — não "tudo saturado", um sistema com
# papel definido para cada cor (ver injetar_css para os tokens completos).
# Um único lugar para mudar a identidade visual do produto inteiro.
CORES = {
    "azul": "#136A9A",
    "azul_claro": "#29ABE2",
    "azul_bg": "#EAF5FB",
    "laranja": "#F0900F",
    "laranja_bg": "#FEF2DF",
    "verde": "#6FA82E",
    "verde_bg": "#EEF8E1",
    "cinza_texto": "#5A6B72",
    "cinza_bg": "#EEF1F4",
    "vermelho": "#C0392B",
    "vermelho_bg": "#FDECEC",
    "navy": "#132A3A",
    "fundo": "#F5F7F9",
    "borda": "#E2E8EE",
}


# --------------------------------------------------------------------------- tema (claro/escuro)
# Tokens SEMÂNTICOS: as páginas só usam var(--iorm-*) — nunca uma cor fixa. Cada tema define o mesmo conjunto de
# nomes; o tema ativo (st.context.theme.type) decide quais valores são injetados. Marca: azul (primária), laranja
# (ação/destaque) e verde (positivo), extraídos da logo do IORM; neutros próprios, sóbrios.
TOKENS_TEMA: dict[str, dict[str, str]] = {
    "light": {
        "azul": "#136A9A", "azul-claro": "#29ABE2", "azul-escuro": "#0D4E73", "azul-bg": "#E8F3FA",
        "laranja": "#E58A0C", "laranja-escuro": "#B8690A", "laranja-bg": "#FDF1DC",
        "verde": "#5E9B22", "verde-escuro": "#3F7212", "verde-bg": "#ECF6DF",
        "vermelho": "#C0392B", "vermelho-bg": "#FBEAE8",
        "navy": "#12263A", "fundo": "#F3F5F8", "superficie": "#FFFFFF", "superficie-alt": "#F8FAFC",
        "borda": "#E1E7ED", "borda-forte": "#C9D3DC", "cinza": "#55666F", "cinza-claro": "#7C8B95", "cinza-bg": "#EDF0F3",
        "badge-laranja-texto": "#8F5208", "badge-vermelho-texto": "#9B2F22", "aviso-texto": "#5C3F08",
        "limitacao-texto": "#7A2E2E", "info-texto": "#0E4666", "destaque-fim": "#FFF8EC", "destaque-borda": "#F1D6A2",
        "on-azul": "#FFFFFF", "sidebar-marca": "#FFFFFF",
        "sombra-sm": "0 1px 2px rgba(18,38,58,0.05)", "sombra-md": "0 2px 8px rgba(18,38,58,0.08)",
        "sombra-lg": "0 6px 20px rgba(18,38,58,0.10)", "grafico": "#1F5F8B",
    },
    "dark": {
        "azul": "#5DB7E8", "azul-claro": "#7CC6F0", "azul-escuro": "#9CD3F2", "azul-bg": "#12314A",
        "laranja": "#F0A030", "laranja-escuro": "#FFB95C", "laranja-bg": "#3B2A0E",
        "verde": "#8CC94B", "verde-escuro": "#A9DC70", "verde-bg": "#1E3316",
        "vermelho": "#F0776A", "vermelho-bg": "#3D1C1C",
        "navy": "#E9EFF6", "fundo": "#0D1520", "superficie": "#16212F", "superficie-alt": "#1A2839",
        "borda": "#2A3A4D", "borda-forte": "#3B5068", "cinza": "#AAB8C6", "cinza-claro": "#8B9BAC", "cinza-bg": "#223245",
        "badge-laranja-texto": "#FFC670", "badge-vermelho-texto": "#FF9F94", "aviso-texto": "#F3D9A6",
        "limitacao-texto": "#F5BDBD", "info-texto": "#BFE4F8", "destaque-fim": "#2F2410", "destaque-borda": "#5B4519",
        "on-azul": "#08131C", "sidebar-marca": "#16212F",
        "sombra-sm": "0 1px 2px rgba(0,0,0,0.35)", "sombra-md": "0 2px 10px rgba(0,0,0,0.40)",
        "sombra-lg": "0 8px 24px rgba(0,0,0,0.45)", "grafico": "#5DB7E8",
    },
}


def tema_atual() -> str:
    """"light" ou "dark", conforme o tema ativo do Streamlit (escolha do usuário no menu ou do sistema)."""
    try:
        return "dark" if st.context.theme.type == "dark" else "light"
    except Exception:  # versões sem st.context.theme, ou fora de execução (testes)
        return "light"


def tokens_do_tema(tema: str | None = None) -> dict[str, str]:
    return TOKENS_TEMA.get(tema or tema_atual(), TOKENS_TEMA["light"])


def injetar_css() -> None:
    tema = tema_atual()
    variaveis = "\n".join(f"            --iorm-{nome}: {valor};" for nome, valor in TOKENS_TEMA[tema].items())
    st.markdown(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&display=swap');

        :root {{
{variaveis}
            --iorm-raio: 10px;
            --iorm-raio-sm: 8px;
            color-scheme: {tema};
        }}

        html, body, [class*="css"] {{ font-family: 'Manrope', -apple-system, sans-serif; }}
        .stApp {{ background-color: var(--iorm-fundo); color: var(--iorm-navy); }}
        h1, h2, h3, h4, h5 {{ color: var(--iorm-navy); font-weight: 700; letter-spacing: -0.012em; }}
        h1 {{ font-weight: 800; }}
        p, span, label, div {{ letter-spacing: 0; }}
        [data-testid="stAppViewContainer"] .block-container {{ padding-top: 1.6rem; max-width: 1500px; }}
        [data-testid="stCaptionContainer"] {{ color: var(--iorm-cinza); }}
        a {{ color: var(--iorm-azul); }}

        /* ---------- sidebar ---------- */
        [data-testid="stSidebar"] {{
            background-color: var(--iorm-superficie); border-right: 1px solid var(--iorm-borda);
        }}
        [data-testid="stSidebar"] .stMarkdown p {{ color: var(--iorm-cinza); }}
        [data-testid="stSidebarNav"] {{ padding-top: 0.25rem; }}
        .iorm-marca-sidebar {{
            display: flex; align-items: center; gap: 0.65rem; padding: 1rem 0.9rem 1rem 0.9rem;
            border-bottom: 1px solid var(--iorm-borda); margin: -1rem -1rem 0.8rem -1rem; width: calc(100% + 2rem);
            background: var(--iorm-sidebar-marca);
        }}
        .iorm-marca-sidebar img {{ display: block; background: #FFFFFF; border-radius: 8px; padding: 3px; }}
        .iorm-marca-nome {{ font-weight: 800; color: var(--iorm-navy); font-size: 1.02rem; line-height: 1.15; letter-spacing: -0.01em; }}
        .iorm-marca-sub {{ color: var(--iorm-azul); font-size: 0.68rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; }}
        [data-testid="stSidebarNav"] > ul, [data-testid="stSidebarNavItems"] {{ gap: 0.05rem; }}

        /* ---------- cabeçalho de página (mesmo visual nos dois temas: faixa escura com a marca) ---------- */
        .iorm-header {{
            background: linear-gradient(120deg, #10283C 0%, #0D4E73 60%, #136A9A 100%);
            border-radius: 12px; padding: 1.25rem 1.6rem; margin-bottom: 1.5rem;
            display: flex; align-items: center; gap: 1.1rem; position: relative; overflow: hidden;
            box-shadow: var(--iorm-sombra-md); border: 1px solid rgba(255,255,255,0.06);
        }}
        .iorm-header-logo {{
            background: #FFFFFF; border-radius: 10px; padding: 7px 9px;
            display: flex; align-items: center; justify-content: center; position: relative; z-index: 1;
        }}
        .iorm-header-texto {{ position: relative; z-index: 1; }}
        .iorm-header h1 {{ color: #FFFFFF; margin: 0; font-size: 1.5rem; }}
        .iorm-header p {{ color: #CFE4F2; margin: 0.2rem 0 0 0; font-size: 0.92rem; }}
        .iorm-header-eyebrow {{
            color: #FFB95C; font-size: 0.68rem; font-weight: 800; text-transform: uppercase;
            letter-spacing: 0.08em; margin-bottom: 0.15rem; display: block;
        }}

        /* ---------- cards / métricas ---------- */
        div[data-testid="stMetric"] {{
            background-color: var(--iorm-superficie); border: 1px solid var(--iorm-borda); border-radius: var(--iorm-raio);
            padding: 0.95rem 1.1rem 0.8rem 1.1rem; box-shadow: var(--iorm-sombra-sm);
        }}
        div[data-testid="stMetricLabel"] {{ color: var(--iorm-cinza); font-weight: 600; font-size: 0.8rem; }}
        div[data-testid="stMetricValue"] {{ color: var(--iorm-navy); font-weight: 800; }}

        /* ---------- seções ---------- */
        .iorm-secao {{
            display: flex; align-items: center; gap: 0.6rem; margin: 1.7rem 0 0.7rem 0;
            padding-bottom: 0.5rem; border-bottom: 1px solid var(--iorm-borda);
        }}
        .iorm-secao-icone {{
            display: inline-flex; align-items: center; justify-content: center; width: 1.8rem; height: 1.8rem;
            border-radius: 8px; background: var(--iorm-azul-bg); font-size: 0.95rem; flex: 0 0 auto;
        }}
        .iorm-secao h3 {{ margin: 0; font-size: 1.05rem; color: var(--iorm-navy); }}
        .iorm-secao-desc {{ color: var(--iorm-cinza); font-size: 0.84rem; margin: -0.3rem 0 0.8rem 0; }}

        /* ---------- cartão genérico reutilizável ---------- */
        .iorm-cartao {{
            background: var(--iorm-superficie); border: 1px solid var(--iorm-borda); border-radius: var(--iorm-raio);
            padding: 1.1rem 1.25rem; box-shadow: var(--iorm-sombra-sm); margin-bottom: 0.9rem; color: var(--iorm-navy);
        }}
        .iorm-cartao-titulo {{
            font-weight: 800; color: var(--iorm-navy); font-size: 0.95rem; margin-bottom: 0.6rem;
            display: flex; align-items: center; gap: 0.4rem;
        }}

        /* ---------- badges / pills ---------- */
        .iorm-badge {{
            display: inline-block; padding: 0.2rem 0.65rem; border-radius: 999px;
            font-size: 0.73rem; font-weight: 700; margin-right: 0.3rem; margin-bottom: 0.25rem; white-space: nowrap;
        }}
        .iorm-badge-azul {{ background: var(--iorm-azul-bg); color: var(--iorm-azul); }}
        .iorm-badge-laranja {{ background: var(--iorm-laranja-bg); color: var(--iorm-badge-laranja-texto); }}
        .iorm-badge-verde {{ background: var(--iorm-verde-bg); color: var(--iorm-verde-escuro); }}
        .iorm-badge-cinza {{ background: var(--iorm-cinza-bg); color: var(--iorm-cinza); }}
        .iorm-badge-vermelho {{ background: var(--iorm-vermelho-bg); color: var(--iorm-badge-vermelho-texto); }}
        .iorm-status {{ font-weight: 700; font-size: 0.85rem; }}

        /* ---------- estados vazios ---------- */
        .iorm-card-vazio {{
            background: var(--iorm-superficie-alt); border: 1.5px dashed var(--iorm-borda-forte); border-radius: var(--iorm-raio);
            padding: 1.6rem 1.4rem; text-align: center; color: var(--iorm-cinza);
        }}
        .iorm-card-vazio-icone {{ font-size: 1.5rem; display: block; margin-bottom: 0.4rem; }}

        /* ---------- fluxo / diagrama ---------- */
        .iorm-fluxo-linha {{ display: flex; flex-direction: column; align-items: center; gap: 2px; margin: 1rem 0; }}
        .iorm-fluxo-caixa {{
            background-color: var(--iorm-azul); color: var(--iorm-on-azul); padding: 0.45rem 1.1rem;
            border-radius: var(--iorm-raio-sm); font-weight: 600; text-align: center; min-width: 300px; font-size: 0.88rem;
        }}
        .iorm-fluxo-seta {{ color: var(--iorm-laranja); font-size: 1.2rem; line-height: 1; }}

        /* ---------- avisos ---------- */
        .iorm-aviso {{
            background-color: var(--iorm-laranja-bg); border-left: 4px solid var(--iorm-laranja);
            padding: 0.75rem 1rem; border-radius: 6px; font-size: 0.88rem; color: var(--iorm-aviso-texto); margin: 0.6rem 0;
        }}
        .iorm-limitacao {{
            background-color: var(--iorm-vermelho-bg); border-left: 4px solid var(--iorm-vermelho);
            padding: 0.75rem 1rem; border-radius: 6px; font-size: 0.86rem; color: var(--iorm-limitacao-texto); margin: 0.6rem 0;
        }}
        .iorm-info {{
            background-color: var(--iorm-azul-bg); border-left: 4px solid var(--iorm-azul-claro);
            padding: 0.75rem 1rem; border-radius: 6px; font-size: 0.88rem; color: var(--iorm-info-texto); margin: 0.6rem 0;
        }}

        /* ---------- próxima ação (CTA de destaque) ---------- */
        .iorm-proxima-acao {{
            background: linear-gradient(120deg, var(--iorm-laranja-bg) 0%, var(--iorm-destaque-fim) 100%);
            border: 1px solid var(--iorm-destaque-borda); border-radius: var(--iorm-raio); padding: 1.1rem 1.3rem;
            margin: 0.8rem 0 1rem 0; display: flex; align-items: flex-start; gap: 0.8rem;
        }}
        .iorm-proxima-acao-icone {{ font-size: 1.4rem; line-height: 1; }}
        .iorm-proxima-acao-rotulo {{ font-size: 0.7rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.06em; color: var(--iorm-laranja-escuro); }}
        .iorm-proxima-acao-texto {{ color: var(--iorm-navy); font-weight: 700; font-size: 0.98rem; margin-top: 0.1rem; }}

        /* ---------- kanban (cartões do Dashboard) ---------- */
        .iorm-kanban-coluna {{
            background: var(--iorm-superficie-alt); border: 1px solid var(--iorm-borda); border-radius: var(--iorm-raio);
            padding: 0.7rem; min-height: 140px;
        }}
        .iorm-kanban-titulo {{
            font-weight: 800; color: var(--iorm-navy); font-size: 0.76rem; text-transform: uppercase; letter-spacing: 0.03em;
            padding-bottom: 0.4rem; border-bottom: 2px solid var(--iorm-borda); margin-bottom: 0.3rem;
        }}
        .iorm-kanban-cartao {{
            background: var(--iorm-superficie); border: 1px solid var(--iorm-borda); border-left: 4px solid var(--iorm-azul-claro);
            border-radius: var(--iorm-raio-sm); padding: 0.6rem 0.7rem; margin: 0.5rem 0; font-size: 0.83rem;
            box-shadow: var(--iorm-sombra-sm); color: var(--iorm-navy);
        }}
        .iorm-kanban-cartao b {{ color: var(--iorm-navy); }}
        .iorm-kanban-cartao-valor {{ color: var(--iorm-verde-escuro); font-weight: 700; }}

        /* ---------- timeline (CRM) ---------- */
        .iorm-timeline-item {{
            display: flex; gap: 0.8rem; padding: 0.55rem 0; border-left: 2px solid var(--iorm-borda);
            margin-left: 0.5rem; padding-left: 1rem; position: relative;
        }}
        .iorm-timeline-item::before {{
            content: ''; position: absolute; left: -6px; top: 0.75rem; width: 10px; height: 10px;
            border-radius: 50%; background: var(--iorm-azul-claro); box-shadow: 0 0 0 3px var(--iorm-azul-bg);
        }}
        .iorm-timeline-data {{ font-weight: 700; color: var(--iorm-azul); font-size: 0.82rem; min-width: 88px; }}
        .iorm-timeline-texto {{ font-size: 0.86rem; color: var(--iorm-navy); }}
        .iorm-timeline-meta {{ font-size: 0.78rem; color: var(--iorm-cinza); }}

        /* ---------- botões ---------- */
        .stButton > button, [data-testid^="stBaseLinkButton"], .stDownloadButton > button {{
            border-radius: var(--iorm-raio-sm); font-weight: 700; border: 1px solid var(--iorm-borda-forte);
            transition: background-color 0.12s ease, border-color 0.12s ease;
        }}
        .stButton > button[kind="primary"], [data-testid="stBaseLinkButton-primary"] {{
            background: var(--iorm-laranja); border-color: var(--iorm-laranja); color: #1A1204;
        }}
        .stButton > button[kind="primary"]:hover {{ background: var(--iorm-laranja-escuro); border-color: var(--iorm-laranja-escuro); color: #FFFFFF; }}

        /* ---------- tabs ---------- */
        .stTabs [data-baseweb="tab"] {{ font-weight: 700; font-size: 0.9rem; }}
        .stTabs [aria-selected="true"] {{ color: var(--iorm-azul) !important; }}

        /* ---------- dataframe ---------- */
        [data-testid="stDataFrame"] {{ border-radius: 8px; overflow: hidden; border: 1px solid var(--iorm-borda); }}

        /* ---------- LEGIBILIDADE: nada de "..." em informação importante ---------- */
        div[data-testid="stMetric"] {{ min-height: 104px; height: 100%; }}
        div[data-testid="stMetricLabel"], div[data-testid="stMetricLabel"] * {{
            white-space: normal !important; overflow: visible !important; text-overflow: clip !important; line-height: 1.25;
        }}
        div[data-testid="stMetricValue"], div[data-testid="stMetricValue"] * {{
            white-space: normal !important; overflow: visible !important; text-overflow: clip !important;
            overflow-wrap: anywhere; line-height: 1.15; font-size: clamp(1.1rem, 1.9vw, 1.9rem);
        }}
        div[data-testid="stMetricDelta"] {{ white-space: normal !important; }}
        .stButton > button, [data-testid^="stBaseLinkButton"], .stDownloadButton > button, [data-testid="stFormSubmitButton"] > button {{
            white-space: normal !important; height: auto !important; min-height: 2.5rem; line-height: 1.25; padding-top: 0.45rem; padding-bottom: 0.45rem;
        }}
        [data-testid="stExpander"] summary p, [data-testid="stExpander"] summary span {{
            white-space: normal !important; overflow: visible !important; text-overflow: clip !important;
        }}
        .stTabs [data-baseweb="tab"] {{ white-space: normal; height: auto; padding-top: 0.5rem; padding-bottom: 0.5rem; }}
        [data-testid="stCaptionContainer"], [data-testid="stMarkdownContainer"] {{ overflow-wrap: anywhere; }}
        [data-baseweb="select"] > div {{ height: auto; min-height: 2.5rem; }}
        [data-baseweb="select"] [class*="ValueContainer"], [data-baseweb="select"] div[value] {{
            white-space: normal !important; overflow: visible !important; text-overflow: clip !important;
        }}
        .iorm-cartao, .iorm-proxima-acao-texto, .iorm-kanban-cartao {{ overflow-wrap: anywhere; }}
        .iorm-cartao {{ min-height: 118px; }}

        /* aderência explicada: um critério por linha, badge + explicação sempre completos */
        .iorm-crit {{ display: flex; flex-wrap: wrap; align-items: baseline; gap: 0.35rem 0.8rem; margin: 0.28rem 0; }}
        .iorm-crit-texto {{ color: var(--iorm-cinza); font-size: 0.86rem; line-height: 1.4; flex: 1 1 260px; min-width: 0; }}
        /* cartão de edital do Dashboard */
        .iorm-edital-linha {{ color: var(--iorm-cinza); font-size: 0.84rem; line-height: 1.45; margin: 0.12rem 0; overflow-wrap: anywhere; }}
        .iorm-edital-linha b {{ color: var(--iorm-navy); }}
        .iorm-edital-resumo {{ color: var(--iorm-navy); font-size: 0.86rem; line-height: 1.45; margin-top: 0.4rem; overflow-wrap: anywhere; }}
        [data-testid="stVerticalBlockBorderWrapper"] .stButton > button[kind="tertiary"] {{
            text-align: left; justify-content: flex-start; font-weight: 800; color: var(--iorm-azul);
            padding-left: 0; font-size: 1rem; border: none;
        }}

        /* ---------- expander (usado como "cartão clicável" em editais etc.) ---------- */
        [data-testid="stExpander"] {{
            border: 1px solid var(--iorm-borda) !important; border-radius: var(--iorm-raio) !important;
            box-shadow: var(--iorm-sombra-sm); background: var(--iorm-superficie);
        }}
        [data-testid="stExpander"] summary {{ font-weight: 700; color: var(--iorm-navy); }}
        </style>
        """,
        unsafe_allow_html=True,
    )

def _logo_base64() -> str | None:
    """Prefere a versão com fundo transparente (fica bem sobre qualquer
    cor); cai para a JPEG original se, por algum motivo, o processamento
    da transparente não tiver rodado neste ambiente."""
    import base64

    caminho = CAMINHO_LOGO_TRANSPARENTE if CAMINHO_LOGO_TRANSPARENTE.exists() else CAMINHO_LOGO
    if not caminho.exists():
        return None
    tipo_mime = "image/png" if caminho.suffix == ".png" else "image/jpeg"
    b64 = base64.b64encode(caminho.read_bytes()).decode()
    return f"data:{tipo_mime};base64,{b64}"


def marca_sidebar() -> None:
    """Bloco de marca fixo no topo da barra lateral — logo + hierarquia
    "IORM RADAR / Inteligência para Captação de Recursos", visível em
    toda navegação (padrão SaaS), não uma logo pequena solta no canto."""
    src = _logo_base64()
    img_tag = f"<img src='{src}' width='42' style='object-fit:contain;'/>" if src else ""
    st.sidebar.markdown(
        f"""
        <div class="iorm-marca-sidebar">
            {img_tag}
            <div>
                <div class="iorm-marca-nome">IORM RADAR</div>
                <div class="iorm-marca-sub">Inteligência p/ Captação</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def cabecalho(titulo: str, subtitulo: str | None = None, eyebrow: str | None = None) -> None:
    """Cabeçalho de página: faixa com gradiente da marca + logo em
    destaque (não uma logo pequena solta no canto) + hierarquia visual
    clara de título/subtítulo. `eyebrow` é um rótulo curto opcional acima
    do título (ex: nome da seção de navegação)."""
    src = _logo_base64()
    img_html = f"<img src='{src}' width='48' style='object-fit:contain;'/>" if src else ""
    sub_html = f"<p>{subtitulo}</p>" if subtitulo else ""
    eyebrow_html = f"<span class='iorm-header-eyebrow'>{eyebrow}</span>" if eyebrow else ""
    st.markdown(
        f"""
        <div class="iorm-header">
            <div class="iorm-header-logo">{img_html}</div>
            <div class="iorm-header-texto">{eyebrow_html}<h1>{titulo}</h1>{sub_html}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def cartao_abrir(titulo: str, icone: str = "") -> None:
    """Abre um cartão visual reutilizável (fundo branco, borda, sombra
    leve) — usar com cartao_fechar() ao redor de um bloco de conteúdo
    (métricas, texto, badges). Para blocos com widgets interativos do
    Streamlit, prefira secao() — st.markdown não pode "abraçar" widgets."""
    st.markdown(
        f"<div class='iorm-cartao'><div class='iorm-cartao-titulo'>{icone} {titulo}</div>",
        unsafe_allow_html=True,
    )


def cartao_fechar() -> None:
    st.markdown("</div>", unsafe_allow_html=True)


def proxima_acao(texto: str, icone: str = "🎯", rotulo: str = "Próximo passo recomendado") -> None:
    """Caixa de destaque para a ação mais provável que o usuário precisa
    tomar agora — nunca uma recomendação inventada, só a leitura direta
    do estado de dados já existente (ver chamadas em cada página)."""
    st.markdown(
        f"""
        <div class="iorm-proxima-acao">
            <span class="iorm-proxima-acao-icone">{icone}</span>
            <div><div class="iorm-proxima-acao-rotulo">{rotulo}</div>
            <div class="iorm-proxima-acao-texto">{texto}</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def secao(titulo: str, icone: str = "", descricao: str | None = None) -> None:
    """Cabeçalho de seção consistente (usar em vez de st.markdown('### ...'))."""
    st.markdown(
        f"<div class='iorm-secao'><span class='iorm-secao-icone'>{icone}</span><h3>{titulo}</h3></div>",
        unsafe_allow_html=True,
    )
    if descricao:
        st.markdown(f"<p class='iorm-secao-desc'>{descricao}</p>", unsafe_allow_html=True)


def estado_vazio(mensagem: str, icone: str = "🗂️") -> None:
    st.markdown(
        f"<div class='iorm-card-vazio'><span class='iorm-card-vazio-icone'>{icone}</span>{mensagem}</div>",
        unsafe_allow_html=True,
    )


def grafico_barras(serie: pd.Series, rotulo_valor: str = "Quantidade", cor: str | None = None, moeda: bool = False) -> None:
    """Barras horizontais com o texto COMPLETO de cada categoria (st.bar_chart corta rótulos
    longos com "…"). Mantém a ordem recebida; a altura cresce com o número de barras.
    `moeda=True`: eixo e dica em reais no padrão brasileiro (R$ 1.000.000,00)."""
    import altair as alt

    cor = cor or tokens_do_tema()["grafico"]  # azul legível no tema ativo
    dados = serie.rename(rotulo_valor).rename_axis("Categoria").reset_index()
    if moeda:
        dados["Valor"] = dados[rotulo_valor].apply(formatar_moeda)
        eixo_x = alt.Axis(labelExpr="'R$ ' + replace(format(datum.value, ',.0f'), regexp(',', 'g'), '.')")
        dica = ["Categoria", alt.Tooltip("Valor:N", title=rotulo_valor)]
    else:
        eixo_x = alt.Axis(tickMinStep=1, format="d")
        dica = ["Categoria", rotulo_valor]
    grafico = (
        alt.Chart(dados)
        .mark_bar(color=cor)
        .encode(
            y=alt.Y("Categoria:N", sort=None, title=None, axis=alt.Axis(labelLimit=0)),
            x=alt.X(f"{rotulo_valor}:Q", title=rotulo_valor, axis=eixo_x),
            tooltip=dica,
        )
        .properties(height=max(120, 30 * len(dados)))
    )
    st.altair_chart(grafico, use_container_width=True)


def badge_origem(origem: str) -> str:
    if origem == "FONTE_EXTERNA":
        return "<span class='iorm-badge iorm-badge-azul'>✓ Fonte verificada</span>"
    return "<span class='iorm-badge iorm-badge-cinza'>✎ Preenchido manualmente</span>"


STATUS_INTEGRACAO = {
    "INTEGRADA": ("🟢", "Integrada e funcionando", "iorm-badge-verde"),
    "PARCIAL": ("🟡", "Fonte encontrada, integração parcial", "iorm-badge-laranja"),
    "MANUAL": ("🔵", "Cadastro/consulta manual", "iorm-badge-azul"),
    "INDISPONIVEL": ("🔴", "Ainda não disponível", "iorm-badge-vermelho"),
}


def badge_status_integracao(status: str) -> str:
    emoji, texto, classe = STATUS_INTEGRACAO.get(status, ("⚪", status, "iorm-badge-cinza"))
    return f"<span class='iorm-badge {classe}'>{emoji} {texto}</span>"


# Camada de Região IORM (ver processamento/regiao.py) -> (emoji, classe CSS).
_BADGE_REGIAO = {
    "CIDADE_ATUACAO": ("🎯", "iorm-badge-verde"),
    "REGIAO_PROXIMA": ("📍", "iorm-badge-azul"),
    "INTERESSE_ESTRATEGICO": ("🔶", "iorm-badge-laranja"),
    "FORA_DA_REGIAO": ("⚪", "iorm-badge-cinza"),
}


def badge_regiao_iorm(camada: str) -> str:
    from processamento import regiao

    emoji, classe = _BADGE_REGIAO.get(camada, ("⚪", "iorm-badge-cinza"))
    return f"<span class='iorm-badge {classe}'>{emoji} {regiao.rotulo(camada)}</span>"


@st.cache_data(ttl=60)
def carregar_dados_salic(caminho_db_str: str):
    conexao = metricas.conectar_leitura(Path(caminho_db_str))

    principal = osc.obter_osc_principal(conexao)
    perfil_osc = osc.carregar_perfil_completo(conexao, principal["id"]) if principal else None
    cidades_osc = perfil_osc["cidades"] if perfil_osc else None
    territorios_osc = perfil_osc["territorios"] if perfil_osc else None

    estatisticas = metricas.estatisticas_gerais(conexao, cidades_osc)
    estatisticas_contatos = metricas.estatisticas_enriquecimento(conexao)
    df_empresas = metricas.carregar_empresas(conexao, cidades_osc, territorios_osc)
    df_enriquecimento = metricas.carregar_enriquecimento(conexao)
    df_mesclado = metricas.mesclar_empresas_e_enriquecimento(df_empresas, df_enriquecimento)
    df_danca = metricas.doacoes_usina_da_danca(conexao)
    df_cidades = metricas.resumo_cidades_iorm(conexao, cidades_osc)
    df_fontes = metricas.listar_fontes(conexao)
    df_contatos_export = metricas.contatos_todos_para_exportacao(conexao)
    conexao.close()
    return {
        "estatisticas": estatisticas,
        "estatisticas_contatos": estatisticas_contatos,
        "df_empresas": df_empresas,
        "df_mesclado": df_mesclado,
        "df_danca": df_danca,
        "df_cidades": df_cidades,
        "df_fontes": df_fontes,
        "df_contatos_export": df_contatos_export,
        "territorios_osc": territorios_osc or [],
    }


def conectar() -> "sqlite3.Connection":
    import sqlite3  # local import só pra não poluir o topo do módulo

    conexao = sqlite3.connect(CAMINHO_DB)
    conexao.row_factory = sqlite3.Row
    conexao.execute("PRAGMA foreign_keys = ON;")
    return conexao


def garantir_tabelas_novas() -> None:
    """Cria (se ainda não existirem) as tabelas do Cérebro da OSC, Radar
    de Editais e CRM — idempotente, nunca apaga nada. Aplica migrações
    leves e seguras (ALTER TABLE ADD COLUMN) e semeia o IORM como OSC
    padrão se a tabela `osc` ainda estiver vazia."""
    conexao = conectar()
    banco.migrar_empresas(conexao)
    osc.criar_tabelas(conexao)
    documentos.migrar(conexao)
    geografia.criar_tabelas(conexao)
    editais.criar_tabelas(conexao)
    editais.migrar_colunas_novas(conexao)
    fontes_dados.criar_tabelas(conexao)
    incentivos_providers.migrar(conexao)
    crm.criar_tabelas(conexao)
    crm.migrar_colunas_novas(conexao)
    osc.semear_organizacao_padrao(conexao)
    relacionamento.sincronizar(conexao)
    descoberta_empresas.criar_tabelas(conexao)
    projetos_editais.criar_tabelas(conexao)
    principal = osc.obter_osc_principal(conexao)
    if principal is not None:  # só recalcula o que mudou (hash do edital + Cérebro da OSC): barato quando nada mudou
        projetos_editais.reanalisar_todos(conexao, osc.carregar_perfil_completo(conexao, principal["id"]))
    conexao.commit()
    conexao.close()


def obter_territorio_osc() -> list[str]:
    """Cidades cadastradas como território da OSC principal — é assim
    que o Cérebro da OSC "alimenta" o Radar de Empresas e o Radar de
    Editais. Sem OSC cadastrada ainda, devolve lista vazia (quem chama
    decide o fallback)."""
    conexao = conectar()
    principal = osc.obter_osc_principal(conexao)
    if principal is None:
        conexao.close()
        return []
    perfil = osc.carregar_perfil_completo(conexao, principal["id"])
    conexao.close()
    return perfil["cidades"]


def limpar_cache() -> None:
    st.cache_data.clear()


def carregar_fila_pesquisa() -> list[dict]:
    if not CAMINHO_FILA_PESQUISA.exists():
        return []
    return json.loads(CAMINHO_FILA_PESQUISA.read_text(encoding="utf-8"))


def adicionar_fila_pesquisa(empresa_id: int, razao_social: str) -> None:
    fila = carregar_fila_pesquisa()
    if not any(item["empresa_id"] == empresa_id for item in fila):
        fila.append(
            {"empresa_id": empresa_id, "razao_social": razao_social, "solicitado_em": datetime.now(timezone.utc).isoformat()}
        )
        CAMINHO_FILA_PESQUISA.write_text(json.dumps(fila, ensure_ascii=False, indent=2), encoding="utf-8")


def remover_fila_pesquisa(empresa_id: int) -> None:
    fila = [item for item in carregar_fila_pesquisa() if item["empresa_id"] != empresa_id]
    CAMINHO_FILA_PESQUISA.write_text(json.dumps(fila, ensure_ascii=False, indent=2), encoding="utf-8")
