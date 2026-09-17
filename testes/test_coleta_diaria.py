import json
from unittest.mock import patch

import pytest

from coleta import coleta_diaria


def _pagina(cnpjs: list[str], total: int):
    return {
        "total": total,
        "_embedded": {
            "incentivadores": [
                {
                    "nome": f"Empresa {cnpj}",
                    "cgccpf": cnpj,
                    "UF": "SP",
                    "municipio": "Guaíra",
                    "total_doado": "1000.00",
                    "_links": {"self": f"https://api.salic.cultura.gov.br/incentivadores/{cnpj}"},
                }
                for cnpj in cnpjs
            ]
        },
    }


CNPJS_VALIDOS_A = ["11444777000161", "11222333000181"]  # dígitos verificadores válidos


@pytest.fixture
def caminhos_temporarios(tmp_path):
    return {
        "db": tmp_path / "teste.db",
        "estado": tmp_path / "estado.json",
        "log": tmp_path / "logs" / "coleta.log",
    }


def test_executar_para_ao_atingir_meta(caminhos_temporarios):
    with patch("coleta.coleta_diaria.coleta_salic.buscar_pagina") as mock_buscar:
        mock_buscar.return_value = _pagina(CNPJS_VALIDOS_A, total=2)
        resumo = coleta_diaria.executar(
            meta_empresas_novas=2, max_paginas_por_uf=5, ufs=["SP"],
            caminho_db=caminhos_temporarios["db"], caminho_estado=caminhos_temporarios["estado"],
            caminho_log=caminhos_temporarios["log"],
        )
    assert resumo["empresas_novas_total"] == 2
    assert resumo["erros"] == []


def test_executar_nao_duplica_empresa_ja_existente(caminhos_temporarios):
    # total bem maior que o tamanho da página -> a UF não fica "concluída" após uma
    # rodada, então uma segunda execução volta a processar a mesma página (simula
    # reencontrar as mesmas empresas) e o dedup por CNPJ precisa segurar a onda.
    with patch("coleta.coleta_diaria.coleta_salic.buscar_pagina") as mock_buscar:
        mock_buscar.return_value = _pagina(CNPJS_VALIDOS_A, total=1000)
        coleta_diaria.executar(
            meta_empresas_novas=2, max_paginas_por_uf=1, ufs=["SP"],
            caminho_db=caminhos_temporarios["db"], caminho_estado=caminhos_temporarios["estado"],
            caminho_log=caminhos_temporarios["log"],
        )
        caminhos_temporarios["estado"].write_text(json.dumps({"SP": {"offset": 0, "concluido": False}}), encoding="utf-8")
        resumo2 = coleta_diaria.executar(
            meta_empresas_novas=2, max_paginas_por_uf=1, ufs=["SP"],
            caminho_db=caminhos_temporarios["db"], caminho_estado=caminhos_temporarios["estado"],
            caminho_log=caminhos_temporarios["log"],
        )
    assert resumo2["empresas_novas_total"] == 0
    assert resumo2["empresas_existentes_total"] == 2


def test_executar_salva_estado_de_offset_por_uf(caminhos_temporarios):
    with patch("coleta.coleta_diaria.coleta_salic.buscar_pagina") as mock_buscar:
        mock_buscar.return_value = _pagina(CNPJS_VALIDOS_A, total=200)  # total grande -> UF não fica "concluído"
        coleta_diaria.executar(
            meta_empresas_novas=2, max_paginas_por_uf=1, ufs=["SP"],
            caminho_db=caminhos_temporarios["db"], caminho_estado=caminhos_temporarios["estado"],
            caminho_log=caminhos_temporarios["log"],
        )
    estado_salvo = json.loads(caminhos_temporarios["estado"].read_text(encoding="utf-8"))
    assert estado_salvo["SP"]["offset"] == coleta_diaria.coleta_salic.LIMITE_POR_PAGINA
    assert estado_salvo["SP"]["concluido"] is False


def test_executar_marca_uf_concluido_quando_api_esgota(caminhos_temporarios):
    with patch("coleta.coleta_diaria.coleta_salic.buscar_pagina") as mock_buscar:
        mock_buscar.return_value = _pagina(CNPJS_VALIDOS_A, total=2)  # total pequeno -> esgota na 1a página
        coleta_diaria.executar(
            meta_empresas_novas=100, max_paginas_por_uf=5, ufs=["SP"],
            caminho_db=caminhos_temporarios["db"], caminho_estado=caminhos_temporarios["estado"],
            caminho_log=caminhos_temporarios["log"],
        )
    estado_salvo = json.loads(caminhos_temporarios["estado"].read_text(encoding="utf-8"))
    assert estado_salvo["SP"]["concluido"] is True


def test_executar_pula_uf_ja_concluido(caminhos_temporarios):
    caminhos_temporarios["estado"].write_text(json.dumps({"SP": {"offset": 999, "concluido": True}}), encoding="utf-8")
    with patch("coleta.coleta_diaria.coleta_salic.buscar_pagina") as mock_buscar:
        resumo = coleta_diaria.executar(
            meta_empresas_novas=10, max_paginas_por_uf=5, ufs=["SP"],
            caminho_db=caminhos_temporarios["db"], caminho_estado=caminhos_temporarios["estado"],
            caminho_log=caminhos_temporarios["log"],
        )
    mock_buscar.assert_not_called()
    assert resumo["ufs_processadas"] == []


def test_executar_registra_log(caminhos_temporarios):
    with patch("coleta.coleta_diaria.coleta_salic.buscar_pagina") as mock_buscar:
        mock_buscar.return_value = _pagina(CNPJS_VALIDOS_A, total=2)
        coleta_diaria.executar(
            meta_empresas_novas=2, max_paginas_por_uf=1, ufs=["SP"],
            caminho_db=caminhos_temporarios["db"], caminho_estado=caminhos_temporarios["estado"],
            caminho_log=caminhos_temporarios["log"],
        )
    linhas = caminhos_temporarios["log"].read_text(encoding="utf-8").strip().splitlines()
    assert len(linhas) == 1
    registro = json.loads(linhas[0])
    assert registro["empresas_novas_total"] == 2


def test_executar_continua_apos_erro_de_rede(caminhos_temporarios):
    with patch("coleta.coleta_diaria.coleta_salic.buscar_pagina") as mock_buscar:
        mock_buscar.side_effect = ConnectionError("falha simulada")
        resumo = coleta_diaria.executar(
            meta_empresas_novas=10, max_paginas_por_uf=1, ufs=["SP"],
            caminho_db=caminhos_temporarios["db"], caminho_estado=caminhos_temporarios["estado"],
            caminho_log=caminhos_temporarios["log"],
        )
    assert len(resumo["erros"]) == 1
    assert "SP" in resumo["erros"][0]
