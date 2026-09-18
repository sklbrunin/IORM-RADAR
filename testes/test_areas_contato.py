import pytest

from processamento import enriquecimento as enr


@pytest.mark.parametrize("cargo,area", [
    ("Gerente de Sustentabilidade", "Sustentabilidade"),
    ("Coordenadora de ESG", "ESG"),
    ("Analista de Marketing Digital", "Marketing"),
    ("Assessoria de Comunicação", "Comunicação"),
    ("Contador", "Contabilidade"),
    ("Diretor Jurídico", "Jurídico"),
    ("Head de Relações com Investidores", "Relações com Investidores"),
    ("Analista Fiscal", "Fiscal"),
    ("Especialista Tributário", "Tributário"),
    ("Controller", "Controladoria"),
    ("Gerente de Recursos Humanos", "RH"),
    ("Coordenador de Captação de Recursos", "Captação/Patrocínios"),
    ("Instituto Fulano - Analista", "Instituto/Fundação"),
    ("Presidente", "Diretoria"),
    ("Responsável por Relações Institucionais", "Relações Institucionais"),
])
def test_classificar_area_de_cargo(cargo, area):
    assert enr.classificar_area(cargo) == area


def test_classificar_area_sem_palavra_conhecida_devolve_none():
    assert enr.classificar_area("Consultor") is None
    assert enr.classificar_area(None) is None
    assert enr.classificar_area("") is None


@pytest.mark.parametrize("email,area", [
    ("financeiro@empresa.com.br", "Financeiro"),
    ("rh@empresa.com.br", "RH"),
    ("marketing@empresa.com.br", "Marketing"),
    ("sustentabilidade@empresa.com.br", "Sustentabilidade"),
    ("juridico@empresa.com.br", "Jurídico"),
    ("contato@empresa.com.br", "Atendimento/Geral"),
    ("patrocinios@empresa.com.br", "Captação/Patrocínios"),
    ("comunicacao@empresa.com.br", "Comunicação"),
    ("contabil@empresa.com.br", "Contabilidade"),
])
def test_area_do_email_institucional(email, area):
    assert enr.area_do_email(email) == area


def test_email_generico_nao_e_atribuido_a_pessoa():
    assert enr.parece_email_de_pessoa("financeiro@empresa.com.br") is False
    assert enr.parece_email_de_pessoa("contato@empresa.com.br") is False


def test_email_nome_sobrenome_parece_pessoal_mas_area_fica_indefinida():
    assert enr.parece_email_de_pessoa("joao.silva@empresa.com.br") is True
    assert enr.area_do_email("joao.silva@empresa.com.br") is None


def test_area_do_email_invalido_ou_vazio():
    assert enr.area_do_email("nao-e-email") is None
    assert enr.area_do_email(None) is None


def test_prioridades_incluem_novas_areas():
    assert enr.classificar_prioridade("Gerente Jurídico") == "PRIORIDADE_3"
    assert enr.classificar_prioridade("Relações com Investidores") == "PRIORIDADE_2"
    assert enr.classificar_prioridade("Captação de Recursos") == "PRIORIDADE_1"
