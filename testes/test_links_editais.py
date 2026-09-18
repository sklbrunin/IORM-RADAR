import sqlite3

import pytest

from processamento import editais, links_editais as le

HTML_EDITAL = """<html><head><title>Edital de Fomento à Dança nº 39 - Prefeitura</title></head><body>
<h1>Edital de Fomento à Dança</h1><p>Regras e cronograma.</p>
<a href="/cultura/editais/fomento-danca-39/inscricao">Inscreva-se aqui</a>
<a href="#topo">Voltar</a><a href="mailto:x@y.com">Contato</a></body></html>"""


def buscador_fixo(status=200, url_final=None, html=HTML_EDITAL):
    def _b(url):
        return status, url_final or url, html
    return _b


# ---------------------------------------------------------- portal genérico
@pytest.mark.parametrize("url", [
    "https://www.prefeitura.sp.gov.br", "https://www.prefeitura.sp.gov.br/", "https://site.org/editais",
    "https://site.org/editais/", "https://site.org/noticias", "https://site.org/index.html", None, "ftp://x/y",
])
def test_urls_genericas(url):
    assert le.eh_portal_generico(url)[0] is True


@pytest.mark.parametrize("url", [
    "https://site.org/cultura/editais/fomento-danca-39", "https://site.org/editais?id=39",
    "https://site.org/edital-39-2026",
])
def test_urls_especificas(url):
    assert le.eh_portal_generico(url)[0] is False


# ---------------------------------------------------------- inscrição
def test_url_de_formulario_e_inscricao():
    assert le.classificar_url_inscricao("https://forms.gle/abc123") is True


def test_url_com_inscricao_no_caminho_e_inscricao():
    assert le.classificar_url_inscricao("https://site.org/edital-39/inscricao") is True


def test_portal_generico_nunca_e_inscricao():
    assert le.classificar_url_inscricao("https://site.org/inscricoes") is False  # lista genérica? só 1 segmento
    assert le.classificar_url_inscricao("https://site.org/") is False


def test_pagina_de_edital_comum_nao_e_inscricao():
    assert le.classificar_url_inscricao("https://site.org/cultura/editais/fomento-danca-39") is False


def test_extrai_link_de_inscricao_da_pagina():
    url = le.extrair_link_inscricao(HTML_EDITAL, "https://site.org/cultura/editais/fomento-danca-39")
    assert url == "https://site.org/cultura/editais/fomento-danca-39/inscricao"


def test_ignora_ancora_mailto_e_link_para_a_propria_pagina():
    html = '<a href="#x">Inscreva-se</a><a href="mailto:a@b.c">Inscrições</a><a href="/e/39">Inscreva-se</a>'
    assert le.extrair_link_inscricao(html, "https://site.org/e/39") is None


def test_ignora_link_de_inscricao_que_aponta_para_portal_generico():
    html = '<a href="https://site.org/">Inscreva-se</a>'
    assert le.extrair_link_inscricao(html, "https://site.org/e/39") is None


# ---------------------------------------------------------- correspondência
def test_correspondencia_alta_quando_titulo_aparece():
    assert le.correspondencia_titulo("Edital de Fomento à Dança 39", "Edital de Fomento à Dança nº 39", "") == 1.0


def test_correspondencia_baixa_quando_pagina_e_outra_coisa():
    assert le.correspondencia_titulo("Edital de Fomento à Dança", "Prefeitura - Notícias", "Vacinação") < 0.5


def test_correspondencia_zero_sem_palavras_significativas():
    assert le.correspondencia_titulo("Edital de", "x", "y") == 0.0


# ---------------------------------------------------------- verificar_link
def test_verificacao_pagina_especifica_confirmada():
    r = le.verificar_link("https://site.org/cultura/editais/fomento-danca-39", "Edital de Fomento à Dança 39", buscador_fixo())
    assert r["status"] == le.STATUS_ESPECIFICA and r["http_status"] == 200
    assert r["url_inscricao_encontrada"].endswith("/inscricao")


def test_verificacao_detecta_portal_generico_mesmo_respondendo_200():
    r = le.verificar_link("https://site.org/editais", "Edital de Fomento à Dança 39", buscador_fixo())
    assert r["status"] == le.STATUS_GENERICO


def test_verificacao_redirect_para_raiz_vira_generico():
    r = le.verificar_link("https://site.org/cultura/edital-39", "Edital de Fomento à Dança 39",
                          buscador_fixo(url_final="https://site.org/"))
    assert r["status"] == le.STATUS_GENERICO


def test_verificacao_responde_mas_titulo_nao_bate():
    r = le.verificar_link("https://site.org/cultura/outra-pagina", "Edital de Fomento à Dança 39",
                          buscador_fixo(html="<html><title>Vacinação</title><body>Campanha de vacinação</body></html>"))
    assert r["status"] == le.STATUS_SEM_CORRESPONDENCIA


