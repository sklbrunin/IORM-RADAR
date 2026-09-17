import sqlite3

import pandas as pd
import pytest

from processamento import banco, metricas


def _linha(**overrides):
    base = {
        "num_incentivos": 0,
        "cnpj_confirmado": False,
        "tem_detalhe": False,
        "cidade_estrategica": False,
        "projeto_iorm": False,
        "valor_total": 0,
    }
    base.update(overrides)
    return pd.Series(base)


def test_empresa_sem_nenhum_criterio_tem_score_zero():
    assert metricas._calcular_score(_linha()) == 0


def test_empresa_com_todos_os_criterios_chega_a_100():
    linha = _linha(
        num_incentivos=5,
        cnpj_confirmado=True,
        tem_detalhe=True,
        cidade_estrategica=True,
        projeto_iorm=True,
        valor_total=1_000_000,
    )
    assert metricas._calcular_score(linha) == 100


def test_faixas_de_valor_sao_cumulativas_e_exclusivas():
    assert metricas._calcular_score(_linha(valor_total=5_000)) == 0
    assert metricas._calcular_score(_linha(valor_total=10_000)) == 5
    assert metricas._calcular_score(_linha(valor_total=100_000)) == 10
    assert metricas._calcular_score(_linha(valor_total=500_000)) == 15


def test_score_nunca_conta_criterios_nao_disponiveis():
    # Empresa só com CNPJ confirmado e nada mais -> só os 15 pontos de CNPJ
    linha = _linha(cnpj_confirmado=True)
    assert metricas._calcular_score(linha) == 15


def test_projeto_ligado_iorm_reconhece_variacoes_reais():
    assert metricas._projeto_ligado_iorm("Usina da Dança 2009/2010") is True
    assert metricas._projeto_ligado_iorm("Espetáculo Usina da Dança") is True
    assert metricas._projeto_ligado_iorm(None) is False
    assert metricas._projeto_ligado_iorm("Projeto Qualquer Sem Relação") is False


def _linha_contactability(**overrides):
    base = {
        "tem_site": False,
        "tem_email_institucional": False,
        "tem_telefone_institucional": False,
        "tem_linkedin": False,
        "tem_instagram": False,
        "tem_evidencia_esg": False,
        "tem_evidencia_responsabilidade_social": False,
        "tem_instituto_fundacao": False,
        "tem_contato_profissional_confirmado": False,
    }
    base.update(overrides)
    return pd.Series(base)


def test_contactability_score_zero_sem_nada():
    assert metricas._calcular_contactability_score(_linha_contactability()) == 0


def test_contactability_score_soma_criterios():
    linha = _linha_contactability(tem_site=True, tem_email_institucional=True)
    assert metricas._calcular_contactability_score(linha) == 30


def test_contactability_score_limitado_a_100():
    linha = _linha_contactability(
        tem_site=True,
        tem_email_institucional=True,
        tem_telefone_institucional=True,
        tem_linkedin=True,
        tem_instagram=True,
        tem_evidencia_esg=True,
        tem_evidencia_responsabilidade_social=True,
        tem_instituto_fundacao=True,
        tem_contato_profissional_confirmado=True,
    )
    assert metricas._calcular_contactability_score(linha) == 100


def test_prioridade_prospeccao_combina_os_dois_scores():
    assert metricas._calcular_prioridade_prospeccao(iorm_score=60, contactability_score=40, tem_relevancia_iorm=False) == 50


def test_prioridade_prospeccao_bonus_relevancia():
    sem_bonus = metricas._calcular_prioridade_prospeccao(iorm_score=60, contactability_score=40, tem_relevancia_iorm=False)
    com_bonus = metricas._calcular_prioridade_prospeccao(iorm_score=60, contactability_score=40, tem_relevancia_iorm=True)
    assert com_bonus == sem_bonus + 10


def test_prioridade_prospeccao_nunca_passa_de_100():
    assert metricas._calcular_prioridade_prospeccao(iorm_score=100, contactability_score=100, tem_relevancia_iorm=True) == 100


def test_mesclar_empresa_sem_pesquisa_fica_com_contactability_zero():
    df_empresas = pd.DataFrame([{"id": 1, "razao_social": "Empresa X", "score": 80}])
    df_enriquecimento = pd.DataFrame()  # ninguém foi pesquisado ainda

    resultado = metricas.mesclar_empresas_e_enriquecimento(df_empresas, df_enriquecimento)

    assert resultado.loc[0, "contactability_score"] == 0
    assert resultado.loc[0, "pesquisado"] == False
    assert resultado.loc[0, "prioridade_prospeccao"] == 40  # 0.5*80 + 0.5*0


