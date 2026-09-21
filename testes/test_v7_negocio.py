"""Testes da rodada v7: Linha Cruzada x Radar (contadores), situação de editais, remoção do Pipeline,
formatação brasileira. (Fontes, incentivos e documentos têm arquivos próprios.)"""
from __future__ import annotations

import sqlite3
from datetime import date

import pandas as pd
import pytest

from processamento import banco, crm, editais, formatacao, metricas, relacionamento

HOJE = date(2026, 9, 18)


# ------------------------------------------------------------------ Linha Cruzada x prospects
class _Conexao(sqlite3.Connection):
    pass


@pytest.fixture
def base():
    conn = sqlite3.connect(":memory:", factory=_Conexao)
    conn.row_factory = sqlite3.Row
    banco.criar_tabelas(conn)
    banco.criar_tabelas_enriquecimento(conn)
    crm.criar_tabelas(conn)

    def empresa(cnpj, nome, cidade="Guaíra"):
        return banco.obter_ou_criar_empresa(
            conn, {"cnpj": cnpj, "razao_social": nome, "nome_fantasia": None, "cidade": cidade, "estado": "SP", "status": None}
        )[0]

    def incentivo(eid, projeto, url):
        banco.inserir_ou_atualizar_incentivo(conn, {
            "empresa_id": eid, "fonte": "SALIC", "tipo_incentivo": "Lei Rouanet", "projeto": projeto, "ano": 2020,
            "valor": 1000.0, "uf": "SP", "cidade": "Guaíra", "url_fonte": url, "coletado_em": "2026-01-01",
            "nivel_confianca": "ALTO"})

    a = empresa("11444777000161", "Empresa Parceira")
    b = empresa("11222333000181", "Empresa Prospect A")
    c = empresa("45997418000153", "Empresa Prospect B", "Ipuã")
    incentivo(a, "Usina da Dança 2019", "https://x/1")
    incentivo(b, "Outro Projeto", "https://x/2")
    conn.commit()
    relacionamento.sincronizar(conn)
    conn.ids = {"parceira": a, "prospect_a": b, "prospect_b": c}
    yield conn
    conn.close()


def _df(conn):
    df = metricas.carregar_empresas(conn)
    df["pesquisado"] = df["id"] == conn.ids["prospect_a"]  # só a Prospect A já foi pesquisada
    return df


def test_empresa_relacionada_fica_fora_dos_prospects_e_na_linha_cruzada(base):
    df = _df(base)
    parceira = df[df["id"] == base.ids["parceira"]].iloc[0]
    assert bool(parceira["linha_cruzada"]) and not bool(parceira["eh_prospect"])
    assert base.ids["parceira"] not in set(df[df["eh_prospect"]]["id"])
    assert base.ids["parceira"] in set(df[df["linha_cruzada"]]["id"])


def test_empresa_nao_relacionada_continua_no_radar(base):
    df = _df(base)
    prospects = set(df[df["eh_prospect"]]["id"])
    assert {base.ids["prospect_a"], base.ids["prospect_b"]} <= prospects
    assert not df[df["id"].isin([base.ids["prospect_a"], base.ids["prospect_b"]])]["linha_cruzada"].any()


def test_contadores_corretos_e_nada_e_apagado(base):
    total_antes = base.execute("SELECT COUNT(*) FROM empresas").fetchone()[0]
    c = metricas.contadores_empresas(_df(base))
    assert c == {"total": 3, "prospects": 2, "linha_cruzada": 1, "reabertas": 0, "pesquisadas": 1, "nao_pesquisadas": 1}
    assert c["prospects"] + c["linha_cruzada"] == c["total"]
    assert base.execute("SELECT COUNT(*) FROM empresas").fetchone()[0] == total_antes  # a classificação não apaga registro


def test_nenhuma_empresa_e_prospect_e_relacionada_ao_mesmo_tempo_sem_justificativa(base):
    df = _df(base)
    assert not (df["eh_prospect"] & df["linha_cruzada"] & ~df["reabrir_prospeccao"]).any()


def test_prospeccao_reaberta_com_justificativa_conta_nos_dois_e_e_explicada(base):
    relacionamento.reabrir_prospeccao(base, base.ids["parceira"], True, "Nova campanha de ampliação de apoio")
    c = metricas.contadores_empresas(_df(base))
    assert c["reabertas"] == 1 and c["prospects"] == 3 and c["linha_cruzada"] == 1
    assert c["total"] == c["prospects"] + c["linha_cruzada"] - c["reabertas"]


