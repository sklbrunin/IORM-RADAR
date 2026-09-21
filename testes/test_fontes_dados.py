from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from processamento import editais, fontes_dados

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Portal</title>
<item><title>Edital de Fomento à Cultura 2026</title><link>https://portal.exemplo/edital-fomento</link>
<description>&lt;p&gt;Inscrições para projetos culturais&lt;/p&gt;</description><pubDate>Mon, 14 Sep 2026 10:00:00 GMT</pubDate></item>
<item><title>Prefeito inaugura praça</title><link>https://portal.exemplo/praca</link><description>Notícia local</description></item>
<item><title>Chamada pública para OSCs</title><link>https://portal.exemplo/chamada</link><description>Seleção de organizações</description></item>
</channel></rss>"""

ATOM = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>X</title>
<entry><title>Prêmio Cultura Viva</title><link href="https://atom.exemplo/premio"/><summary>Prêmio para iniciativas</summary>
<updated>2026-09-10T12:00:00Z</updated></entry></feed>"""

URL = "https://portal.exemplo/feed.xml"


@pytest.fixture
def conexao():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    editais.criar_tabelas(conn)
    fontes_dados.criar_tabelas(conn)
    yield conn
    conn.close()


def _fetcher(texto, status=200, tipo="application/xml"):
    return lambda url: (status, tipo, texto)


def _nova(conexao, **extra):
    return fontes_dados.cadastrar(conexao, {"nome": "Portal de Editais XYZ", "tipo": "Editais", "url": URL, **extra})


# ------------------------------------------------------------------ cadastro / edição / ativação / persistência
def test_cadastrar_persiste_todos_os_campos(conexao):
    fid = _nova(conexao, categoria="Cultura", descricao="Portal municipal", frequencia="SEMANAL", observacoes="indicado pela equipe")
    f = fontes_dados.obter(conexao, fid)
    assert (f["nome"], f["tipo"], f["url"], f["categoria"], f["frequencia"], f["ativo"]) == (
        "Portal de Editais XYZ", "Editais", URL, "Cultura", "SEMANAL", 1)
    assert f["metodo_acesso"] == fontes_dados.ACESSO_NAO_AVALIADO and f["proxima_consulta"] and f["criado_em"]
    # persistiu de fato: outra conexão ao mesmo banco enxergaria a linha (aqui: nova leitura)
    assert [r["nome"] for r in fontes_dados.listar(conexao)] == ["Portal de Editais XYZ"]


def test_cadastro_invalido(conexao):
    with pytest.raises(ValueError, match="nome"):
        fontes_dados.cadastrar(conexao, {"nome": " ", "tipo": "Editais", "url": URL})
    with pytest.raises(ValueError, match="URL"):
        fontes_dados.cadastrar(conexao, {"nome": "X", "tipo": "Editais", "url": "portal sem esquema"})
    with pytest.raises(ValueError, match="Tipo"):
        fontes_dados.cadastrar(conexao, {"nome": "X", "tipo": "Fofoca", "url": URL})
    with pytest.raises(ValueError, match="Frequência"):
        fontes_dados.cadastrar(conexao, {"nome": "X", "tipo": "Editais", "url": URL, "frequencia": "HORARIA"})


def test_url_duplicada_e_recusada(conexao):
    _nova(conexao)
    with pytest.raises(ValueError, match="Já existe"):
        _nova(conexao, nome="Outro nome")


def test_editar_atualiza_e_url_nova_invalida_a_avaliacao_anterior(conexao):
    fid = _nova(conexao)
    fontes_dados.registrar_avaliacao(conexao, fid, {"metodo_acesso": fontes_dados.ACESSO_FEED, "detalhe": "ok"})
    fontes_dados.atualizar(conexao, fid, {"nome": "Portal XYZ (novo nome)", "frequencia": "DIARIA"})
    f = fontes_dados.obter(conexao, fid)
    assert f["nome"] == "Portal XYZ (novo nome)" and f["frequencia"] == "DIARIA" and f["metodo_acesso"] == "FEED"
    fontes_dados.atualizar(conexao, fid, {"url": "https://outro.exemplo/rss"})
    assert fontes_dados.obter(conexao, fid)["metodo_acesso"] == fontes_dados.ACESSO_NAO_AVALIADO


