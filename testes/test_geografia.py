import sqlite3

import pytest

from processamento import geografia, osc, regiao


def _municipio(id_, nome, ri_id, ri_nome):
    return {"id": id_, "nome": nome, "regiao-imediata": {"id": ri_id, "nome": ri_nome}}


MUNICIPIOS_FALSOS = [
    _municipio(1, "Guaíra", 100, "Barretos"),
    _municipio(2, "Barretos", 100, "Barretos"),
    _municipio(3, "Colômbia", 100, "Barretos"),
    _municipio(4, "Ipuã", 200, "São Joaquim da Barra"),
    _municipio(5, "Orlândia", 200, "São Joaquim da Barra"),
    _municipio(6, "Franca", 300, "Franca"),
]


def fetcher_falso(url):
    return MUNICIPIOS_FALSOS


@pytest.fixture
def conexao():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    geografia.criar_tabelas(conn)
    yield conn
    conn.close()


def test_buscar_regiao_ibge_lista_municipios_da_mesma_regiao_imediata():
    dados = geografia.buscar_regiao_ibge("Guaíra", "SP", fetcher_falso)
    nomes = [n for _, n in dados["municipios"]]
    assert dados["regiao_imediata"] == "Barretos"
    assert nomes == ["Barretos", "Colômbia", "Guaíra"]
    assert "Franca" not in nomes


def test_buscar_regiao_ibge_ignora_acento_e_caixa_do_polo():
    dados = geografia.buscar_regiao_ibge("GUAIRA", "SP", fetcher_falso)
    assert dados["regiao_imediata"] == "Barretos"


def test_polo_inexistente_levanta_erro():
    with pytest.raises(ValueError):
        geografia.buscar_regiao_ibge("Cidade Que Não Existe", "SP", fetcher_falso)


def test_uf_sem_codigo_levanta_erro():
    with pytest.raises(ValueError):
        geografia.buscar_regiao_ibge("Guaíra", "XX", fetcher_falso)


def test_sincronizar_grava_regiao_com_fonte_e_sem_o_proprio_polo(conexao):
    resumo = geografia.sincronizar_ibge(conexao, ["Guaíra"], "SP", fetcher_falso)
    assert resumo["novos"] == 2 and resumo["erros"] == []
    linhas = geografia.listar(conexao)
    assert {l["municipio"] for l in linhas} == {"Barretos", "Colômbia"}
    assert all(l["origem"] == "IBGE_REGIAO_IMEDIATA" and "IBGE" in l["fonte"] for l in linhas)


def test_sincronizar_duas_vezes_nao_duplica(conexao):
    geografia.sincronizar_ibge(conexao, ["Guaíra"], "SP", fetcher_falso)
    resumo = geografia.sincronizar_ibge(conexao, ["Guaíra"], "SP", fetcher_falso)
    assert resumo["novos"] == 0 and resumo["ja_existentes"] == 2
    assert len(geografia.listar(conexao, apenas_ativos=False)) == 2


def test_sincronizar_nao_reativa_municipio_desativado_pela_equipe(conexao):
    geografia.sincronizar_ibge(conexao, ["Guaíra"], "SP", fetcher_falso)
    barretos = next(l for l in geografia.listar(conexao) if l["municipio"] == "Barretos")
    geografia.definir_ativo(conexao, barretos["id"], False)
    geografia.sincronizar_ibge(conexao, ["Guaíra"], "SP", fetcher_falso)
    assert {l["municipio"] for l in geografia.listar(conexao)} == {"Colômbia"}


def test_polo_com_erro_nao_derruba_os_outros(conexao):
    resumo = geografia.sincronizar_ibge(conexao, ["Inexistente", "Guaíra"], "SP", fetcher_falso)
    assert len(resumo["erros"]) == 1
    assert resumo["novos"] == 2


def test_adicionar_manual_fica_marcado_como_manual(conexao):
    geografia.adicionar_manual(conexao, "Guaíra", "Cidade Nova", "SP", "atendimento informal")
    linha = next(l for l in geografia.listar(conexao) if l["municipio"] == "Cidade Nova")
    assert linha["origem"] == "MANUAL" and "atendimento informal" in linha["fonte"]


def test_municipios_por_polo_agrupa(conexao):
    geografia.sincronizar_ibge(conexao, ["Guaíra", "Ipuã"], "SP", fetcher_falso)
    grupos = geografia.municipios_por_polo(conexao)
    assert set(grupos) == {"Guaíra", "Ipuã"}
    assert [l["municipio"] for l in grupos["Ipuã"]] == ["Orlândia"]


def test_perfil_osc_expoe_regiao_dos_polos_como_regiao_proxima():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    osc.criar_tabelas(conn)
    osc_id = osc.criar_ou_atualizar_osc(conn, None, {"nome": "OSC Teste"})
    osc.adicionar_territorio(conn, osc_id, "cidade", "Guaíra")
    geografia.sincronizar_ibge(conn, ["Guaíra"], "SP", fetcher_falso)
    perfil = osc.carregar_perfil_completo(conn, osc_id)
    assert regiao.classificar_cidade("Barretos", perfil["territorios"]) == "REGIAO_PROXIMA"
    assert regiao.classificar_cidade("BARRETOS", perfil["territorios"]) == "REGIAO_PROXIMA"
    assert regiao.classificar_cidade("Guaíra", perfil["territorios"]) == "CIDADE_ATUACAO"
    assert perfil["cidades"] == ["Guaíra"]  # região próxima não vira "cidade de atuação"
    assert regiao.classificar_cidade("Franca", perfil["territorios"]) == "FORA_DA_REGIAO"


def test_normalizar_cidade_remove_acento_e_espaco_extra():
    assert regiao.normalizar_cidade("  SÃO  Joaquim da Barra ") == "sao joaquim da barra"
