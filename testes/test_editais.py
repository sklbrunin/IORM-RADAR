import sqlite3
from datetime import date

import pytest

from processamento import editais


@pytest.fixture
def conexao():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    editais.criar_tabelas(conn)
    yield conn
    conn.close()


def test_criar_edital_sem_data_fica_nao_confirmado(conexao):
    edital_id = editais.criar_edital(conexao, {"titulo": "Edital X", "fonte": "Busca automática"})
    linha = conexao.execute("SELECT situacao_inscricao FROM editais WHERE id = ?", (edital_id,)).fetchone()
    assert linha["situacao_inscricao"] == "NAO_CONFIRMADO"


def test_classificar_situacao_sem_data_encerramento():
    assert editais.classificar_situacao_inscricao(None, None) == "NAO_CONFIRMADO"


def test_classificar_situacao_encerrado():
    assert editais.classificar_situacao_inscricao(None, "2020-01-01", hoje=date(2026, 1, 1)) == "ENCERRADO"


def test_classificar_situacao_aberto():
    assert editais.classificar_situacao_inscricao(None, "2026-12-31", hoje=date(2026, 1, 1)) == "ABERTO"


def test_classificar_situacao_proximo():
    assert editais.classificar_situacao_inscricao("2026-06-01", "2026-12-31", hoje=date(2026, 1, 1)) == "PROXIMO"


def test_classificar_situacao_data_invalida_fica_nao_confirmado():
    assert editais.classificar_situacao_inscricao(None, "data-invalida") == "NAO_CONFIRMADO"


def test_migrar_colunas_novas_e_idempotente(conexao):
    editais.migrar_colunas_novas(conexao)
    editais.migrar_colunas_novas(conexao)  # rodar de novo não deve quebrar
    colunas = {linha["name"] for linha in conexao.execute("PRAGMA table_info(editais)")}
    assert "situacao_inscricao" in colunas
    assert "origem_descoberta" in colunas


PERFIL_IORM = {
    "cidades": ["Guaíra", "Ipuã", "Miguelópolis", "Orlândia"],
    "estados": ["SP"],
    "temas": ["educação", "cultura", "música", "dança"],
    "palavras_chave": ["arte", "juventude", "infância"],
    "programas": [{"publico": "crianças e adolescentes em vulnerabilidade social"}],
}


