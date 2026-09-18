import sqlite3

import pytest

from processamento import banco, crm, metricas, relacionamento


class _Conexao(sqlite3.Connection):
    pass


@pytest.fixture
def conexao():
    conn = sqlite3.connect(":memory:", factory=_Conexao)
    conn.row_factory = sqlite3.Row
    banco.criar_tabelas(conn)
    crm.criar_tabelas(conn)

    def empresa(cnpj, nome, cidade):
        return banco.obter_ou_criar_empresa(
            conn, {"cnpj": cnpj, "razao_social": nome, "nome_fantasia": None, "cidade": cidade, "estado": "SP", "status": None}
        )[0]

    def incentivo(eid, projeto, url):
        banco.inserir_ou_atualizar_incentivo(
            conn, {"empresa_id": eid, "fonte": "SALIC", "tipo_incentivo": "Lei Rouanet", "projeto": projeto, "ano": 2020,
                   "valor": 1000.0, "uf": "SP", "cidade": "Guaíra", "url_fonte": url, "coletado_em": "2026-01-01",
                   "nivel_confianca": "ALTO"}
        )

    ids = {
        "parceira": empresa("11444777000161", "Empresa Parceira", "Guaíra"),
        "prospect": empresa("11222333000181", "Empresa Prospect", "Guaíra"),
        "crm": empresa("45997418000153", "Empresa Ganha no CRM", "Ipuã"),
    }
    incentivo(ids["parceira"], "Usina da Dança 2019", "https://x/1")
    incentivo(ids["prospect"], "Projeto Qualquer", "https://x/2")
    conn.execute(
        "INSERT INTO crm_oportunidades (empresa_id, titulo, estagio, criado_em, atualizado_em) VALUES (?, 'Ganho', 'Fechado — ganho', 'a', 'a')",
        (ids["crm"],),
    )
    conn.commit()
    conn.ids = ids
    yield conn
    conn.close()


def _linha(conn, chave):
    return conn.execute("SELECT * FROM empresas WHERE id = ?", (conn.ids[chave],)).fetchone()


def test_sincronizar_marca_quem_apoiou_projeto_do_iorm(conexao):
    resumo = relacionamento.sincronizar(conexao)
    assert resumo["doacao"] == 1
    linha = _linha(conexao, "parceira")
    assert linha["relacionamento_iorm"] == 1
    assert linha["relacionamento_tipo"] == relacionamento.TIPO_DOACAO
    assert "SALIC" in linha["relacionamento_fonte"] and "2020" in linha["relacionamento_fonte"]


def test_sincronizar_marca_oportunidade_ganha_no_crm(conexao):
    relacionamento.sincronizar(conexao)
    assert _linha(conexao, "crm")["relacionamento_tipo"] == relacionamento.TIPO_CRM


def test_prospect_sem_evidencia_continua_prospect(conexao):
    relacionamento.sincronizar(conexao)
    assert _linha(conexao, "prospect")["relacionamento_iorm"] == 0


def test_sincronizar_e_idempotente(conexao):
    relacionamento.sincronizar(conexao)
    antes = _linha(conexao, "parceira")["relacionamento_em"]
    relacionamento.sincronizar(conexao)
    assert _linha(conexao, "parceira")["relacionamento_em"] == antes
    assert conexao.execute("SELECT COUNT(*) FROM empresas").fetchone()[0] == 3  # nada duplicado nem apagado


def test_classificacao_manual_nao_e_sobrescrita_pela_sincronizacao(conexao):
    relacionamento.marcar_manual(conexao, conexao.ids["parceira"], False, "Doação foi de outra empresa homônima")
    relacionamento.sincronizar(conexao)
    linha = _linha(conexao, "parceira")
    assert linha["relacionamento_iorm"] == 0 and linha["relacionamento_tipo"] == relacionamento.TIPO_MANUAL


def test_marcar_manual_exige_justificativa(conexao):
    with pytest.raises(ValueError):
        relacionamento.marcar_manual(conexao, conexao.ids["prospect"], True, "   ")


def test_reabrir_prospeccao_exige_justificativa(conexao):
    with pytest.raises(ValueError):
        relacionamento.reabrir_prospeccao(conexao, conexao.ids["parceira"], True, "")


def test_eh_prospect_definicao_unica():
    assert relacionamento.eh_prospect(0, 0) is True
    assert relacionamento.eh_prospect(1, 0) is False
    assert relacionamento.eh_prospect(1, 1) is True  # reabertura explícita


def test_empresa_com_relacionamento_nunca_e_prospect_e_prospect_ao_mesmo_tempo(conexao):
    relacionamento.sincronizar(conexao)
    df = metricas.carregar_empresas(conexao)
    linha_cruzada = df[df["linha_cruzada"]]
    prospects = df[df["eh_prospect"]]
    assert set(linha_cruzada["id"]) == {conexao.ids["parceira"], conexao.ids["crm"]}
    assert set(linha_cruzada["id"]).isdisjoint(set(prospects["id"]))
    assert set(prospects["id"]) == {conexao.ids["prospect"]}
    assert len(df) == 3  # ninguém saiu da base


def test_reabertura_justificada_faz_empresa_aparecer_nos_dois_lados(conexao):
    relacionamento.sincronizar(conexao)
    relacionamento.reabrir_prospeccao(conexao, conexao.ids["parceira"], True, "Apoiou em 2015; nova abordagem aprovada")
    df = metricas.carregar_empresas(conexao)
    linha = df[df["id"] == conexao.ids["parceira"]].iloc[0]
    assert bool(linha["linha_cruzada"]) and bool(linha["eh_prospect"])
    assert "nova abordagem" in linha["reabrir_justificativa"]


def test_classificacao_evidente_mesmo_sem_sincronizar(conexao):
    # Sem rodar sincronizar(), a evidência nos dados já basta para não virar prospect.
    df = metricas.carregar_empresas(conexao)
    assert not bool(df[df["id"] == conexao.ids["parceira"]].iloc[0]["eh_prospect"])


def test_a_propria_osc_nunca_e_prospect_mesmo_com_doacao_a_si_mesma(conexao):
    from processamento import osc

    osc.criar_tabelas(conexao)
    osc.criar_ou_atualizar_osc(conexao, None, {"nome": "OSC Própria", "cnpj": "11.222.333/0001-81"})  # = empresa "prospect"
    conexao.execute("UPDATE incentivos SET projeto = 'Usina da Dança' WHERE empresa_id = ?", (conexao.ids["prospect"],))
    conexao.commit()
    relacionamento.sincronizar(conexao)
    linha = _linha(conexao, "prospect")
    assert linha["relacionamento_tipo"] == relacionamento.TIPO_PROPRIA_OSC  # não é sobrescrito por DOACAO
    df = metricas.carregar_empresas(conexao)
    assert not bool(df[df["id"] == conexao.ids["prospect"]].iloc[0]["eh_prospect"])


def test_migrar_empresas_e_idempotente_em_banco_antigo():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE empresas (id INTEGER PRIMARY KEY, cnpj TEXT, razao_social TEXT NOT NULL, criado_em TEXT, atualizado_em TEXT)"
    )
    conn.execute("INSERT INTO empresas (razao_social, criado_em, atualizado_em) VALUES ('Antiga', 'a', 'a')")
    banco.migrar_empresas(conn)
    banco.migrar_empresas(conn)
    linha = conn.execute("SELECT * FROM empresas").fetchone()
    assert linha["relacionamento_iorm"] == 0 and linha["razao_social"] == "Antiga"


