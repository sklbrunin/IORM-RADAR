"""Regressões v8 — doador do IORM não pode ficar entre os prospects.

Causa real encontrada: a lista de programas do IORM era uma constante no código e não incluía o projeto
"IORM CULTURAL 2026" (apoiado em 2025/2026). Empresas como "Produtos Alimentícios Orlândia S/A" (doação em 2026)
continuavam como prospects. Agora os termos vêm do Cérebro da OSC + sigla da OSC (processamento/programas_iorm.py).
"""
from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from processamento import banco, crm, metricas, osc, programas_iorm, relacionamento

RAIZ = Path(__file__).resolve().parent.parent
BANCO_REAL = RAIZ / "dados" / "iorm_radar.db"


class _Conexao(sqlite3.Connection):
    pass


@pytest.fixture
def conexao():
    conn = sqlite3.connect(":memory:", factory=_Conexao)
    conn.row_factory = sqlite3.Row
    banco.criar_tabelas(conn)
    banco.criar_tabelas_enriquecimento(conn)
    crm.criar_tabelas(conn)
    osc.criar_tabelas(conn)
    osc_id = osc.criar_ou_atualizar_osc(conn, None, {"nome": "Instituto Oswaldo Ribeiro de Mendonça", "nome_fantasia": "IORM"})
    osc.adicionar_programa(conn, osc_id, {"nome": "Usina da Dança"})
    osc.adicionar_programa(conn, osc_id, {"nome": "Artes e Cultura"})  # nome genérico demais: não pode virar termo de busca
    conn.osc_id = osc_id
    yield conn
    programas_iorm.carregar(sqlite3.connect(":memory:"))  # devolve a lista global ao estado-base para os outros testes
    conn.close()


def _empresa(conn, cnpj, nome, cidade="Orlândia"):
    return banco.obter_ou_criar_empresa(conn, {"cnpj": cnpj, "razao_social": nome, "nome_fantasia": None, "cidade": cidade,
                                              "estado": "SP", "status": None})[0]


def _incentivo(conn, empresa_id, projeto, ano, url):
    banco.inserir_ou_atualizar_incentivo(conn, {
        "empresa_id": empresa_id, "fonte": "SALIC", "tipo_incentivo": "Lei Rouanet", "mecanismo": "LEI_ROUANET", "projeto": projeto,
        "ano": ano, "valor": 16276.15, "uf": "SP", "cidade": "Orlândia", "url_fonte": url, "coletado_em": "2026-09-01",
        "nivel_confianca": "ALTO"})
    conn.commit()


def _situacao(conn, empresa_id):
    df = metricas.carregar_empresas(conn)
    linha = df[df["id"] == empresa_id].iloc[0]
    return bool(linha["eh_prospect"]), bool(linha["linha_cruzada"])


# ------------------------------------------------------------------ o caso real (projeto "IORM CULTURAL 2026")
def test_doador_de_projeto_com_a_sigla_do_iorm_sai_dos_prospects_e_vai_para_linha_cruzada(conexao):
    doadora = _empresa(conexao, "11444777000161", "Produtos Alimentícios Orlândia S/A")
    _incentivo(conexao, doadora, "IORM CULTURAL 2026", 2026, "https://salic/1")
    assert _situacao(conexao, doadora) == (False, True)  # já pela regra dinâmica, sem depender de marca antiga
    relatorio = relacionamento.reconciliar_relacionamentos(conexao)
    assert [e["empresa"] for e in relatorio["novas_no_relacionamento"]] == ["Produtos Alimentícios Orlândia S/A"]
    linha = conexao.execute("SELECT * FROM empresas WHERE id = ?", (doadora,)).fetchone()
    assert linha["relacionamento_iorm"] == 1 and linha["relacionamento_tipo"] == relacionamento.TIPO_DOACAO
    assert "IORM CULTURAL 2026" in linha["relacionamento_fonte"] and "2026" in linha["relacionamento_fonte"]  # motivo/evidência


def test_nova_doacao_depois_da_ultima_sincronizacao_e_reconhecida(conexao):
    empresa = _empresa(conexao, "11222333000181", "Empresa que ainda não doou")
    relacionamento.reconciliar_relacionamentos(conexao)
    assert _situacao(conexao, empresa) == (True, False)  # ainda é prospect
    _incentivo(conexao, empresa, "IORM CULTURAL 2026", 2026, "https://salic/2")  # entra depois
    assert _situacao(conexao, empresa) == (False, True)  # a tela não depende da marca antiga
    assert conexao.execute("SELECT relacionamento_iorm FROM empresas WHERE id = ?", (empresa,)).fetchone()[0] == 0
    relatorio = relacionamento.reconciliar_relacionamentos(conexao)
    assert relatorio["relacionamento_depois"] == relatorio["relacionamento_antes"] + 1
    assert conexao.execute("SELECT relacionamento_iorm FROM empresas WHERE id = ?", (empresa,)).fetchone()[0] == 1


