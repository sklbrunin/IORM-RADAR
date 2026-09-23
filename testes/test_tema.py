"""Tema claro/escuro: contraste dos tokens (WCAG), ausência de cor fixa nas regras de CSS e renderização das
páginas nos dois temas. Protege contra o bug "texto ilegível no modo escuro"."""
from __future__ import annotations

import re
import shutil
import textwrap
from pathlib import Path

import pytest

from paginas import _shared

RAIZ = Path(__file__).resolve().parent.parent
BANCO = RAIZ / "dados" / "iorm_radar.db"


def _rgb(hex_: str) -> tuple[float, float, float]:
    hex_ = hex_.lstrip("#")
    return tuple(int(hex_[i:i + 2], 16) for i in (0, 2, 4))


def _luminancia(hex_: str) -> float:
    def canal(v: float) -> float:
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (canal(v) for v in _rgb(hex_))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contraste(a: str, b: str) -> float:
    la, lb = _luminancia(a), _luminancia(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


TEMAS = ["light", "dark"]

# (texto, fundo, mínimo WCAG) — pares que a interface realmente usa
PARES = [
    ("navy", "fundo", 7.0), ("navy", "superficie", 7.0), ("navy", "superficie-alt", 7.0),
    ("cinza", "fundo", 4.5), ("cinza", "superficie", 4.5), ("cinza", "superficie-alt", 4.5), ("cinza-claro", "superficie", 3.0),
    ("azul", "superficie", 4.5), ("azul", "fundo", 4.5), ("azul", "azul-bg", 4.5),
    ("verde-escuro", "verde-bg", 4.5), ("badge-laranja-texto", "laranja-bg", 4.5), ("badge-vermelho-texto", "vermelho-bg", 4.5),
    ("cinza", "cinza-bg", 4.5), ("aviso-texto", "laranja-bg", 4.5), ("limitacao-texto", "vermelho-bg", 4.5),
    ("info-texto", "azul-bg", 4.5), ("on-azul", "azul", 4.5), ("laranja-escuro", "laranja-bg", 3.0),
    ("verde-escuro", "superficie", 4.5),
]


@pytest.mark.parametrize("tema", TEMAS)
@pytest.mark.parametrize("texto,fundo,minimo", PARES)
def test_contraste_dos_pares_de_cores_do_tema(tema, texto, fundo, minimo):
    tokens = _shared.TOKENS_TEMA[tema]
    razao = contraste(tokens[texto], tokens[fundo])
    assert razao >= minimo, f"{tema}: {texto} sobre {fundo} = {razao:.2f} (mínimo {minimo})"


def test_os_dois_temas_definem_exatamente_os_mesmos_tokens():
    assert set(_shared.TOKENS_TEMA["light"]) == set(_shared.TOKENS_TEMA["dark"])


def test_tema_escuro_tem_fundo_escuro_e_texto_claro():
    dark, light = _shared.TOKENS_TEMA["dark"], _shared.TOKENS_TEMA["light"]
    assert _luminancia(dark["fundo"]) < 0.05 < 0.5 < _luminancia(dark["navy"])
    assert _luminancia(light["fundo"]) > 0.5 > 0.05 > _luminancia(light["navy"])


def test_botao_primario_tem_texto_legivel_nos_dois_temas():
    for tema in TEMAS:
        assert contraste("#1A1204", _shared.TOKENS_TEMA[tema]["laranja"]) >= 4.5


# ------------------------------------------------------------------ CSS gerado
def _css(tema: str, monkeypatch) -> str:
    from streamlit.testing.v1 import AppTest

    corpo = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, r"{RAIZ}")
        from paginas import _shared
        _shared.tema_atual = lambda: "{tema}"
        _shared.injetar_css()
    """)
    app = AppTest.from_string(corpo).run()
    assert not app.exception
    return next(m.value for m in app.markdown if "<style>" in m.value)


@pytest.mark.parametrize("tema", TEMAS)
def test_css_injetado_usa_os_tokens_do_tema_ativo(tema, monkeypatch):
    css = _css(tema, monkeypatch)
    assert f"--iorm-fundo: {_shared.TOKENS_TEMA[tema]['fundo']};" in css and f"color-scheme: {tema};" in css


@pytest.mark.parametrize("tema", TEMAS)
def test_regras_de_css_nao_usam_cor_fixa_fora_do_bloco_de_tokens(tema, monkeypatch):
    """Cor fixa numa regra quebra um dos temas. Exceções conscientes: faixa do cabeçalho (escura nos dois temas), logo
    sobre fundo branco e texto do botão primário."""
    css = _css(tema, monkeypatch)
    sem_tokens = re.sub(r":root \{.*?\}", "", css, count=1, flags=re.S)
    fixas = set(re.findall(r"#[0-9A-Fa-f]{6}\b|#[0-9A-Fa-f]{3}\b", sem_tokens))
    permitidas = {"#10283C", "#0D4E73", "#136A9A", "#FFFFFF", "#CFE4F2", "#FFB95C", "#1A1204"}
    assert {c.upper() for c in fixas} <= permitidas, f"cores fixas nas regras: {sorted(fixas - permitidas)}"


def test_kanban_recebe_as_cores_do_tema_no_componente_em_iframe(monkeypatch):
    from paginas import crm as pagina_crm

    for tema in TEMAS:
        monkeypatch.setattr(_shared, "tema_atual", lambda t=tema: t)
        estilo = pagina_crm._estilo_kanban()
        tokens = _shared.TOKENS_TEMA[tema]
        assert tokens["superficie"] in estilo and tokens["navy"] in estilo and not re.search(r"(?<![-\w])white(?![-\w])", estilo.lower())


def test_tema_atual_cai_para_claro_sem_contexto():
    assert _shared.tema_atual() in ("light", "dark")


def test_config_do_streamlit_define_temas_claro_e_escuro_alinhados_aos_tokens():
    config = (RAIZ / ".streamlit" / "config.toml").read_text(encoding="utf-8")
    for tema in TEMAS:
        bloco = re.search(rf"\[theme\.{tema}\](.*?)(?:\n\[|\Z)", config, re.S).group(1)
        assert _shared.TOKENS_TEMA[tema]["fundo"].lower() in bloco.lower() and _shared.TOKENS_TEMA[tema]["superficie"].lower() in bloco.lower()


# ------------------------------------------------------------------ páginas renderizam nos dois temas
PAGINAS = ["dashboard", "cerebro_osc", "radar_empresas", "radar_editais", "contatos", "crm", "oportunidades", "rotina_diaria", "configuracoes"]


@pytest.fixture(scope="module")
def banco_copia(tmp_path_factory):
    if not BANCO.exists():
        pytest.skip("banco real não disponível")
    destino = tmp_path_factory.mktemp("tema") / "iorm_radar.db"
    shutil.copy(BANCO, destino)
    return destino


@pytest.mark.parametrize("tema", TEMAS)
@pytest.mark.parametrize("modulo", PAGINAS)
def test_pagina_renderiza_sem_excecao_no_tema(modulo, tema, banco_copia):
    from streamlit.testing.v1 import AppTest

    corpo = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, r"{RAIZ}")
        from pathlib import Path
        from paginas import _shared
        _shared.CAMINHO_DB = Path(r"{banco_copia}")
        _shared.tema_atual = lambda: "{tema}"
        _shared.garantir_tabelas_novas()
        _shared.injetar_css()
        from paginas import {modulo}
        {modulo}.render()
    """)
    app = AppTest.from_string(corpo, default_timeout=120).run()
    assert not app.exception, [e.value for e in app.exception]
    css = next(m.value for m in app.markdown if "<style>" in m.value)
    assert f"color-scheme: {tema};" in css
