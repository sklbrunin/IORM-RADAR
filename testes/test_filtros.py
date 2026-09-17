import pandas as pd
import pytest

from processamento import filtros


@pytest.fixture
def df_exemplo():
    return pd.DataFrame(
        [
            {"razao_social": "Empresa A", "estado": "SP", "cidade": "Guaíra", "score": 90,
             "valor_total": 500000, "num_incentivos": 5, "cnpj_confirmado": True, "tipo_dado": "Detalhado"},
            {"razao_social": "Empresa B", "estado": "SP", "cidade": "Orlândia", "score": 40,
             "valor_total": 1000, "num_incentivos": 1, "cnpj_confirmado": False, "tipo_dado": "Agregado"},
            {"razao_social": "Empresa C", "estado": "PR", "cidade": "Curitiba", "score": 60,
             "valor_total": 20000, "num_incentivos": 2, "cnpj_confirmado": True, "tipo_dado": "Agregado"},
        ]
    )


def test_sem_filtro_devolve_tudo_ordenado_por_score(df_exemplo):
    resultado = filtros.aplicar_filtros(df_exemplo, filtros.FILTROS_PADRAO)
    assert list(resultado["razao_social"]) == ["Empresa A", "Empresa C", "Empresa B"]


def test_filtro_por_estado(df_exemplo):
    resultado = filtros.aplicar_filtros(df_exemplo, {**filtros.FILTROS_PADRAO, "estado": "PR"})
    assert list(resultado["razao_social"]) == ["Empresa C"]


def test_filtro_por_cidade(df_exemplo):
    resultado = filtros.aplicar_filtros(df_exemplo, {**filtros.FILTROS_PADRAO, "cidade": "Guaíra"})
    assert list(resultado["razao_social"]) == ["Empresa A"]


def test_filtro_por_score_minimo(df_exemplo):
    resultado = filtros.aplicar_filtros(df_exemplo, {**filtros.FILTROS_PADRAO, "score_min": 60})
    assert set(resultado["razao_social"]) == {"Empresa A", "Empresa C"}


def test_filtro_cnpj_confirmado(df_exemplo):
    resultado = filtros.aplicar_filtros(df_exemplo, {**filtros.FILTROS_PADRAO, "cnpj": "Confirmado"})
    assert set(resultado["razao_social"]) == {"Empresa A", "Empresa C"}


def test_filtro_cnpj_nao_confirmado(df_exemplo):
    resultado = filtros.aplicar_filtros(df_exemplo, {**filtros.FILTROS_PADRAO, "cnpj": "Não confirmado"})
    assert list(resultado["razao_social"]) == ["Empresa B"]


def test_filtro_tipo_dado(df_exemplo):
    resultado = filtros.aplicar_filtros(df_exemplo, {**filtros.FILTROS_PADRAO, "tipo": "Detalhado"})
    assert list(resultado["razao_social"]) == ["Empresa A"]


def test_ordenar_por_nome(df_exemplo):
    resultado = filtros.aplicar_filtros(df_exemplo, {**filtros.FILTROS_PADRAO, "ordenar": "Nome"})
    assert list(resultado["razao_social"]) == ["Empresa A", "Empresa B", "Empresa C"]


def test_filtros_combinados(df_exemplo):
    resultado = filtros.aplicar_filtros(
        df_exemplo, {**filtros.FILTROS_PADRAO, "estado": "SP", "cnpj": "Confirmado"}
    )
    assert list(resultado["razao_social"]) == ["Empresa A"]


def test_df_vazio_nao_quebra():
    vazio = pd.DataFrame()
    assert filtros.aplicar_filtros(vazio, filtros.FILTROS_PADRAO).empty


def test_filtro_regiao_iorm(df_exemplo):
    df_exemplo["regiao_iorm"] = ["CIDADE_ATUACAO", "CIDADE_ATUACAO", "FORA_DA_REGIAO"]
    resultado = filtros.aplicar_filtros(df_exemplo, {**filtros.FILTROS_PADRAO, "regiao": "FORA_DA_REGIAO"})
    assert list(resultado["razao_social"]) == ["Empresa C"]


def test_filtro_regiao_iorm_sem_coluna_nao_quebra(df_exemplo):
    # DataFrame sem regiao_iorm (código antigo) + filtro de região setado -> não deve dar KeyError
    resultado = filtros.aplicar_filtros(df_exemplo, {**filtros.FILTROS_PADRAO, "regiao": "CIDADE_ATUACAO"})
    assert len(resultado) == 3
