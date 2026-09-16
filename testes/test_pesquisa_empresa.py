import sqlite3

import pytest

from processamento import banco, busca_providers, pesquisa_empresa


class ProviderFalso(busca_providers.SearchProvider):
    """Provider de teste — nunca faz chamada de rede. Devolve resultados
    fixos para validar a orquestração isoladamente."""

    nome = "ProviderFalso"

    def __init__(self, resultados_por_consulta):
        self._resultados = resultados_por_consulta

    def disponivel(self) -> bool:
        return True

    def buscar(self, query, num_resultados=5):
        for chave, resultados in self._resultados.items():
            if chave in query:
                return resultados
        return []


@pytest.fixture
def conexao():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    banco.criar_tabelas(conn)
    banco.criar_tabelas_enriquecimento(conn)
    empresa_id, _ = banco.obter_ou_criar_empresa(
        conn,
        {"cnpj": "11444777000161", "razao_social": "Empresa Teste", "nome_fantasia": None,
         "cidade": "Guaíra", "estado": "SP", "status": None},
    )
    yield conn, empresa_id
    conn.close()


def test_sem_provider_real_devolve_sem_provider(conexao):
    conn, empresa_id = conexao
    resultado = pesquisa_empresa.pesquisar_empresa(
        conn, empresa_id, "Empresa Teste", "Guaíra", provider=busca_providers.FilaManualProvider()
    )
    assert resultado["status"] == "SEM_PROVIDER"
    total_pesquisas = conn.execute("SELECT COUNT(*) FROM historico_pesquisa").fetchone()[0]
    assert total_pesquisas == 0  # não registra pesquisa nenhuma sem provider real


def test_provider_real_grava_presenca_e_evidencia(conexao):
    conn, empresa_id = conexao
    provider = ProviderFalso(
        {
            "site oficial": [
                busca_providers.ResultadoBusca(titulo="Site oficial", url="https://empresateste.com.br"),
                busca_providers.ResultadoBusca(titulo="LinkedIn", url="https://linkedin.com/company/empresateste"),
            ],
            "ESG": [
                busca_providers.ResultadoBusca(
                    titulo="Empresa Teste investe em ESG",
                    url="https://noticias.com/empresateste-esg",
                    trecho="A empresa lançou programa de responsabilidade social.",
                ),
            ],
        }
    )
    resultado = pesquisa_empresa.pesquisar_empresa(conn, empresa_id, "Empresa Teste", "Guaíra", provider=provider)

    assert resultado["status"] == "OK"
    assert resultado["presenca_digital"] == 2
    assert resultado["evidencias"] == 1

    presencas = conn.execute("SELECT tipo, url, nivel_confianca FROM presenca_digital WHERE empresa_id = ?", (empresa_id,)).fetchall()
    tipos = {p["tipo"] for p in presencas}
    assert "site" in tipos
    assert "linkedin" in tipos
    assert all(p["nivel_confianca"] == "MEDIO" for p in presencas)

    evidencias = conn.execute("SELECT nivel_confianca FROM evidencias WHERE empresa_id = ?", (empresa_id,)).fetchall()
    assert len(evidencias) == 1
    assert evidencias[0]["nivel_confianca"] == "BAIXO"

    historico = conn.execute("SELECT status FROM historico_pesquisa WHERE empresa_id = ?", (empresa_id,)).fetchone()
    assert historico["status"] == "SUCESSO"


def test_evidencia_sem_termo_relevante_e_descartada(conexao):
    conn, empresa_id = conexao
    provider = ProviderFalso(
        {
            "ESG": [
                busca_providers.ResultadoBusca(
                    titulo="Empresa Teste vende produtos", url="https://loja.com/empresateste",
                    trecho="Confira nossa promoção de outubro.",
                ),
            ],
        }
    )
    resultado = pesquisa_empresa.pesquisar_empresa(conn, empresa_id, "Empresa Teste", "Guaíra", provider=provider)
    assert resultado["evidencias"] == 0


def test_classificar_url():
    assert pesquisa_empresa.classificar_url("https://www.linkedin.com/company/x") == "linkedin"
    assert pesquisa_empresa.classificar_url("https://instagram.com/x") == "instagram"
    assert pesquisa_empresa.classificar_url("https://empresa.com.br") == "site"


def test_extrair_contatos_do_texto_encontra_email_e_telefone():
    achados = pesquisa_empresa._extrair_contatos_do_texto(
        "Fale conosco: contato@empresateste.com.br ou (17) 3331-2000."
    )
    assert achados["emails"] == ["contato@empresateste.com.br"]
    assert achados["telefones"] == ["1733312000"]  # normalizado (só dígitos) por enriquecimento.normalizar_telefone