def test_programa_novo_no_cerebro_da_osc_reconcilia_sozinho(conexao):
    empresa = _empresa(conexao, "45997418000153", "Apoiadora do Novo Horizonte")
    _incentivo(conexao, empresa, "Projeto Novo Horizonte 2025", 2025, "https://salic/3")
    assert _situacao(conexao, empresa) == (True, False)  # programa ainda não cadastrado: não é adivinhado
    osc.adicionar_programa(conexao, conexao.osc_id, {"nome": "Projeto Novo Horizonte"})  # gancho reconcilia
    assert conexao.execute("SELECT relacionamento_iorm FROM empresas WHERE id = ?", (empresa,)).fetchone()[0] == 1
    assert _situacao(conexao, empresa) == (False, True)


def test_nome_generico_de_programa_e_palavra_dentro_de_outra_palavra_nao_classificam(conexao):
    a = _empresa(conexao, "11444777000161", "Empresa A")
    b = _empresa(conexao, "11222333000181", "Empresa B")
    _incentivo(conexao, a, "Festival de Artes e Cultura de Bebedouro", 2025, "https://salic/4")  # 'Artes e Cultura' é genérico
    _incentivo(conexao, b, "Projeto Fiormaris 2025", 2025, "https://salic/5")  # 'iorm' dentro de outra palavra
    relacionamento.reconciliar_relacionamentos(conexao)
    assert _situacao(conexao, a) == (True, False) and _situacao(conexao, b) == (True, False)


def test_reabertura_explicita_e_classificacao_manual_sobrevivem_a_reconciliacao(conexao):
    reaberta = _empresa(conexao, "11444777000161", "Reaberta")
    manual = _empresa(conexao, "11222333000181", "Marcada como nao relacionada")
    for empresa, url in ((reaberta, "https://salic/6"), (manual, "https://salic/7")):
        _incentivo(conexao, empresa, "IORM CULTURAL 2026", 2026, url)
    relacionamento.reconciliar_relacionamentos(conexao)
    relacionamento.reabrir_prospeccao(conexao, reaberta, True, "Campanha de ampliação 2027")
    relacionamento.marcar_manual(conexao, manual, False, "Doou para outro projeto homônimo — conferido")
    relacionamento.reconciliar_relacionamentos(conexao)
    relacionamento.reconciliar_relacionamentos(conexao)
    assert _situacao(conexao, reaberta) == (True, True)  # justificativa registrada: conta nos dois, de forma explícita
    assert _situacao(conexao, manual) == (True, False)  # decisão manual da equipe nunca é desfeita
    assert conexao.execute("SELECT reabrir_justificativa FROM empresas WHERE id = ?", (reaberta,)).fetchone()[0]


def test_reconciliar_e_idempotente_e_nao_apaga_nada(conexao):
    empresa = _empresa(conexao, "11444777000161", "Doadora")
    _incentivo(conexao, empresa, "IORM CULTURAL 2026", 2026, "https://salic/8")
    antes = (conexao.execute("SELECT COUNT(*) FROM empresas").fetchone()[0], conexao.execute("SELECT COUNT(*) FROM incentivos").fetchone()[0])
    r1 = relacionamento.reconciliar_relacionamentos(conexao)
    r2 = relacionamento.reconciliar_relacionamentos(conexao)
    assert len(r1["novas_no_relacionamento"]) == 1 and r2["novas_no_relacionamento"] == []
    assert antes == (conexao.execute("SELECT COUNT(*) FROM empresas").fetchone()[0], conexao.execute("SELECT COUNT(*) FROM incentivos").fetchone()[0])


def test_contadores_nao_misturam_apos_a_correcao(conexao):
    doadora = _empresa(conexao, "11444777000161", "Doadora")
    outra = _empresa(conexao, "11222333000181", "Prospect comum")
    _incentivo(conexao, doadora, "IORM CULTURAL 2026", 2026, "https://salic/9")
    relacionamento.reconciliar_relacionamentos(conexao)
    df = metricas.carregar_empresas(conexao)
    df["pesquisado"] = False
    c = metricas.contadores_empresas(df)
    assert (c["total"], c["prospects"], c["linha_cruzada"]) == (2, 1, 1) and c["prospects"] + c["linha_cruzada"] == c["total"]
    assert outra in set(df[df["eh_prospect"]]["id"]) and doadora not in set(df[df["eh_prospect"]]["id"])