def test_verificacao_http_404():
    r = le.verificar_link("https://site.org/cultura/edital-39", "Edital 39", buscador_fixo(status=404))
    assert r["status"] == le.STATUS_NAO_RESPONDE and r["http_status"] == 404


def test_verificacao_excecao_de_rede_nao_quebra():
    def falha(url):
        raise ConnectionError("sem rede")

    r = le.verificar_link("https://site.org/cultura/edital-39", "Edital 39", falha)
    assert r["status"] == le.STATUS_NAO_RESPONDE and "ConnectionError" in r["motivo"]


def test_verificacao_sem_url():
    assert le.verificar_link(None, "Edital")["status"] == le.STATUS_NAO_RESPONDE


def test_detecta_indicio_de_inscricoes_encerradas():
    html = "<html><title>Edital de Fomento à Dança 39</title><body>Inscrições encerradas em 10/03.</body></html>"
    r = le.verificar_link("https://site.org/cultura/edital-39", "Edital de Fomento à Dança 39", buscador_fixo(html=html))
    assert r["indicio_encerrado"] is True


def test_verificar_inscricao():
    ok = le.verificar_inscricao("https://forms.gle/abc", buscador_fixo())
    assert ok["ok"] is True
    assert le.verificar_inscricao(None)["motivo"] == "Link direto de inscrição não localizado"
    assert le.verificar_inscricao("https://site.org/")["ok"] is False
    assert le.verificar_inscricao("https://forms.gle/abc", buscador_fixo(status=500))["ok"] is False


# ---------------------------------------------------------- persistência
@pytest.fixture
def conexao():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    editais.criar_tabelas(conn)
    yield conn
    conn.close()


def test_verificar_e_registrar_grava_status_e_link_de_inscricao_encontrado(conexao):
    eid = editais.criar_edital(conexao, {"titulo": "Edital de Fomento à Dança 39", "fonte": "teste",
                                          "url": "https://site.org/cultura/editais/fomento-danca-39"})
    editais.verificar_e_registrar(conexao, eid, buscador_fixo())
    e = conexao.execute("SELECT * FROM editais WHERE id = ?", (eid,)).fetchone()
    assert e["link_status"] == le.STATUS_ESPECIFICA and e["link_http_status"] == 200 and e["link_verificado_em"]
    assert e["url_inscricao"].endswith("/inscricao") and e["inscricao_origem"] == "EXTRAIDO_DA_PAGINA_DO_EDITAL"
    assert e["inscricao_verificada"] == 1


def test_link_de_portal_generico_nunca_vira_url_de_inscricao(conexao):
    eid = editais.criar_edital(conexao, {"titulo": "Edital X", "fonte": "teste", "url": "https://site.org/editais"})
    editais.verificar_e_registrar(conexao, eid, buscador_fixo(html="<html><body>lista de editais</body></html>"))
    e = conexao.execute("SELECT * FROM editais WHERE id = ?", (eid,)).fetchone()
    assert e["link_status"] == le.STATUS_GENERICO
    assert e["url_inscricao"] is None and e["inscricao_verificada"] == 0


def test_indicio_de_encerrado_atualiza_situacao(conexao):
    eid = editais.criar_edital(conexao, {"titulo": "Edital de Fomento à Dança 39", "fonte": "teste",
                                          "url": "https://site.org/cultura/edital-39"})
    html = "<html><title>Edital de Fomento à Dança 39</title><body>Edital encerrado.</body></html>"
    editais.verificar_e_registrar(conexao, eid, buscador_fixo(html=html))
    assert conexao.execute("SELECT situacao_inscricao FROM editais WHERE id = ?", (eid,)).fetchone()[0] == "ENCERRADO"


def test_url_inscricao_cadastrada_e_preservada_e_verificada(conexao):
    eid = editais.criar_edital(conexao, {"titulo": "Edital de Fomento à Dança 39", "fonte": "teste",
                                          "url": "https://site.org/cultura/edital-39", "url_inscricao": "https://forms.gle/xyz"})
    editais.verificar_e_registrar(conexao, eid, buscador_fixo(html="<html><title>Edital de Fomento à Dança 39</title></html>"))
    e = conexao.execute("SELECT * FROM editais WHERE id = ?", (eid,)).fetchone()
    assert e["url_inscricao"] == "https://forms.gle/xyz" and e["inscricao_verificada"] == 1


def test_novo_edital_nasce_nao_verificado(conexao):
    eid = editais.criar_edital(conexao, {"titulo": "Edital Y", "fonte": "teste"})
    e = conexao.execute("SELECT * FROM editais WHERE id = ?", (eid,)).fetchone()
    assert e["link_status"] == "NAO_VERIFICADO" and e["url_inscricao"] is None