def test_contadores_com_base_vazia():
    assert metricas.contadores_empresas(pd.DataFrame())["total"] == 0


# ------------------------------------------------------------------ situação dos editais
def _edital(**campos):
    base = {"titulo": "Edital X", "url": "https://prefeitura.exemplo/edital", "data_encerramento": "2026-10-30",
            "data_publicacao": "2026-09-01", "situacao_inscricao": "NAO_CONFIRMADO", "status": "ENCONTRADO",
            "origem_descoberta": "AUTOMATICA"}
    base.update(campos)
    return base


def test_edital_com_prazo_futuro_e_link_e_aberto():
    situacao, motivo = editais.situacao_efetiva(_edital(), HOJE)
    assert situacao == "ABERTO" and "30/10/2026" in motivo


def test_edital_com_prazo_vencido_e_encerrado_mesmo_gravado_como_aberto():
    situacao, _ = editais.situacao_efetiva(_edital(data_encerramento="2026-09-01", situacao_inscricao="ABERTO"), HOJE)
    assert situacao == "ENCERRADO"


def test_edital_sem_data_nao_e_tratado_como_aberto():
    situacao, motivo = editais.situacao_efetiva(_edital(data_encerramento=None), HOJE)
    assert situacao == "NAO_CONFIRMADO" and "data de encerramento" in motivo


def test_edital_sem_link_nao_e_aberto_mesmo_com_prazo_futuro():
    assert editais.situacao_efetiva(_edital(url=None), HOJE)[0] == "NAO_CONFIRMADO"


def test_edital_que_ainda_nao_abriu_nao_e_aberto():
    assert editais.situacao_efetiva(_edital(data_abertura="2026-10-05"), HOJE)[0] == "NAO_CONFIRMADO"


def test_pagina_oficial_dizendo_encerrado_ou_status_interno_encerrado_prevalece():
    assert editais.situacao_efetiva(_edital(situacao_inscricao="ENCERRADO"), HOJE)[0] == "ENCERRADO"
    assert editais.situacao_efetiva(_edital(status="ENCERRADO"), HOJE)[0] == "ENCERRADO"


def test_registro_de_teste_nunca_e_oportunidade_aberta():
    teste = _edital(origem_descoberta="TESTE_NAO_REAL")
    assert editais.situacao_efetiva(teste, HOJE)[0] != "ABERTO"
    grupos = editais.agrupar_por_situacao([teste, _edital()], HOJE)
    assert len(grupos["testes"]) == 1 and len(grupos["abertos"]) == 1


def test_agrupamento_e_contagem():
    lista = [_edital(), _edital(data_encerramento="2026-01-01"), _edital(data_encerramento=None)]
    assert editais.contar_por_situacao(lista, HOJE) == {"abertos": 1, "nao_confirmados": 1, "encerrados": 1, "testes": 0}


def test_abertos_com_aderencia_so_traz_abertos_e_ordena_pela_nota():
    perfil = {"temas": ["cultura", "danca"], "palavras_chave": [], "cidades": ["Guaíra"], "estados": ["SP"], "programas": []}
    forte = _edital(titulo="Fomento à cultura e dança", descricao="cultura danca", territorio="Guaíra")
    fraco = _edital(titulo="Outro assunto", descricao="nada a ver", territorio="Acre")
    encerrado = _edital(titulo="Cultura e dança encerrado", descricao="cultura danca", data_encerramento="2026-01-01")
    itens = editais.abertos_com_aderencia([fraco, encerrado, forte], perfil, hoje=HOJE)
    assert [i["titulo"] for i in itens] == ["Fomento à cultura e dança", "Outro assunto"]
    assert itens[0]["nota_final"] > itens[1]["nota_final"]
    assert editais.abertos_com_aderencia([fraco, forte], perfil, nota_minima=7.0, hoje=HOJE)[0]["titulo"].startswith("Fomento")


def test_aderencia_traz_detalhes_de_todos_os_criterios_e_marca_o_que_falta():
    perfil = {"temas": ["cultura"], "palavras_chave": [], "cidades": [], "estados": [], "programas": []}
    r = editais.calcular_aderencia({"titulo": "cultura", "descricao": "cultura"}, perfil, HOJE)
    assert [d["criterio"] for d in r["detalhes"]] == ["area", "territorio", "publico", "elegibilidade", "valor", "prazo"]
    sem_dado = [d for d in r["detalhes"] if d["nota"] is None]
    assert sem_dado and all(d["motivo"] for d in sem_dado)  # o motivo da ausência está explícito