def test_ingestao_de_incentivos_reconcilia_automaticamente(conexao):
    """Coleta nova (provedor) → a empresa que apoiou o IORM já sai dos prospects, sem passo manual."""
    from processamento import incentivos_providers as ip

    class Provedor(ip.IncentivoProvider):
        codigo = "TESTE"
        nome = "Teste"

        def coletar(self, uf, max_paginas=None, **opcoes):
            empresa = {"cnpj": "11444777000161", "razao_social": "DOADORA DA COLETA LTDA", "nome_fantasia": None, "cidade": "Orlândia",
                       "estado": "SP", "status": None}
            incentivo = {"mecanismo": "TESTE", "fonte": "teste", "tipo_incentivo": "Lei Rouanet", "projeto": "IORM CULTURAL 2026",
                         "ano": 2026, "valor": 100.0, "uf": "SP", "cidade": "Orlândia", "url_fonte": "https://salic/coleta/1",
                         "coletado_em": "2026-09-23", "nivel_confianca": "ALTO"}
            yield ip.RegistroIncentivo(empresa, incentivo)

    resumo = ip.ingerir(conexao, Provedor(), "SP")
    assert resumo["relacionamento"] == 1
    empresa_id = conexao.execute("SELECT id FROM empresas WHERE cnpj = '11444777000161'").fetchone()[0]
    assert _situacao(conexao, empresa_id) == (False, True)


# ------------------------------------------------------------------ termos vêm do Cérebro da OSC
def test_termos_incluem_programas_da_osc_sigla_e_nome_mas_nao_genericos(conexao):
    termos = programas_iorm.carregar(conexao)
    assert "usina da danca" in termos and "iorm" in termos and "instituto oswaldo ribeiro de mendonca" in termos
    assert "artes e cultura" not in termos
    assert programas_iorm.projeto_e_do_iorm("Espetáculo Usina da Dança 2016") and programas_iorm.projeto_e_do_iorm("iorm cultural")
    assert not programas_iorm.projeto_e_do_iorm(None) and not programas_iorm.projeto_e_do_iorm("Plano Anual do Hospital de Amor")


# ------------------------------------------------------------------ caso REAL do banco (não inventado)
@pytest.mark.skipif(not BANCO_REAL.exists(), reason="banco real não disponível")
def test_doador_real_de_2026_esta_na_linha_cruzada_e_fora_dos_prospects(tmp_path):
    copia = tmp_path / "copia.db"
    shutil.copy(BANCO_REAL, copia)
    conn = sqlite3.connect(copia, factory=_Conexao)
    conn.row_factory = sqlite3.Row
    linha = conn.execute(
        """SELECT e.id, e.razao_social FROM empresas e JOIN incentivos i ON i.empresa_id = e.id
           WHERE i.projeto = 'IORM CULTURAL 2026' AND i.ano = 2026""").fetchone()
    assert linha is not None, "o dado real de referência (IORM CULTURAL 2026, ano 2026) deixou de existir no banco"
    relacionamento.reconciliar_relacionamentos(conn)
    df = metricas.carregar_empresas(conn)
    r = df[df["id"] == linha["id"]].iloc[0]
    assert not bool(r["eh_prospect"]) and bool(r["linha_cruzada"])
    assert linha["id"] not in set(df[df["eh_prospect"]]["id"]) and linha["id"] in set(df[df["linha_cruzada"]]["id"])
    fonte = conn.execute("SELECT relacionamento_fonte, relacionamento_tipo FROM empresas WHERE id = ?", (linha["id"],)).fetchone()
    assert fonte["relacionamento_tipo"] == relacionamento.TIPO_DOACAO and "IORM CULTURAL 2026" in fonte["relacionamento_fonte"]
    # todas as empresas que apoiaram QUALQUER projeto do IORM estão fora dos prospects
    ids = {l["empresa_id"] for l in conn.execute("SELECT empresa_id, projeto FROM incentivos WHERE projeto IS NOT NULL")
           if programas_iorm.projeto_e_do_iorm(l["projeto"])}
    prospects = set(df[df["eh_prospect"] & ~df["reabrir_prospeccao"]]["id"])
    assert ids and not (ids & prospects)
    conn.close()
    programas_iorm.carregar(sqlite3.connect(":memory:"))
