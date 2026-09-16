import sqlite3
from datetime import datetime, timezone

import pytest

from processamento import banco


@pytest.fixture
def conexao():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    banco.criar_tabelas(conn)
    yield conn
    conn.close()


def _dados_empresa(cnpj="11444777000161"):
    return {
        "cnpj": cnpj,
        "razao_social": "Empresa Teste",
        "nome_fantasia": None,
        "cidade": "Ribeirão Preto",
        "estado": "SP",
        "status": None,
    }


def _dados_incentivo(empresa_id, url_fonte="https://api.salic.cultura.gov.br/api/v1/incentivadores/abc123"):
    return {
        "empresa_id": empresa_id,
        "fonte": "SALIC",
        "tipo_incentivo": "Lei Rouanet",
        "projeto": None,
        "ano": None,
        "valor": 1000.0,
        "uf": "SP",
        "cidade": "Ribeirão Preto",
        "url_fonte": url_fonte,
        "coletado_em": datetime.now(timezone.utc).isoformat(),
        "nivel_confianca": "Alta",
    }


def test_criar_empresa_nova(conexao):
    empresa_id, criada = banco.obter_ou_criar_empresa(conexao, _dados_empresa())
    assert criada is True
    assert empresa_id is not None


def test_mesma_empresa_por_cnpj_nao_duplica(conexao):
    id1, criada1 = banco.obter_ou_criar_empresa(conexao, _dados_empresa())
    id2, criada2 = banco.obter_ou_criar_empresa(conexao, _dados_empresa())
    assert id1 == id2
    assert criada1 is True
    assert criada2 is False
    total = conexao.execute("SELECT COUNT(*) FROM empresas").fetchone()[0]
    assert total == 1


def test_empresas_sem_cnpj_nao_sao_fundidas_automaticamente(conexao):
    dados = _dados_empresa(cnpj=None)
    id1, _ = banco.obter_ou_criar_empresa(conexao, dados)
    id2, _ = banco.obter_ou_criar_empresa(conexao, dados)
    assert id1 != id2  # sem CNPJ confirmado, cada registro vira uma linha própria


def test_inserir_incentivo_e_reexecutar_nao_duplica(conexao):
    empresa_id, _ = banco.obter_ou_criar_empresa(conexao, _dados_empresa())
    dados_incentivo = _dados_incentivo(empresa_id)

    id1, criado1 = banco.inserir_ou_atualizar_incentivo(conexao, dados_incentivo)
    id2, criado2 = banco.inserir_ou_atualizar_incentivo(conexao, dados_incentivo)

    assert criado1 is True
    assert criado2 is False
    assert id1 == id2
    total = conexao.execute("SELECT COUNT(*) FROM incentivos").fetchone()[0]
    assert total == 1


def test_reexecucao_atualiza_valor_em_vez_de_duplicar(conexao):
    empresa_id, _ = banco.obter_ou_criar_empresa(conexao, _dados_empresa())
    dados_incentivo = _dados_incentivo(empresa_id)
    banco.inserir_ou_atualizar_incentivo(conexao, dados_incentivo)

    dados_incentivo["valor"] = 2500.0
    banco.inserir_ou_atualizar_incentivo(conexao, dados_incentivo)

    linha = conexao.execute("SELECT valor FROM incentivos WHERE url_fonte = ?", (dados_incentivo["url_fonte"],)).fetchone()
    assert linha["valor"] == 2500.0
