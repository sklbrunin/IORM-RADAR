import sqlite3

import pytest

from processamento import banco, busca_providers, contact_providers as cp

RESPOSTA_RECEITA = {
    "razao_social": "AGUETONI TRANSPORTES LTDA", "nome_fantasia": "AGUETONI LOG",
    "descricao_situacao_cadastral": "ATIVA", "cnae_fiscal": 4930202,
    "cnae_fiscal_descricao": "Transporte rodoviário de carga", "ddd_telefone_1": "1791664022",
    "ddd_telefone_2": "", "email": "financeiro@aguetoni.com.br",
    "qsa": [
        {"nome_socio": "ALUIZIO SERAFIM AGUETONI", "qualificacao_socio": "Administrador", "cnpj_cpf_do_socio": "***783468**",
         "faixa_etaria": "Entre 61 a 70 anos"},
        {"nome_socio": "", "qualificacao_socio": "Sócio"},
    ],
}


@pytest.fixture
def conexao():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    banco.criar_tabelas(conn)
    banco.criar_tabelas_enriquecimento(conn)
    banco.obter_ou_criar_empresa(
        conn, {"cnpj": "65744138000140", "razao_social": "Aguetoni Transportes Ltda.", "nome_fantasia": None,
               "cidade": "Guaíra", "estado": "SP", "status": None})
    yield conn
    conn.close()


def empresa(conexao):
    return {"id": conexao.execute("SELECT id FROM empresas").fetchone()[0], "razao_social": "Aguetoni Transportes Ltda.",
            "cnpj": "65744138000140", "cidade": "Guaíra", "estado": "SP"}


def receita(status=200, corpo=RESPOSTA_RECEITA):
    return cp.ReceitaFederalContactProvider(buscador=lambda url: (status, corpo), pausa=0)


# ------------------------------------------------------------ Receita Federal
def test_receita_devolve_situacao_fantasia_telefone_email_e_socios(conexao):
    r = receita().enriquecer(empresa(conexao))
    assert r.atualizacoes_empresa == {"status": "Ativa", "nome_fantasia": "Aguetoni Log"}
    tipos = [c.tipo_contato for c in r.contatos]
    assert tipos.count("PESSOA_CARGO") == 1  # sócio sem nome é ignorado
    assert "TELEFONE_INSTITUCIONAL" in tipos and "EMAIL_INSTITUCIONAL" in tipos
    assert r.chamadas_api == 1 and r.erros == []


def test_receita_nao_guarda_cpf_nem_faixa_etaria(conexao):
    r = receita().enriquecer(empresa(conexao))
    pessoa = next(c for c in r.contatos if c.tipo_contato == "PESSOA_CARGO")
    texto = " ".join(str(v) for v in vars(pessoa).values())
    assert "783468" not in texto and "61 a 70" not in texto
    assert pessoa.cargo.startswith("Administrador") and "Receita Federal" in pessoa.cargo


def test_receita_email_generico_recebe_area_e_continua_institucional(conexao):
    r = receita().enriquecer(empresa(conexao))
    email = next(c for c in r.contatos if c.tipo_contato == "EMAIL_INSTITUCIONAL")
    assert email.departamento == "Financeiro" and email.nome is None


def test_receita_sem_cnpj_e_ignorada(conexao):
    r = receita().enriquecer({**empresa(conexao), "cnpj": None})
    assert r.ignorado_motivo and r.chamadas_api == 0


@pytest.mark.parametrize("status,trecho", [(404, "não encontrado"), (429, "limite"), (500, "inesperada")])
def test_receita_erros_de_api_sao_amigaveis(conexao, status, trecho):
    r = receita(status, None).enriquecer(empresa(conexao))
    assert trecho in r.erros[0] and r.contatos == []


def test_receita_falha_de_rede_nao_quebra(conexao):
    def falha(url):
        raise ConnectionError("x")

    r = cp.ReceitaFederalContactProvider(buscador=falha, pausa=0).enriquecer(empresa(conexao))
    assert "falha de rede" in r.erros[0]


# ------------------------------------------------------------ persistência
def test_persistir_grava_contatos_com_fonte_url_e_data(conexao):
    e = empresa(conexao)
    r = receita().enriquecer(e)
    contagem = cp.persistir(conexao, e["id"], r)
    assert contagem["contatos"] == 3 and contagem["evidencias"] == 1
    pessoa = conexao.execute("SELECT * FROM contatos WHERE tipo_contato='PESSOA_CARGO'").fetchone()
    assert pessoa["nome"] == "Aluizio Serafim Aguetoni" and pessoa["nivel_confianca"] == "ALTO"
    assert "Receita Federal" in pessoa["fonte"] and pessoa["url_fonte"].startswith("https://brasilapi.com.br") and pessoa["coletado_em"]
    email = conexao.execute("SELECT * FROM contatos WHERE tipo_contato='EMAIL_INSTITUCIONAL'").fetchone()
    assert email["nome"] is None and email["departamento"] == "Financeiro"  # institucional, nunca "pessoa"