def test_editar_ignora_campos_que_nao_sao_editaveis_e_valida(conexao):
    fid = _nova(conexao)
    fontes_dados.atualizar(conexao, fid, {"ativo": 0, "criado_em": "1999"})
    f = fontes_dados.obter(conexao, fid)
    assert f["ativo"] == 1 and f["criado_em"] != "1999"
    with pytest.raises(ValueError):
        fontes_dados.atualizar(conexao, fid, {"nome": ""})


def test_ativar_e_desativar(conexao):
    fid = _nova(conexao)
    fontes_dados.definir_ativo(conexao, fid, False)
    assert fontes_dados.obter(conexao, fid)["ativo"] == 0
    assert fontes_dados.listar(conexao, somente_ativas=True) == []
    fontes_dados.definir_ativo(conexao, fid, True)
    assert len(fontes_dados.listar(conexao, somente_ativas=True)) == 1


def test_fontes_devidas_respeitam_ativo_frequencia_e_data(conexao):
    diaria = _nova(conexao, frequencia="DIARIA")
    fontes_dados.cadastrar(conexao, {"nome": "Manual", "tipo": "Outros", "url": "https://m.exemplo", "frequencia": "MANUAL"})
    amanha = datetime.now(timezone.utc) + timedelta(days=2)
    assert [f["id"] for f in fontes_dados.devidas(conexao, agora=amanha)] == [diaria]
    assert fontes_dados.devidas(conexao) == []  # recém-cadastrada: ainda não venceu
    fontes_dados.definir_ativo(conexao, diaria, False)
    assert fontes_dados.devidas(conexao, agora=amanha) == []


# ------------------------------------------------------------------ avaliação de acesso (nunca assume)
def test_avaliar_acesso_detecta_feed_json_html_e_erro():
    assert fontes_dados.avaliar_acesso(URL, _fetcher(RSS))["metodo_acesso"] == "FEED"
    assert fontes_dados.avaliar_acesso(URL, _fetcher(ATOM))["metodo_acesso"] == "FEED"
    assert fontes_dados.avaliar_acesso(URL, _fetcher('{"itens": []}', tipo="application/json"))["metodo_acesso"] == "API_JSON"
    assert fontes_dados.avaliar_acesso(URL, _fetcher("<html><body>Olá</body></html>", tipo="text/html"))["metodo_acesso"] == "PAGINA_PUBLICA"
    assert fontes_dados.avaliar_acesso(URL, _fetcher("", status=404))["metodo_acesso"] == "INACESSIVEL"

    def quebrado(url):
        raise TimeoutError("sem resposta")

    assert fontes_dados.avaliar_acesso(URL, quebrado)["metodo_acesso"] == "INACESSIVEL"


# ------------------------------------------------------------------ coleta por feed → editais
def test_interpretar_rss_e_atom():
    itens = fontes_dados.interpretar_feed(RSS)
    assert len(itens) == 3 and itens[0]["descricao"] == "Inscrições para projetos culturais"
    assert itens[0]["data_publicacao"] == "2026-09-14"
    atom = fontes_dados.interpretar_feed(ATOM)
    assert atom[0]["url"] == "https://atom.exemplo/premio" and atom[0]["data_publicacao"] == "2026-09-10"


def test_feed_com_entidades_xml_e_recusado():
    malicioso = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><rss><channel/></rss>'
    with pytest.raises(ValueError, match="entidades"):
        fontes_dados.interpretar_feed(malicioso)