@pytest.fixture
def conexao_com_dados():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    banco.criar_tabelas(conn)

    id_iorm, _ = banco.obter_ou_criar_empresa(
        conn, {"cnpj": "11444777000161", "razao_social": "Empresa Parceira do IORM", "nome_fantasia": None,
               "cidade": "Guaíra", "estado": "SP", "status": None},
    )
    banco.inserir_ou_atualizar_incentivo(
        conn, {"empresa_id": id_iorm, "fonte": "SALIC", "tipo_incentivo": "Lei Rouanet",
               "projeto": "Usina da Dança 2024", "ano": 2024, "valor": 50000.0, "uf": "SP", "cidade": "Guaíra",
               "url_fonte": "https://x/1", "coletado_em": "2026-01-01", "nivel_confianca": "ALTO"},
    )
    id_outra, _ = banco.obter_ou_criar_empresa(
        conn, {"cnpj": "22555888000172", "razao_social": "Empresa Qualquer", "nome_fantasia": None,
               "cidade": "Osasco", "estado": "SP", "status": None},
    )
    banco.inserir_ou_atualizar_incentivo(
        conn, {"empresa_id": id_outra, "fonte": "SALIC", "tipo_incentivo": "Lei Rouanet",
               "projeto": "Projeto Qualquer Sem Relação", "ano": 2024, "valor": 30000.0, "uf": "SP", "cidade": "Osasco",
               "url_fonte": "https://x/2", "coletado_em": "2026-01-01", "nivel_confianca": "ALTO"},
    )
    yield conn
    conn.close()


def test_doacoes_ligadas_ao_iorm_encontra_so_projetos_do_iorm(conexao_com_dados):
    df = metricas.doacoes_ligadas_ao_iorm(conexao_com_dados)
    assert len(df) == 1
    assert df.iloc[0]["empresa"] == "Empresa Parceira do IORM"
    assert df.iloc[0]["ano"] == 2024


def test_resumo_por_cidade_inclui_cidade_sem_empresa(conexao_com_dados):
    df = metricas.resumo_por_cidade(conexao_com_dados, ["Guaíra", "Cidade Sem Empresa Nenhuma"])
    assert len(df) == 2
    linha_vazia = df[df["cidade"] == "Cidade Sem Empresa Nenhuma"].iloc[0]
    assert linha_vazia["empresas"] == 0
    assert linha_vazia["valor"] == 0


def test_carregar_empresas_com_territorios_classifica_regiao(conexao_com_dados):
    territorios = [{"tipo": "cidade", "valor": "Guaíra"}, {"tipo": "regiao_proxima", "valor": "Barretos"}]
    df = metricas.carregar_empresas(conexao_com_dados, territorios=territorios)
    linha_guaira = df[df["cidade"] == "Guaíra"].iloc[0]
    linha_osasco = df[df["cidade"] == "Osasco"].iloc[0]
    assert linha_guaira["regiao_iorm"] == "CIDADE_ATUACAO"
    assert linha_guaira["cidade_estrategica"] == True
    assert linha_osasco["regiao_iorm"] == "FORA_DA_REGIAO"
    assert linha_osasco["cidade_estrategica"] == False


def test_mesclar_empresa_pesquisada_calcula_prioridade():
    df_empresas = pd.DataFrame([{"id": 1, "razao_social": "Empresa X", "score": 80}])
    df_enriquecimento = pd.DataFrame(
        [
            {
                "empresa_id": 1,
                "tem_site": True,
                "tem_email_institucional": True,
                "tem_relevancia_iorm": True,
                "contactability_score": 30,
                "ultima_pesquisa_em": "2026-01-01T00:00:00",
                "ultima_pesquisa_status": "SUCESSO",
            }
        ]
    )

    resultado = metricas.mesclar_empresas_e_enriquecimento(df_empresas, df_enriquecimento)

    assert resultado.loc[0, "pesquisado"] == True
    assert resultado.loc[0, "contactability_score"] == 30
    assert resultado.loc[0, "prioridade_prospeccao"] == 65  # 0.5*80 + 0.5*30 + 10 (bonus)
