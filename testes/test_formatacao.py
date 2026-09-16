import math

from processamento import formatacao


def test_formatar_moeda_br_valor_grande():
    assert formatacao.formatar_moeda_br(16905389.94) == "R$ 16.905.389,94"


def test_formatar_moeda_br_valor_pequeno():
    assert formatacao.formatar_moeda_br(1500) == "R$ 1.500,00"


def test_formatar_moeda_br_zero():
    assert formatacao.formatar_moeda_br(0) == "R$ 0,00"


def test_formatar_moeda_br_none():
    assert formatacao.formatar_moeda_br(None) == "Não disponível"


def test_formatar_moeda_br_nan():
    assert formatacao.formatar_moeda_br(math.nan) == "Não disponível"


def test_formatar_numero_br():
    assert formatacao.formatar_numero_br(8211) == "8.211"
    assert formatacao.formatar_numero_br(0) == "0"


def test_formatar_numero_br_none():
    assert formatacao.formatar_numero_br(None) == "Não disponível"


def test_formatar_cnpj_valido():
    assert formatacao.formatar_cnpj("11444777000161") == "11.444.777/0001-61"


def test_formatar_cnpj_ausente():
    assert formatacao.formatar_cnpj(None) == "Não disponível"
    assert formatacao.formatar_cnpj("") == "Não disponível"


def test_formatar_percentual():
    assert formatacao.formatar_percentual(10.5) == "10,5%"
    assert formatacao.formatar_percentual(100) == "100,0%"


def test_formatar_percentual_none():
    assert formatacao.formatar_percentual(None) == "Não disponível"


def test_formatar_data_br():
    assert formatacao.formatar_data_br("2026-09-15") == "15/09/2026"
    assert formatacao.formatar_data_br("2026-09-15T10:30:00") == "15/09/2026"


def test_formatar_data_br_ausente():
    assert formatacao.formatar_data_br(None) == "Não disponível"
    assert formatacao.formatar_data_br("") == "Não disponível"
