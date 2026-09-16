import sqlite3

from coleta import importar_enriquecimento as importador
from processamento import banco


def test_validar_presenca_digital_valida():
    resultado = importador._validar_presenca_digital(
        {"tipo": "site", "url": "https://empresa.com.br", "fonte": "busca", "nivel_confianca": "ALTO"},
        empresa_id=1,
        agora="2026-01-01T00:00:00",
    )
    assert resultado["tipo"] == "site"
    assert resultado["url"] == "https://empresa.com.br"


def test_validar_presenca_digital_sem_url_e_descartada():
    resultado = importador._validar_presenca_digital(
        {"tipo": "site", "url": None, "fonte": "busca", "nivel_confianca": "ALTO"},
        empresa_id=1,
        agora="2026-01-01T00:00:00",
    )
    assert resultado is None


def test_validar_contato_email_institucional():
    resultado = importador._validar_contato(
        {
            "tipo_contato": "email_institucional",
            "valor": "Contato@Empresa.COM.BR",
            "fonte": "site oficial",
            "nivel_confianca": "ALTO",
        },
        empresa_id=1,
        agora="2026-01-01T00:00:00",
    )
    assert resultado["tipo_contato"] == "EMAIL_INSTITUCIONAL"
    assert resultado["valor"] == "contato@empresa.com.br"


def test_validar_contato_email_invalido_e_descartado():
    resultado = importador._validar_contato(
        {"tipo_contato": "EMAIL_INSTITUCIONAL", "valor": "nao-e-email", "fonte": "x", "nivel_confianca": "ALTO"},
        empresa_id=1,
        agora="2026-01-01T00:00:00",
    )
    assert resultado is None


def test_validar_contato_pessoa_cargo_classifica_prioridade():
    resultado = importador._validar_contato(
        {
            "tipo_contato": "PESSOA_CARGO",
            "nome": "maria silva",
            "cargo": "Gerente de Sustentabilidade",
            "valor": "https://www.linkedin.com/in/exemplo",
            "fonte": "LinkedIn (referência pública)",
            "nivel_confianca": "MEDIO",
        },
        empresa_id=1,
        agora="2026-01-01T00:00:00",
    )
    assert resultado["nome"] == "Maria Silva"
    assert resultado["prioridade"] == "PRIORIDADE_1"


def test_validar_evidencia_sem_descricao_e_descartada():
    resultado = importador._validar_evidencia(
        {"categoria": "ESG", "descricao": "", "fonte": "x", "nivel_confianca": "ALTO"},
        empresa_id=1,
        agora="2026-01-01T00:00:00",
    )
    assert resultado is None


def test_importar_empresa_inexistente_retorna_falha():
    conexao = sqlite3.connect(":memory:")
    conexao.row_factory = sqlite3.Row
    banco.criar_tabelas(conexao)
    banco.criar_tabelas_enriquecimento(conexao)

    resultado = importador.importar_empresa(conexao, {"empresa_id": 999, "status_pesquisa": "SUCESSO"})
    assert resultado["status"] == "FALHA"
    conexao.close()


def test_importar_empresa_completa_grava_tudo():
    conexao = sqlite3.connect(":memory:")
    conexao.row_factory = sqlite3.Row
    banco.criar_tabelas(conexao)
    banco.criar_tabelas_enriquecimento(conexao)
    empresa_id, _ = banco.obter_ou_criar_empresa(
        conexao,
        {
            "cnpj": "11444777000161",
            "razao_social": "Empresa Teste",
            "nome_fantasia": None,
            "cidade": "Guaíra",
            "estado": "SP",
            "status": None,
        },
    )

    item = {
        "empresa_id": empresa_id,
        "status_pesquisa": "SUCESSO",
        "presenca_digital": [
            {"tipo": "site", "url": "https://empresa.com.br", "fonte": "busca", "nivel_confianca": "ALTO"}
        ],
        "contatos": [
            {
                "tipo_contato": "EMAIL_INSTITUCIONAL",
                "valor": "contato@empresa.com.br",
                "fonte": "site oficial",
                "nivel_confianca": "ALTO",
            }
        ],
        "evidencias": [
            {
                "categoria": "SUSTENTABILIDADE",
                "descricao": "Publica relatório de sustentabilidade.",
                "fonte": "site oficial",
                "nivel_confianca": "ALTO",
            }
        ],
    }

    resultado = importador.importar_empresa(conexao, item)
    assert resultado["status"] == "SUCESSO"
    assert resultado["presenca_digital"] == 1
    assert resultado["contatos"] == 1
    assert resultado["evidencias"] == 1

    total_pesquisas = conexao.execute("SELECT COUNT(*) FROM historico_pesquisa").fetchone()[0]
    assert total_pesquisas == 1
    conexao.close()