def test_persistir_atualiza_cadastro_so_quando_vazio(conexao):
    e = empresa(conexao)
    conexao.execute("UPDATE empresas SET nome_fantasia = 'Nome Definido Pela Equipe' WHERE id = ?", (e["id"],))
    cp.persistir(conexao, e["id"], receita().enriquecer(e))
    linha = conexao.execute("SELECT status, nome_fantasia FROM empresas").fetchone()
    assert linha["status"] == "Ativa" and linha["nome_fantasia"] == "Nome Definido Pela Equipe"


def test_persistir_duas_vezes_nao_duplica(conexao):
    e = empresa(conexao)
    cp.persistir(conexao, e["id"], receita().enriquecer(e))
    segunda = cp.persistir(conexao, e["id"], receita().enriquecer(e))
    assert segunda["contatos"] == 0 and segunda["evidencias"] == 0
    assert conexao.execute("SELECT COUNT(*) FROM contatos").fetchone()[0] == 3


def test_persistir_nunca_aceita_nivel_alto_fora_de_registro_oficial(conexao):
    e = empresa(conexao)
    r = cp.ResultadoProvider(provider="X", contatos=[cp.ContatoEncontrado(
        tipo_contato="EMAIL_CONTATO", valor="contato@x.com.br", fonte="Blog qualquer", url_fonte="http://x", nivel_confianca="ALTO")])
    cp.persistir(conexao, e["id"], r)
    assert conexao.execute("SELECT nivel_confianca FROM contatos").fetchone()[0] == "MEDIO"


def test_persistir_descarta_pessoa_sem_cargo_e_email_invalido(conexao):
    e = empresa(conexao)
    r = cp.ResultadoProvider(provider="X", contatos=[
        cp.ContatoEncontrado(tipo_contato="PESSOA_CARGO", valor="http://p", nome="Fulano", cargo=None, fonte="f", url_fonte=None),
        cp.ContatoEncontrado(tipo_contato="EMAIL_CONTATO", valor="isso-nao-e-email", fonte="f", url_fonte=None),
    ])
    assert cp.persistir(conexao, e["id"], r)["contatos"] == 0


# ------------------------------------------------------------ Hunter (resposta simulada)
CORPO_HUNTER = {"data": {"emails": [
    {"value": "maria.silva@aguetoni.com.br", "type": "personal", "confidence": 92, "first_name": "Maria", "last_name": "Silva",
     "position": "Gerente de Sustentabilidade", "department": "management", "sources": [{"uri": "https://aguetoni.com.br/equipe"}]},
    {"value": "contato@aguetoni.com.br", "type": "generic", "confidence": 95, "sources": []},
    {"value": "joao.souza@aguetoni.com.br", "type": "personal", "confidence": 60, "first_name": "João", "last_name": "Souza",
     "position": None, "sources": []},
]}}


def test_hunter_sem_chave_fica_indisponivel(monkeypatch):
    monkeypatch.delenv("HUNTER_API_KEY", raising=False)
    assert cp.HunterContactProvider().disponivel() is False


def test_hunter_pessoa_com_cargo_vira_pessoa_e_generico_fica_institucional(conexao, monkeypatch):
    monkeypatch.setenv("HUNTER_API_KEY", "chave-de-teste")
    prov = cp.HunterContactProvider(buscador=lambda url, params: CORPO_HUNTER)
    r = prov.enriquecer({**empresa(conexao), "site": "https://www.aguetoni.com.br/"})
    por_valor = {c.valor: c for c in r.contatos}
    pessoa = por_valor["maria.silva@aguetoni.com.br"]
    assert pessoa.tipo_contato == "PESSOA_CARGO" and pessoa.departamento == "Sustentabilidade" and pessoa.email_profissional
    assert por_valor["contato@aguetoni.com.br"].tipo_contato == "EMAIL_CONTATO"
    # pessoal SEM cargo não é promovido a "responsável"
    assert por_valor["joao.souza@aguetoni.com.br"].tipo_contato == "EMAIL_CONTATO"
    assert r.chamadas_api == 1


def test_hunter_sem_site_e_ignorado(conexao, monkeypatch):
    monkeypatch.setenv("HUNTER_API_KEY", "chave-de-teste")
    r = cp.HunterContactProvider(buscador=lambda u, p: CORPO_HUNTER).enriquecer(empresa(conexao))
    assert r.ignorado_motivo and r.chamadas_api == 0


def test_hunter_erro_da_api_e_reportado(conexao, monkeypatch):
    monkeypatch.setenv("HUNTER_API_KEY", "chave-de-teste")
    prov = cp.HunterContactProvider(buscador=lambda u, p: {"errors": [{"details": "Plano não inclui API"}]})
    r = prov.enriquecer({**empresa(conexao), "site": "https://aguetoni.com.br"})
    assert "Plano não inclui API" in r.erros[0]


# ------------------------------------------------------------ Web search (modo sem provider)
def test_web_search_sem_chave_e_ignorado(conexao, monkeypatch):
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    r = cp.WebSearchContactProvider(conexao, busca_providers.FilaManualProvider()).enriquecer(empresa(conexao))
    assert r.ignorado_motivo and r.chamadas_api == 0
