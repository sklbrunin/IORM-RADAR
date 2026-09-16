import sqlite3
from datetime import date

import pytest

from processamento import banco, crm


@pytest.fixture
def conexao():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    banco.criar_tabelas(conn)
    banco.criar_tabelas_enriquecimento(conn)
    crm.criar_tabelas(conn)
    empresa_id, _ = banco.obter_ou_criar_empresa(
        conn,
        {
            "cnpj": "11444777000161",
            "razao_social": "Empresa Teste",
            "nome_fantasia": None,
            "cidade": "Guaíra",
            "estado": "SP",
            "status": None,
        },
    )
    yield conn, empresa_id
    conn.close()


# ---------------------------------------------------------------- persistência

def test_criar_oportunidade(conexao):
    conn, empresa_id = conexao
    op_id = crm.criar_oportunidade(conn, {"empresa_id": empresa_id, "titulo": "Patrocínio 2026"})
    assert op_id is not None
    linha = conn.execute("SELECT estagio FROM crm_oportunidades WHERE id = ?", (op_id,)).fetchone()
    assert linha["estagio"] == "Prospect"


def test_estagio_invalido_vira_prospect(conexao):
    conn, empresa_id = conexao
    op_id = crm.criar_oportunidade(conn, {"empresa_id": empresa_id, "titulo": "X", "estagio": "Nao Existe"})
    linha = conn.execute("SELECT estagio FROM crm_oportunidades WHERE id = ?", (op_id,)).fetchone()
    assert linha["estagio"] == "Prospect"


def test_mover_estagio(conexao):
    conn, empresa_id = conexao
    op_id = crm.criar_oportunidade(conn, {"empresa_id": empresa_id, "titulo": "X"})
    crm.mover_estagio(conn, op_id, "Reunião")
    linha = conn.execute("SELECT estagio FROM crm_oportunidades WHERE id = ?", (op_id,)).fetchone()
    assert linha["estagio"] == "Reunião"


def test_mover_estagio_invalido_leva_erro(conexao):
    conn, empresa_id = conexao
    op_id = crm.criar_oportunidade(conn, {"empresa_id": empresa_id, "titulo": "X"})
    with pytest.raises(ValueError):
        crm.mover_estagio(conn, op_id, "Estágio Fantasia")


def test_empresa_ja_tem_oportunidade_aberta(conexao):
    conn, empresa_id = conexao
    assert crm.empresa_ja_tem_oportunidade_aberta(conn, empresa_id) is False
    crm.criar_oportunidade(conn, {"empresa_id": empresa_id, "titulo": "X"})
    assert crm.empresa_ja_tem_oportunidade_aberta(conn, empresa_id) is True


def test_oportunidade_fechada_nao_conta_como_aberta(conexao):
    conn, empresa_id = conexao
    op_id = crm.criar_oportunidade(conn, {"empresa_id": empresa_id, "titulo": "X"})
    crm.mover_estagio(conn, op_id, "Fechado — perdido")
    assert crm.empresa_ja_tem_oportunidade_aberta(conn, empresa_id) is False


def test_registrar_interacao(conexao):
    conn, empresa_id = conexao
    op_id = crm.criar_oportunidade(conn, {"empresa_id": empresa_id, "titulo": "X"})
    crm.registrar_interacao(
        conn, {"oportunidade_id": op_id, "tipo": "ligacao", "data": "2026-09-15", "descricao": "Primeiro contato"}
    )
    interacoes = crm.listar_interacoes(conn, op_id)
    assert len(interacoes) == 1


# ---------------------------------------------------------------- funções puras

def test_classificar_follow_ups():
    oportunidades = [
        {"estagio": "Prospect", "proxima_acao_data": "2026-09-10"},  # atrasada
        {"estagio": "Reunião", "proxima_acao_data": "2026-09-15"},  # hoje
        {"estagio": "Proposta enviada", "proxima_acao_data": "2026-09-20"},  # futura
        {"estagio": "Em conversa", "proxima_acao_data": None},  # sem followup
        {"estagio": "Fechado — ganho", "proxima_acao_data": "2026-09-01"},  # ignorada (fechada)
    ]
    resultado = crm.classificar_follow_ups(oportunidades, hoje=date(2026, 9, 15))
    assert len(resultado["atrasadas"]) == 1
    assert len(resultado["hoje"]) == 1
    assert len(resultado["futuras"]) == 1
    assert len(resultado["sem_followup"]) == 1


def test_valor_potencial_total_ignora_fechadas():
    oportunidades = [
        {"estagio": "Prospect", "valor_potencial": 1000},
        {"estagio": "Fechado — ganho", "valor_potencial": 5000},
        {"estagio": "Fechado — perdido", "valor_potencial": 2000},
        {"estagio": "Negociação", "valor_potencial": 3000},
    ]
    assert crm.valor_potencial_total(oportunidades) == 4000


def test_migrar_colunas_novas_e_idempotente():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    # simula um banco "antigo", sem a coluna programa_relacionado
    conn.executescript(
        """
        CREATE TABLE crm_oportunidades (
            id INTEGER PRIMARY KEY AUTOINCREMENT, empresa_id INTEGER, contato_id INTEGER,
            titulo TEXT NOT NULL, estagio TEXT NOT NULL DEFAULT 'Prospect', valor_potencial REAL,
            mecanismo TEXT, probabilidade INTEGER, responsavel TEXT, proxima_acao_data TEXT,
            proxima_acao_descricao TEXT, proxima_acao_prioridade TEXT,
            criado_em TEXT NOT NULL, atualizado_em TEXT NOT NULL
        );
        """
    )
    crm.migrar_colunas_novas(conn)
    colunas = {linha["name"] for linha in conn.execute("PRAGMA table_info(crm_oportunidades)")}
    assert "programa_relacionado" in colunas

    crm.migrar_colunas_novas(conn)  # rodar de novo não deve dar erro
    conn.close()


def test_oportunidades_sem_proxima_acao():
    oportunidades = [
        {"estagio": "Prospect", "proxima_acao_data": None},
        {"estagio": "Reunião", "proxima_acao_data": "2026-09-20"},
        {"estagio": "Fechado — ganho", "proxima_acao_data": None},  # fechada, não conta
    ]
    resultado = crm.oportunidades_sem_proxima_acao(oportunidades)
    assert len(resultado) == 1
    assert resultado[0]["estagio"] == "Prospect"


def test_contar_por_estagio():
    oportunidades = [{"estagio": "Prospect"}, {"estagio": "Prospect"}, {"estagio": "Reunião"}]
    contagem = crm.contar_por_estagio(oportunidades)
    assert contagem["Prospect"] == 2
    assert contagem["Reunião"] == 1
    assert contagem["Negociação"] == 0