# ------------------------------------------------------------------ remover do Pipeline
@pytest.fixture
def crm_base():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    banco.criar_tabelas(conn)
    crm.criar_tabelas(conn)
    eid, _ = banco.obter_ou_criar_empresa(
        conn, {"cnpj": "11444777000161", "razao_social": "Empresa Teste", "nome_fantasia": None, "cidade": "Guaíra",
               "estado": "SP", "status": None})
    yield conn, eid
    conn.close()


def test_remover_tira_do_pipeline_mas_preserva_empresa_e_historico(crm_base):
    conn, eid = crm_base
    op = crm.criar_oportunidade(conn, {"empresa_id": eid, "titulo": "Patrocínio 2026"})
    crm.registrar_interacao(conn, {"oportunidade_id": op, "tipo": "ligacao", "data": "2026-09-10", "descricao": "Primeiro contato"})
    assert crm.remover_oportunidade(conn, op, "cadastrada por engano") is True
    assert op not in {o["id"] for o in crm.listar_oportunidades(conn)}
    assert conn.execute("SELECT COUNT(*) FROM empresas WHERE id = ?", (eid,)).fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM crm_interacoes WHERE oportunidade_id = ?", (op,)).fetchone()[0] == 1
    linha = conn.execute("SELECT removida_em, motivo_remocao FROM crm_oportunidades WHERE id = ?", (op,)).fetchone()
    assert linha["removida_em"] and linha["motivo_remocao"] == "cadastrada por engano"


def test_removida_nao_conta_em_valor_potencial_nem_atividade_recente_e_pode_ser_restaurada(crm_base):
    conn, eid = crm_base
    op = crm.criar_oportunidade(conn, {"empresa_id": eid, "titulo": "X", "valor_potencial": 5000})
    crm.registrar_interacao(conn, {"oportunidade_id": op, "tipo": "email", "data": "2026-09-10"})
    crm.remover_oportunidade(conn, op)
    assert crm.valor_potencial_total([dict(o) for o in crm.listar_oportunidades(conn)]) == 0
    assert crm.listar_interacoes_recentes(conn) == []
    assert not crm.empresa_ja_tem_oportunidade_aberta(conn, eid)
    assert [r["id"] for r in crm.listar_removidas(conn)] == [op]
    assert crm.restaurar_oportunidade(conn, op) is True
    assert op in {o["id"] for o in crm.listar_oportunidades(conn)}


def test_remover_inexistente_ou_duas_vezes_devolve_false(crm_base):
    conn, eid = crm_base
    assert crm.remover_oportunidade(conn, 999) is False
    op = crm.criar_oportunidade(conn, {"empresa_id": eid, "titulo": "X"})
    assert crm.remover_oportunidade(conn, op) is True
    assert crm.remover_oportunidade(conn, op) is False


def test_oportunidade_ganha_removida_nao_marca_relacionamento(crm_base):
    conn, eid = crm_base
    op = crm.criar_oportunidade(conn, {"empresa_id": eid, "titulo": "Ganha", "estagio": "Fechado — ganho"})
    crm.remover_oportunidade(conn, op)
    banco.migrar_empresas(conn)
    relacionamento.sincronizar(conn)
    assert conn.execute("SELECT relacionamento_iorm FROM empresas WHERE id = ?", (eid,)).fetchone()[0] == 0


# ------------------------------------------------------------------ formatação brasileira
@pytest.mark.parametrize("valor,esperado", [
    (1_000_000, "R$ 1.000.000,00"), (1000.5, "R$ 1.000,50"), (100000, "R$ 100.000,00"), (0, "R$ 0,00"),
    (1573345.987, "R$ 1.573.345,99"), (14427151575.217, "R$ 14.427.151.575,22"), (-2500, "R$ -2.500,00"),
    ("2500.5", "R$ 2.500,50"),
])
def test_moeda_brasileira(valor, esperado):
    assert formatacao.formatar_moeda_br(valor) == esperado


@pytest.mark.parametrize("ausente", [None, float("nan"), "abc", ""])
def test_moeda_dado_ausente(ausente):
    assert formatacao.formatar_moeda_br(ausente) == "Não disponível"


