import pytest

from processamento import enriquecimento


def test_classificar_prioridade_1():
    assert enriquecimento.classificar_prioridade("Gerente de Sustentabilidade") == "PRIORIDADE_1"
    assert enriquecimento.classificar_prioridade("Analista de ESG") == "PRIORIDADE_1"
    assert enriquecimento.classificar_prioridade("Instituto XYZ") == "PRIORIDADE_1"


def test_classificar_prioridade_2():
    assert enriquecimento.classificar_prioridade("Coordenador de Marketing") == "PRIORIDADE_2"
    assert enriquecimento.classificar_prioridade("Diretoria Executiva") == "PRIORIDADE_2"


def test_classificar_prioridade_3():
    assert enriquecimento.classificar_prioridade("Analista Fiscal") == "PRIORIDADE_3"
    assert enriquecimento.classificar_prioridade("Contabilidade") == "PRIORIDADE_3"


def test_classificar_prioridade_nao_reconhecido():
    assert enriquecimento.classificar_prioridade("Motorista") is None
    assert enriquecimento.classificar_prioridade(None) is None


def test_normalizar_email_valido():
    assert enriquecimento.normalizar_email(" Contato@Empresa.COM.BR ") == "contato@empresa.com.br"


def test_normalizar_email_invalido():
    assert enriquecimento.normalizar_email("nao-e-email") is None
    assert enriquecimento.normalizar_email(None) is None


def test_normalizar_telefone_com_pontuacao():
    assert enriquecimento.normalizar_telefone("(17) 3331-2233") == "1733312233"


def test_normalizar_telefone_com_codigo_pais():
    assert enriquecimento.normalizar_telefone("+55 17 3331-2233") == "+551733312233"


def test_normalizar_telefone_curto_demais_invalido():
    assert enriquecimento.normalizar_telefone("123") is None


def test_normalizar_url():
    assert enriquecimento.normalizar_url("https://empresa.com.br/") == "https://empresa.com.br"
    assert enriquecimento.normalizar_url("empresa.com.br") is None


def test_normalizar_nome_pessoa():
    assert enriquecimento.normalizar_nome_pessoa("  joão   DA silva  ") == "João Da Silva"


def test_validar_nivel_confianca_valido():
    assert enriquecimento.validar_nivel_confianca("ALTO") == "ALTO"


def test_validar_nivel_confianca_invalido():
    with pytest.raises(ValueError):
        enriquecimento.validar_nivel_confianca("SUPER_ALTO")


def test_validar_tipo_presenca_digital():
    assert enriquecimento.validar_tipo_presenca_digital("LinkedIn") == "linkedin"
    with pytest.raises(ValueError):
        enriquecimento.validar_tipo_presenca_digital("tiktok")


def test_validar_categoria_evidencia():
    assert enriquecimento.validar_categoria_evidencia("esg") == "ESG"
    with pytest.raises(ValueError):
        enriquecimento.validar_categoria_evidencia("INEXISTENTE")
