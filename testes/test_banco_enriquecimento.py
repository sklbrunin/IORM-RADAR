import sqlite3
from datetime import datetime, timezone

import pytest

from processamento import banco


@pytest.fixture
def conexao_e_empresa():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    banco.criar_tabelas(conn)
    banco.criar_tabelas_enriquecimento(conn)
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


def _agora():
    return datetime.now(timezone.utc).isoformat()


def test_presenca_digital_nova(conexao_e_empresa):
    conexao, empresa_id = conexao_e_empresa
    dados = {
        "empresa_id": empresa_id,
        "tipo": "site",
        "url": "https://empresa.com.br",
        "fonte": "busca institucional",
        "coletado_em": _agora(),
        "nivel_confianca": "ALTO",
    }
    _, criado = banco.inserir_ou_atualizar_presenca_digital(conexao, dados)
    assert criado is True
    total = conexao.execute("SELECT COUNT(*) FROM presenca_digital").fetchone()[0]
    assert total == 1


def test_presenca_digital_nao_duplica(conexao_e_empresa):
    conexao, empresa_id = conexao_e_empresa
    dados = {
        "empresa_id": empresa_id,
        "tipo": "site",
        "url": "https://empresa.com.br",
        "fonte": "busca institucional",
        "coletado_em": _agora(),
        "nivel_confianca": "ALTO",
    }
    banco.inserir_ou_atualizar_presenca_digital(conexao, dados)
    banco.inserir_ou_atualizar_presenca_digital(conexao, dados)
    total = conexao.execute("SELECT COUNT(*) FROM presenca_digital").fetchone()[0]
    assert total == 1


def test_contato_nao_duplica_e_nao_rebaixa_confianca(conexao_e_empresa):
    conexao, empresa_id = conexao_e_empresa
    base = {
        "empresa_id": empresa_id,
        "tipo_contato": "EMAIL_INSTITUCIONAL",
        "valor": "contato@empresa.com.br",
        "fonte": "site oficial",
        "url_fonte": "https://empresa.com.br/contato",
        "coletado_em": _agora(),
        "nivel_confianca": "ALTO",
    }
    banco.inserir_ou_atualizar_contato(conexao, base)

    # uma segunda fonte, mais fraca, tentando reduzir a confiança
    segunda = {**base, "fonte": "busca genérica", "nivel_confianca": "BAIXO"}
    id2, criado2 = banco.inserir_ou_atualizar_contato(conexao, segunda)

    assert criado2 is False
    total = conexao.execute("SELECT COUNT(*) FROM contatos").fetchone()[0]
    assert total == 1
    linha = conexao.execute("SELECT nivel_confianca FROM contatos WHERE id = ?", (id2,)).fetchone()
    assert linha["nivel_confianca"] == "ALTO"  # não foi rebaixado


def test_evidencia_nao_duplica(conexao_e_empresa):
    conexao, empresa_id = conexao_e_empresa
    dados = {
        "empresa_id": empresa_id,
        "categoria": "ESG",
        "descricao": "Publica relatório de sustentabilidade anual.",
        "url": "https://empresa.com.br/esg",
        "fonte": "site oficial",
        "coletado_em": _agora(),
        "nivel_confianca": "ALTO",
    }
    banco.inserir_ou_atualizar_evidencia(conexao, dados)
    banco.inserir_ou_atualizar_evidencia(conexao, dados)
    total = conexao.execute("SELECT COUNT(*) FROM evidencias").fetchone()[0]
    assert total == 1


def test_registrar_pesquisa(conexao_e_empresa):
    conexao, empresa_id = conexao_e_empresa
    banco.registrar_pesquisa(
        conexao,
        {
            "empresa_id": empresa_id,
            "executado_em": _agora(),
            "quantidade_fontes": 2,
            "quantidade_contatos": 1,
            "quantidade_redes": 1,
            "quantidade_evidencias": 1,
            "status": "SUCESSO",
        },
    )
    total = conexao.execute("SELECT COUNT(*) FROM historico_pesquisa").fetchone()[0]
    assert total == 1