def _edital(**overrides):
    base = {
        "titulo": "Edital de Fomento à Cultura",
        "descricao": "Apoio a projetos de música e dança para crianças",
        "territorio": "Município de Guaíra/SP",
        "publico": "crianças e adolescentes",
        "requisitos": "Aberto a Organizações da Sociedade Civil (OSC) sem fins lucrativos",
        "valor_numerico": 50000,
        "data_encerramento": None,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------- área

def test_avaliar_area_encontra_temas():
    nota, motivo = editais._avaliar_area(_edital(), PERFIL_IORM["temas"], PERFIL_IORM["palavras_chave"])
    assert nota is not None and nota > 0
    assert "música" in motivo or "cultura" in motivo


def test_avaliar_area_sem_match_e_zero():
    edital = _edital(titulo="Edital de saneamento básico", descricao="Obras de infraestrutura urbana")
    nota, _ = editais._avaliar_area(edital, PERFIL_IORM["temas"], PERFIL_IORM["palavras_chave"])
    assert nota == 0.0


def test_avaliar_area_sem_temas_cadastrados_e_none():
    nota, _ = editais._avaliar_area(_edital(), [], [])
    assert nota is None


# ---------------------------------------------------------------- território

def test_avaliar_territorio_cidade_da_osc():
    nota, motivo = editais._avaliar_territorio(_edital(), PERFIL_IORM["cidades"], PERFIL_IORM["estados"])
    assert nota == 10.0
    assert "Guaíra" in motivo


def test_avaliar_territorio_fora_da_area():
    edital = _edital(territorio="Somente para o estado do Amazonas")
    nota, _ = editais._avaliar_territorio(edital, PERFIL_IORM["cidades"], PERFIL_IORM["estados"])
    assert nota == 0.0


def test_avaliar_territorio_sem_info_e_none():
    edital = _edital(territorio=None)
    nota, _ = editais._avaliar_territorio(edital, PERFIL_IORM["cidades"], PERFIL_IORM["estados"])
    assert nota is None


# ---------------------------------------------------------------- elegibilidade

def test_avaliar_elegibilidade_positiva():
    nota, _ = editais._avaliar_elegibilidade(_edital())
    assert nota == 8.0


def test_avaliar_elegibilidade_negativa():
    edital = _edital(requisitos="Somente empresas privadas podem participar")
    nota, _ = editais._avaliar_elegibilidade(edital)
    assert nota == 0.0


# ---------------------------------------------------------------- prazo

def test_avaliar_prazo_confortavel():
    edital = _edital(data_encerramento="2026-12-31")
    nota, _ = editais._avaliar_prazo(edital, hoje=date(2026, 9, 15))
    assert nota == 10.0


def test_avaliar_prazo_encerrado():
    edital = _edital(data_encerramento="2026-01-01")
    nota, motivo = editais._avaliar_prazo(edital, hoje=date(2026, 9, 15))
    assert nota == 0.0
    assert "encerrado" in motivo


def test_avaliar_prazo_sem_data_e_none():
    nota, _ = editais._avaliar_prazo(_edital(data_encerramento=None), hoje=date(2026, 9, 15))
    assert nota is None


# ---------------------------------------------------------------- aderência completa

def test_calcular_aderencia_alta_para_edital_compativel():
    edital = _edital(data_encerramento="2026-12-31")
    resultado = editais.calcular_aderencia(edital, PERFIL_IORM, hoje=date(2026, 9, 15))
    assert resultado["nota_final"] >= 7
    assert len(resultado["motivos_recomendacao"]) > 0


def test_calcular_aderencia_nunca_inventa_nota_sem_dado():
    edital_vazio = {"titulo": "", "descricao": ""}
    resultado = editais.calcular_aderencia(edital_vazio, PERFIL_IORM)
    assert resultado["nota_final"] is None or resultado["nota_area"] is None


def test_calcular_aderencia_registra_pontos_de_atencao():
    edital = _edital(territorio="Somente para o estado do Amazonas", data_encerramento="2026-12-31")
    resultado = editais.calcular_aderencia(edital, PERFIL_IORM, hoje=date(2026, 9, 15))
    assert len(resultado["pontos_atencao"]) > 0


# ---------------------------------------------------------------- persistência

def test_criar_edital_e_atualizar_status(conexao):
    edital_id = editais.criar_edital(
        conexao, {"titulo": "Edital Teste", "fonte": "Cadastro manual", "status": "ENCONTRADO"}
    )
    assert edital_id is not None

    editais.atualizar_status(conexao, edital_id, "ADERENTE")
    linha = conexao.execute("SELECT status FROM editais WHERE id = ?", (edital_id,)).fetchone()
    assert linha["status"] == "ADERENTE"


def test_atualizar_status_invalido_leva_erro(conexao):
    edital_id = editais.criar_edital(conexao, {"titulo": "Edital Teste", "fonte": "Cadastro manual"})
    with pytest.raises(ValueError):
        editais.atualizar_status(conexao, edital_id, "STATUS_INEXISTENTE")


def test_salvar_aderencia(conexao):
    edital_id = editais.criar_edital(conexao, {"titulo": "Edital Teste", "fonte": "Cadastro manual"})
    resultado = editais.calcular_aderencia(_edital(data_encerramento="2026-12-31"), PERFIL_IORM, hoje=date(2026, 9, 15))
    editais.salvar_aderencia(conexao, edital_id, osc_id=1, resultado=resultado)
    total = conexao.execute("SELECT COUNT(*) FROM editais_aderencia").fetchone()[0]
    assert total == 1
