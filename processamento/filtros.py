"""Lógica de filtro e ordenação da tabela de empresas — separada dos
widgets do Streamlit para poder ser testada sem precisar rodar a
dashboard inteira. app.py só chama aplicar_filtros() com os valores
escolhidos no formulário "Aplicar Filtros"."""
from __future__ import annotations

import pandas as pd

FILTROS_PADRAO = {
    "estado": "Todos",
    "cidade": "Todas",
    "regiao": "Todas",
    "score_min": 0,
    "cnpj": "Todos",
    "tipo": "Todos",
    "ordenar": "IORM Score",
}

_COLUNA_ORDENACAO = {
    "IORM Score": "score",
    "Valor histórico": "valor_total",
    "Número de doações": "num_incentivos",
    "Nome": "razao_social",
    "Cidade": "cidade",
}


def aplicar_filtros(df: pd.DataFrame, filtros: dict) -> pd.DataFrame:
    if df.empty:
        return df

    resultado = df.copy()

    if filtros.get("estado", "Todos") != "Todos":
        resultado = resultado[resultado["estado"] == filtros["estado"]]

    if filtros.get("cidade", "Todas") != "Todas":
        resultado = resultado[resultado["cidade"] == filtros["cidade"]]

    regiao_filtro = filtros.get("regiao", "Todas")
    if regiao_filtro != "Todas" and "regiao_iorm" in resultado.columns:
        resultado = resultado[resultado["regiao_iorm"] == regiao_filtro]

    resultado = resultado[resultado["score"] >= filtros.get("score_min", 0)]

    cnpj_filtro = filtros.get("cnpj", "Todos")
    if cnpj_filtro == "Confirmado":
        resultado = resultado[resultado["cnpj_confirmado"]]
    elif cnpj_filtro == "Não confirmado":
        resultado = resultado[~resultado["cnpj_confirmado"]]

    tipo_filtro = filtros.get("tipo", "Todos")
    if tipo_filtro != "Todos":
        resultado = resultado[resultado["tipo_dado"] == tipo_filtro]

    coluna = _COLUNA_ORDENACAO.get(filtros.get("ordenar", "IORM Score"), "score")
    ascendente = coluna in ("razao_social", "cidade")
    return resultado.sort_values(coluna, ascending=ascendente)
