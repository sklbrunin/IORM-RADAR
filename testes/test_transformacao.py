from processamento import transformacao

REGISTRO_EXEMPLO = {
    "nome": "Empresa Exemplo LTDA",
    "municipio": "Ribeirão Preto",
    "UF": "SP",
    "responsavel": "",
    "total_doado": 5000.0,
    "tipo_pessoa": "juridica",
    "cgccpf": "11444777000161",
    "_links": {"self": "https://api.salic.cultura.gov.br/api/v1/incentivadores/abc123"},
}


def test_transforma_registro_valido():
    resultado = transformacao.transformar_registro(REGISTRO_EXEMPLO, fonte_nome="SALIC")
    assert resultado is not None
    assert resultado["empresa"]["cnpj"] == "11444777000161"
    assert resultado["empresa"]["razao_social"] == "Empresa Exemplo LTDA"
    assert resultado["empresa"]["estado"] == "SP"
    assert resultado["incentivo"]["valor"] == 5000.0
    assert resultado["incentivo"]["url_fonte"].startswith("https://")
    # nesta etapa o endpoint usado não fornece projeto/ano — tem que ficar None, não inventado
    assert resultado["incentivo"]["projeto"] is None
    assert resultado["incentivo"]["ano"] is None


def test_registro_sem_nome_e_descartado():
    registro = {**REGISTRO_EXEMPLO, "nome": ""}
    assert transformacao.transformar_registro(registro, fonte_nome="SALIC") is None


def test_registro_sem_url_e_descartado():
    registro = {**REGISTRO_EXEMPLO, "_links": {}}
    assert transformacao.transformar_registro(registro, fonte_nome="SALIC") is None


def test_cnpj_matematicamente_invalido_vira_none_mas_nao_descarta_registro():
    registro = {**REGISTRO_EXEMPLO, "cgccpf": "00000000000000"}
    resultado = transformacao.transformar_registro(registro, fonte_nome="SALIC")
    assert resultado is not None
    assert resultado["empresa"]["cnpj"] is None


def test_sem_cgccpf_cnpj_fica_none():
    registro = {**REGISTRO_EXEMPLO, "cgccpf": None}
    resultado = transformacao.transformar_registro(registro, fonte_nome="SALIC")
    assert resultado["empresa"]["cnpj"] is None


DOACAO_EXEMPLO = {
    "PRONAC": "121680",
    "valor": 5200,
    "data_recibo": "2013-12-30",
    "nome_projeto": "Usina da Dança",
    "cgccpf": "65744138000140",
    "nome_doador": "Aguetoni Transportes Ltda.",
}


def test_transforma_doacao_valida():
    resultado = transformacao.transformar_doacao(
        DOACAO_EXEMPLO,
        url_doacoes_empresa="https://api.salic.cultura.gov.br/api/v1/incentivadores/65744138000140/doacoes",
        fonte_nome="SALIC",
    )
    assert resultado is not None
    assert resultado["projeto"] == "Usina da Dança"
    assert resultado["ano"] == 2013
    assert resultado["valor"] == 5200
    assert "pronac=121680" in resultado["url_fonte"]


def test_doacao_sem_pronac_e_descartada():
    registro = {**DOACAO_EXEMPLO, "PRONAC": ""}
    assert transformacao.transformar_doacao(registro, "https://x/doacoes", "SALIC") is None


def test_doacao_sem_data_recibo_ano_fica_none():
    registro = {**DOACAO_EXEMPLO, "data_recibo": None}
    resultado = transformacao.transformar_doacao(registro, "https://x/doacoes", "SALIC")
    assert resultado["ano"] is None