def test_extrair_contatos_do_texto_sem_padroes_devolve_listas_vazias():
    achados = pesquisa_empresa._extrair_contatos_do_texto("Nenhum contato aqui, só texto solto.")
    assert achados == {"emails": [], "telefones": []}


def test_extrair_pessoa_cargo_linkedin_reconhece_formato_padrao():
    achado = pesquisa_empresa._extrair_pessoa_cargo_linkedin(
        "Maria Silva - Gerente de Sustentabilidade - Empresa Teste | LinkedIn",
        "https://br.linkedin.com/in/mariasilva",
    )
    assert achado == ("Maria Silva", "Gerente de Sustentabilidade")


def test_extrair_pessoa_cargo_linkedin_ignora_url_fora_do_linkedin():
    achado = pesquisa_empresa._extrair_pessoa_cargo_linkedin(
        "Maria Silva - Gerente de Sustentabilidade", "https://empresateste.com.br/equipe",
    )
    assert achado is None


def test_extrair_pessoa_cargo_linkedin_ignora_titulo_sem_separador():
    achado = pesquisa_empresa._extrair_pessoa_cargo_linkedin(
        "Empresa Teste", "https://br.linkedin.com/in/empresateste",
    )
    assert achado is None


def test_pesquisar_empresa_grava_email_encontrado_no_texto(conexao):
    conn, empresa_id = conexao
    provider = ProviderFalso(
        {
            "site oficial": [
                busca_providers.ResultadoBusca(
                    titulo="Fale conosco", url="https://empresateste.com.br/contato",
                    trecho="Escreva para contato@empresateste.com.br ou ligue (17) 3331-2000.",
                ),
            ],
        }
    )
    resultado = pesquisa_empresa.pesquisar_empresa(conn, empresa_id, "Empresa Teste", "Guaíra", provider=provider)
    assert resultado["contatos"] >= 1

    contatos = conn.execute(
        "SELECT tipo_contato, valor, nivel_confianca FROM contatos WHERE empresa_id = ?", (empresa_id,)
    ).fetchall()
    tipos = {c["tipo_contato"] for c in contatos}
    assert "EMAIL_CONTATO" in tipos
    assert "TELEFONE_INSTITUCIONAL" in tipos
    assert all(c["nivel_confianca"] in ("MEDIO", "BAIXO") for c in contatos)  # nunca ALTO em busca automática


def test_texto_menciona_empresa_aceita_quando_nome_aparece():
    assert pesquisa_empresa._texto_menciona_empresa(
        "Aguetoni Transportes Ltda.", "A Aguetoni Transportes anunciou um novo projeto social."
    )


def test_texto_menciona_empresa_rejeita_conteudo_generico_sem_o_nome():
    assert not pesquisa_empresa._texto_menciona_empresa(
        "Aguetoni Transportes Ltda.", "Manual de Patrocínio Cultural e ESG: Lei Rouanet para empresas."
    )


def test_evidencia_generica_sem_mencionar_empresa_e_descartada(conexao):
    conn, empresa_id = conexao
    provider = ProviderFalso(
        {
            "ESG": [
                busca_providers.ResultadoBusca(
                    titulo="Manual de patrocínio cultural e ESG",
                    url="https://blog-generico.com/manual-esg",
                    trecho="Guia geral sobre responsabilidade social, sem citar nenhuma organização específica.",
                ),
            ],
        }
    )
    resultado = pesquisa_empresa.pesquisar_empresa(conn, empresa_id, "Empresa Teste", "Guaíra", provider=provider)
    assert resultado["evidencias"] == 0


def test_pesquisar_empresa_registra_erro_do_provider_sem_quebrar(conexao):
    conn, empresa_id = conexao

    class ProviderComErro(busca_providers.SearchProvider):
        nome = "ProviderComErro"

        def disponivel(self):
            return True

        def buscar(self, query, num_resultados=5):
            self.ultimo_erro = "A chave da SerpApi foi rejeitada (simulado)."
            return []

    resultado = pesquisa_empresa.pesquisar_empresa(
        conn, empresa_id, "Empresa Teste", "Guaíra", provider=ProviderComErro()
    )
    assert resultado["status"] == "OK"
    assert len(resultado["erros"]) > 0
    historico = conn.execute("SELECT status FROM historico_pesquisa WHERE empresa_id = ?", (empresa_id,)).fetchone()
    assert historico["status"] == "FALHA"