def test_moeda_aceita_tipos_numpy_e_nao_altera_o_valor_guardado():
    import numpy as np

    valor = np.float64(1234567.891)
    assert formatacao.formatar_moeda_br(valor) == "R$ 1.234.567,89"
    assert valor == 1234567.891  # só a apresentação muda


def test_texto_longo_nao_e_truncado_pela_formatacao():
    nome = "INSTITUTO OSWALDO RIBEIRO DE MENDONÇA — " + "X" * 150
    assert formatacao.formatar_numero_br(8311) == "8.311"
    assert nome in f"{nome}"  # formatadores de texto não cortam; ver test_paginas_smoke para o auditor de layout

# ------------------------------------------------------------------ prazo sugerido pela página x confirmação da equipe
def test_extrair_prazo_devolve_data_final_e_trecho_literal():
    from processamento import links_editais

    data, trecho = links_editais.extrair_prazo("Prazo de inscrição: de 01/10/2026 a 15/11/2026. Divulgação em 20/12/2026")
    assert data == "2026-11-15" and "15/11/2026" in trecho
    data, _ = links_editais.extrair_prazo("Inscrições abertas até 30 de outubro de 2026 pelo site.")
    assert data == "2026-10-30"
    assert links_editais.extrair_prazo("Página sem nenhuma data de prazo.") is None
    assert links_editais.extrair_prazo("Prazo indefinido 31/02/2026 (data impossível)") is None


def test_verificar_link_sugere_prazo_so_de_pagina_que_corresponde_ao_titulo():
    from processamento import links_editais

    html = "<html><title>Edital Fomento Dança 2026</title><body>Edital Fomento Dança 2026. Inscrições até 30/10/2026.</body></html>"
    r = links_editais.verificar_link("https://prefeitura.exemplo/fomento-danca-2026", "Edital Fomento Dança 2026",
                                     lambda u: (200, u, html))
    assert r["prazo_sugerido"] == "2026-10-30" and "30/10/2026" in r["prazo_sugerido_trecho"]
    r2 = links_editais.verificar_link("https://prefeitura.exemplo/outra-coisa", "Edital Totalmente Diferente XYZ",
                                      lambda u: (200, u, html))
    assert r2["prazo_sugerido"] is None  # página não é do edital: não sugere prazo


def test_prazo_sugerido_nao_abre_o_edital_ate_a_equipe_confirmar():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    editais.criar_tabelas(conn)
    eid = editais.criar_edital(conn, {"titulo": "Edital Fomento Dança 2026", "url": "https://prefeitura.exemplo/fomento",
                                      "fonte": "teste"})
    editais.registrar_verificacao(conn, eid, {"status": "PAGINA_ESPECIFICA_CONFIRMADA", "prazo_sugerido": "2099-10-30",
                                              "prazo_sugerido_trecho": "Inscrições até 30/10/2099"})
    linha = conn.execute("SELECT * FROM editais WHERE id = ?", (eid,)).fetchone()
    assert linha["prazo_sugerido"] == "2099-10-30" and linha["data_encerramento"] is None
    assert editais.situacao_efetiva(linha)[0] == "NAO_CONFIRMADO"
    assert editais.confirmar_prazo(conn, eid) == "2099-10-30"
    linha = conn.execute("SELECT * FROM editais WHERE id = ?", (eid,)).fetchone()
    assert linha["prazo_origem"] == "CONFIRMADO_PELA_EQUIPE" and editais.situacao_efetiva(linha)[0] == "ABERTO"
    with pytest.raises(ValueError):
        editais.confirmar_prazo(conn, eid, "31/02/2099")
    conn.close()


def test_link_direto_de_inscricao_nunca_e_inventado_a_partir_do_link_do_edital():
    from processamento import links_editais

    html = "<html><title>Edital Fomento Dança 2026</title><body>Edital Fomento Dança 2026. <a href='/edital-fomento'>Início</a></body></html>"
    r = links_editais.verificar_link("https://prefeitura.exemplo/edital-fomento-danca", "Edital Fomento Dança 2026",
                                     lambda u: (200, u, html))
    assert r["url_inscricao_encontrada"] is None
    ok = "<html><title>Edital Fomento Dança 2026</title><body>Edital Fomento Dança 2026 <a href='https://forms.gle/abc'>Inscreva-se</a></body></html>"
    r = links_editais.verificar_link("https://prefeitura.exemplo/edital-fomento-danca", "Edital Fomento Dança 2026",
                                     lambda u: (200, u, ok))
    assert r["url_inscricao_encontrada"] == "https://forms.gle/abc"
