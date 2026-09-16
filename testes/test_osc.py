import sqlite3

import pytest

from processamento import osc


@pytest.fixture
def conexao():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    osc.criar_tabelas(conn)
    yield conn
    conn.close()


def test_criar_osc_e_obter_principal(conexao):
    assert osc.obter_osc_principal(conexao) is None
    osc_id = osc.criar_ou_atualizar_osc(conexao, None, {"nome": "Instituto Teste"})
    principal = osc.obter_osc_principal(conexao)
    assert principal["id"] == osc_id
    assert principal["nome"] == "Instituto Teste"


def test_atualizar_osc_existente_nao_duplica(conexao):
    osc_id = osc.criar_ou_atualizar_osc(conexao, None, {"nome": "Instituto Teste"})
    osc.criar_ou_atualizar_osc(conexao, osc_id, {"nome": "Instituto Teste Atualizado"})
    total = conexao.execute("SELECT COUNT(*) FROM osc").fetchone()[0]
    assert total == 1
    principal = osc.obter_osc_principal(conexao)
    assert principal["nome"] == "Instituto Teste Atualizado"


def test_adicionar_territorio_nao_duplica(conexao):
    osc_id = osc.criar_ou_atualizar_osc(conexao, None, {"nome": "Instituto Teste"})
    osc.adicionar_territorio(conexao, osc_id, "cidade", "Guaíra", prioritario=True, origem="FONTE_EXTERNA")
    osc.adicionar_territorio(conexao, osc_id, "cidade", "Guaíra", prioritario=True, origem="FONTE_EXTERNA")
    total = conexao.execute("SELECT COUNT(*) FROM osc_territorios").fetchone()[0]
    assert total == 1


def test_carregar_perfil_completo(conexao):
    osc_id = osc.criar_ou_atualizar_osc(conexao, None, {"nome": "Instituto Teste"})
    osc.adicionar_territorio(conexao, osc_id, "cidade", "Guaíra")
    osc.adicionar_territorio(conexao, osc_id, "estado", "SP")
    osc.adicionar_area_atuacao(conexao, osc_id, "educação")
    osc.adicionar_palavra_chave(conexao, osc_id, "Arte")
    osc.adicionar_mecanismo(conexao, osc_id, "Lei Rouanet")
    osc.adicionar_programa(conexao, osc_id, {"nome": "Usina da Dança", "publico": "crianças"})

    perfil = osc.carregar_perfil_completo(conexao, osc_id)
    assert perfil["cidades"] == ["Guaíra"]
    assert perfil["estados"] == ["SP"]
    assert "educação" in perfil["temas"]
    assert "arte" in perfil["palavras_chave"]  # normalizado para minúsculo
    assert "Lei Rouanet" in perfil["mecanismos"]
    assert len(perfil["programas"]) == 1


def test_adicionar_palavra_chave_vazia_e_ignorada(conexao):
    osc_id = osc.criar_ou_atualizar_osc(conexao, None, {"nome": "Instituto Teste"})
    osc.adicionar_palavra_chave(conexao, osc_id, "   ")
    total = conexao.execute("SELECT COUNT(*) FROM osc_palavras_chave").fetchone()[0]
    assert total == 0


def test_semear_organizacao_padrao_cria_iorm(conexao):
    osc_id = osc.semear_organizacao_padrao(conexao)
    assert osc_id is not None
    principal = osc.obter_osc_principal(conexao)
    assert "Oswaldo Ribeiro" in principal["nome"]
    assert principal["ano_fundacao"] == 2005
    perfil = osc.carregar_perfil_completo(conexao, osc_id)
    assert set(perfil["cidades"]) == {"Ipuã", "Guaíra", "Miguelópolis", "Orlândia"}
    assert "Lei Rouanet" in perfil["mecanismos"]


def test_semear_organizacao_padrao_e_idempotente(conexao):
    primeiro_id = osc.semear_organizacao_padrao(conexao)
    segundo_id = osc.semear_organizacao_padrao(conexao)
    assert primeiro_id == segundo_id
    total = conexao.execute("SELECT COUNT(*) FROM osc").fetchone()[0]
    assert total == 1


def test_semear_organizacao_padrao_nao_sobrescreve_edicao_manual(conexao):
    osc.semear_organizacao_padrao(conexao)
    principal = osc.obter_osc_principal(conexao)
    osc.criar_ou_atualizar_osc(conexao, principal["id"], {"nome": "Nome Editado Pelo Usuário"})

    osc.semear_organizacao_padrao(conexao)  # não deve rodar de novo, já existe uma OSC
    principal_depois = osc.obter_osc_principal(conexao)
    assert principal_depois["nome"] == "Nome Editado Pelo Usuário"