def test_coletar_feed_cadastra_so_o_relevante_como_nao_confirmado_e_sem_duplicar(conexao):
    fid = _nova(conexao)
    r = fontes_dados.coletar_fonte(conexao, fid, _fetcher(RSS))
    assert (r["encontrados"], r["relevantes"], r["novos"]) == (3, 2, 2)
    linhas = conexao.execute("SELECT * FROM editais ORDER BY id").fetchall()
    assert {l["titulo"] for l in linhas} == {"Edital de Fomento à Cultura 2026", "Chamada pública para OSCs"}
    for l in linhas:
        assert l["origem_descoberta"] == "FONTE_CADASTRADA" and l["situacao_inscricao"] == "NAO_CONFIRMADO"
        assert "Portal de Editais XYZ" in l["fonte"] and URL in l["fonte"]
        assert l["url_inscricao"] is None  # nunca inventa link de inscrição
        assert editais.situacao_efetiva(l)[0] == "NAO_CONFIRMADO"  # e nunca vira "aberto" sozinho
    f = fontes_dados.obter(conexao, fid)
    assert f["metodo_acesso"] == "FEED" and f["ultima_consulta"] and f["ultimo_resultado"]
    r2 = fontes_dados.coletar_fonte(conexao, fid, _fetcher(RSS))
    assert (r2["novos"], r2["ja_existentes"]) == (0, 2)
    assert conexao.execute("SELECT COUNT(*) FROM editais").fetchone()[0] == 2


def test_fonte_html_so_e_registrada_sem_coletar(conexao):
    fid = _nova(conexao)
    r = fontes_dados.coletar_fonte(conexao, fid, _fetcher("<html>portal</html>", tipo="text/html"))
    assert r["novos"] == 0 and "não coletada automaticamente" in r["mensagem"].lower()
    assert conexao.execute("SELECT COUNT(*) FROM editais").fetchone()[0] == 0
    assert fontes_dados.obter(conexao, fid)["metodo_acesso"] == "PAGINA_PUBLICA"


def test_feed_que_nao_e_do_tipo_editais_nao_alimenta_o_radar(conexao):
    fid = fontes_dados.cadastrar(conexao, {"nome": "Notícias", "tipo": "Notícias", "url": URL})
    r = fontes_dados.coletar_fonte(conexao, fid, _fetcher(RSS))
    assert r["novos"] == 0 and conexao.execute("SELECT COUNT(*) FROM editais").fetchone()[0] == 0


def test_feed_quebrado_nao_derruba_e_fonte_inacessivel_e_registrada(conexao):
    fid = _nova(conexao)
    r = fontes_dados.coletar_fonte(conexao, fid, _fetcher("<rss><channel><item>", tipo="application/xml"))
    assert r["novos"] == 0 and "ilegível" in r["mensagem"]

    def fora(url):
        raise ConnectionError("sem rede")

    r = fontes_dados.coletar_fonte(conexao, fid, fora)
    assert fontes_dados.obter(conexao, fid)["metodo_acesso"] == "INACESSIVEL" and r["novos"] == 0


def test_coletar_devidas_isola_falhas(conexao):
    a = _nova(conexao, frequencia="DIARIA")
    b = fontes_dados.cadastrar(conexao, {"nome": "B", "tipo": "Editais", "url": "https://b.exemplo/rss", "frequencia": "DIARIA"})
    conexao.execute("UPDATE fontes_dados SET proxima_consulta = '2000-01-01T00:00:00+00:00'")
    conexao.commit()

    def fetcher(url):
        if "b.exemplo" in url:
            raise RuntimeError("falhou")
        return 200, "application/xml", RSS

    resultados = fontes_dados.coletar_devidas(conexao, fetcher)
    assert len(resultados) == 2
    assert sum(r.get("novos", 0) for r in resultados) == 2
    assert fontes_dados.obter(conexao, a)["ultima_consulta"]

@pytest.mark.parametrize("titulo,esperado", [
    ("Edital de Fomento à Cultura 2026", True), ("Prefeitura abre inscrições para oficinas", True),
    ("Chamada Pública para OSCs", True), ("Chamamento público nº 5/2026", True),
    ("Seleção brasileira vence amistoso", False), ("Prêmio Nobel de Física é anunciado", False),
    ("Governo edita decreto sobre trânsito", False), ("Notícia qualquer sobre o tempo", False),
])
def test_filtro_de_relevancia_nao_deixa_passar_noticia_comum(titulo, esperado):
    assert fontes_dados.parece_oportunidade({"titulo": titulo, "descricao": None}) is esperado
