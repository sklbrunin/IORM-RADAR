from processamento import validadores


def test_normalizar_cnpj_remove_pontuacao():
    assert validadores.normalizar_cnpj("11.444.777/0001-61") == "11444777000161"


def test_normalizar_cnpj_tamanho_errado_retorna_none():
    assert validadores.normalizar_cnpj("123") is None


def test_normalizar_cnpj_vazio_retorna_none():
    assert validadores.normalizar_cnpj(None) is None
    assert validadores.normalizar_cnpj("") is None


def test_validar_cnpj_valido():
    # CNPJ de teste conhecido/publicamente usado para validar o algoritmo
    assert validadores.validar_cnpj("11444777000161") is True


def test_validar_cnpj_digitos_verificadores_errados():
    assert validadores.validar_cnpj("11444777000199") is False


def test_validar_cnpj_sequencia_repetida_e_invalida():
    assert validadores.validar_cnpj("00000000000000") is False


def test_validar_cnpj_tamanho_errado():
    assert validadores.validar_cnpj("123") is False


def test_validar_uf_valida_fica_maiuscula():
    assert validadores.validar_uf("sp") == "SP"


def test_validar_uf_invalida_retorna_none():
    assert validadores.validar_uf("XX") is None


def test_validar_ano_dentro_do_intervalo():
    assert validadores.validar_ano(2023) == 2023


def test_validar_ano_fora_do_intervalo():
    assert validadores.validar_ano(1800) is None


def test_validar_valor_numero_valido():
    assert validadores.validar_valor("1500.50") == 1500.50


def test_validar_valor_negativo_e_invalido():
    assert validadores.validar_valor(-10) is None


def test_validar_url_valida():
    url = "https://api.salic.cultura.gov.br/x"
    assert validadores.validar_url(url) == url


def test_validar_url_invalida():
    assert validadores.validar_url("nao-e-uma-url") is None
