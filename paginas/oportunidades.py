"""Oportunidades IORM: recomendações do radar (não confundir com o
pipeline do CRM — aqui é "quem parece uma boa oportunidade", lá é
"oportunidades que já viraram trabalho de captação ativo").

Três abas:
  Oportunidades   -> lista principal de prospecção (exclui quem já tem
                     relação direta e comprovada com o IORM — ver Linha
                     Cruzada).
  Radar por Região -> navegação por Região IORM/cidade (não só um número,
                     dá pra clicar e explorar a lista de empresas).
  Linha Cruzada   -> empresas que já apoiaram um projeto do próprio IORM.
                     Não são removidas da base — só apresentadas à parte,
                     pra não virarem "prospecção repetida" pro captador."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from processamento import metricas, regiao
from paginas import _shared


def _tabela_empresas(df: pd.DataFrame, colunas_extra: dict | None = None) -> pd.DataFrame:
    exibir = df.copy()
    exibir["Projetos"] = exibir["projetos"].fillna("Não disponível")
    exibir["Valor histórico (R$)"] = exibir["valor_total"].apply(_shared.formatar_moeda)
    exibir["Região IORM"] = exibir.get("regiao_iorm", pd.Series(dtype=str)).apply(
        lambda c: regiao.rotulo(c) if pd.notna(c) else "Não classificada"
    )
    exibir = exibir.rename(
        columns={"razao_social": "Empresa", "cidade": "Cidade", "num_incentivos": "Nº de doações",
                 "score": "IORM Score", "contactability_score": "Contactability", "prioridade_prospeccao": "Prioridade"}
    )
    return exibir[["Empresa", "Cidade", "Região IORM", "Valor histórico (R$)", "Nº de doações", "Projetos", "IORM Score", "Contactability", "Prioridade"]]


def _aba_oportunidades(df_mesclado: pd.DataFrame) -> None:
    _shared.secao(
        "Empresas recomendadas", "⭐",
        "Gerado pelo radar (IORM Score + Contactability Score). Empresas que já apoiaram um projeto do "
        "próprio IORM aparecem em Linha Cruzada, não aqui — evita repetir prospecção de quem já é parceiro.",
    )

    df_oportunidades = df_mesclado[
        df_mesclado["regiao_iorm"].isin(["CIDADE_ATUACAO", "REGIAO_PROXIMA"])
        & (df_mesclado["num_incentivos"] > 0)
        & (~df_mesclado["projeto_iorm"])
    ].sort_values("prioridade_prospeccao", ascending=False)

    if df_oportunidades.empty:
        _shared.estado_vazio("Nenhuma oportunidade encontrada com os dados atuais.")
    else:
        st.dataframe(
            _tabela_empresas(df_oportunidades), use_container_width=True, hide_index=True,
            column_config=_shared.CONFIG_COLUNA_EMPRESA,
        )

    _shared.secao("Rankings", "🏆")
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.markdown("##### Top 10 — Valor histórico")
        top_valor = df_mesclado.sort_values("valor_total", ascending=False).head(10).copy()
        top_valor["Valor (R$)"] = top_valor["valor_total"].apply(_shared.formatar_moeda)
        st.dataframe(top_valor[["razao_social", "cidade", "Valor (R$)"]].rename(columns={"razao_social": "Empresa", "cidade": "Cidade"}), use_container_width=True, hide_index=True)
    with col_b:
        st.markdown("##### Top 10 — IORM Score")
        top_score = df_mesclado.sort_values("score", ascending=False).head(10)
        st.dataframe(top_score[["razao_social", "cidade", "score"]].rename(columns={"razao_social": "Empresa", "cidade": "Cidade", "score": "Score"}), use_container_width=True, hide_index=True)
    with col_c:
        st.markdown("##### Top 10 — Prioridade de Prospecção")
        top_prioridade = df_mesclado.sort_values("prioridade_prospeccao", ascending=False).head(10)
        st.dataframe(top_prioridade[["razao_social", "cidade", "prioridade_prospeccao"]].rename(columns={"razao_social": "Empresa", "cidade": "Cidade", "prioridade_prospeccao": "Prioridade"}), use_container_width=True, hide_index=True)


def _aba_radar_regiao(conexao, df_mesclado: pd.DataFrame, territorios: list[dict]) -> None:
    _shared.secao(
        "Radar por Região IORM", "🗺️",
        "Cidades de atuação, região próxima e interesse estratégico continuam existindo como camadas — "
        "mas não são um limite rígido. Escolha uma camada ou uma cidade específica para explorar.",
    )

    grupos = regiao.cidades_por_camada(territorios)
    contagem_regiao = df_mesclado["regiao_iorm"].value_counts().to_dict() if "regiao_iorm" in df_mesclado.columns else {}
    col_a, col_b, col_c = st.columns(3)
    col_a.metric(f"🎯 {regiao.rotulo('CIDADE_ATUACAO')}", contagem_regiao.get("CIDADE_ATUACAO", 0))
    col_b.metric(f"📍 {regiao.rotulo('REGIAO_PROXIMA')}", contagem_regiao.get("REGIAO_PROXIMA", 0))
    col_c.metric(f"🔶 {regiao.rotulo('INTERESSE_ESTRATEGICO')}", contagem_regiao.get("INTERESSE_ESTRATEGICO", 0))

    opcoes_camada = ["Todas as camadas"] + [regiao.rotulo(c) for c in ["CIDADE_ATUACAO", "REGIAO_PROXIMA", "INTERESSE_ESTRATEGICO"]]
    camada_escolhida = st.selectbox("Filtrar por camada", opcoes_camada)

    if camada_escolhida == "Todas as camadas":
        todas_cidades = sorted(set(grupos["CIDADE_ATUACAO"] + grupos["REGIAO_PROXIMA"] + grupos["INTERESSE_ESTRATEGICO"]))
        camada_chave = None
    else:
        camada_chave = next(c for c in ["CIDADE_ATUACAO", "REGIAO_PROXIMA", "INTERESSE_ESTRATEGICO"] if regiao.rotulo(c) == camada_escolhida)
        todas_cidades = grupos[camada_chave]

    cidade_escolhida = st.selectbox("Selecionar cidade", ["Todas as cidades desta camada"] + todas_cidades)

    if not todas_cidades:
        _shared.estado_vazio(
            "Nenhuma cidade cadastrada nesta camada ainda. Cadastre em Cérebro da OSC → Território.", "🗺️"
        )
        return

    df_resumo = metricas.resumo_por_cidade(conexao, todas_cidades)
    st.dataframe(
        df_resumo.assign(**{"Valor histórico (R$)": df_resumo["valor"].apply(_shared.formatar_moeda)}).rename(
            columns={"cidade": "Cidade", "empresas": "Empresas", "doacoes": "Doações"}
        )[["Cidade", "Empresas", "Valor histórico (R$)", "Doações"]],
        use_container_width=True, hide_index=True,
    )
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("#### Empresas por cidade")
        st.bar_chart(df_resumo.set_index("cidade")["empresas"])
    with col_b:
        st.markdown("#### Valor histórico por cidade (R$)")
        st.bar_chart(df_resumo.set_index("cidade")["valor"])

    st.markdown("##### Empresas — clique para explorar")
    if cidade_escolhida == "Todas as cidades desta camada":
        df_filtrado = df_mesclado[df_mesclado["cidade"].isin(todas_cidades)]
    else:
        df_filtrado = df_mesclado[df_mesclado["cidade"] == cidade_escolhida]

    if df_filtrado.empty:
        _shared.estado_vazio("Nenhuma empresa encontrada nesta cidade/camada ainda.")
    else:
        st.dataframe(
            _tabela_empresas(df_filtrado).sort_values("Prioridade", ascending=False),
            use_container_width=True, hide_index=True, column_config=_shared.CONFIG_COLUNA_EMPRESA,
        )


def _aba_linha_cruzada(conexao, df_mesclado: pd.DataFrame) -> None:
    _shared.secao(
        "Linha Cruzada", "🎗️",
        "Empresas que já têm relação direta e comprovada com o IORM (apoiaram um projeto do próprio "
        "instituto). Continuam na base normalmente — só ficam separadas da lista de prospecção pra você "
        "não receber a mesma empresa de novo como se fosse uma novidade.",
    )
    df_doacoes = metricas.doacoes_ligadas_ao_iorm(conexao)
    if df_doacoes.empty:
        _shared.estado_vazio("Nenhuma empresa com relação direta identificada com o IORM ainda.", "🎗️")
        return

    exibir = df_doacoes.copy()
    exibir["Valor (R$)"] = exibir["valor"].apply(_shared.formatar_moeda)
    exibir["ano"] = exibir["ano"].fillna("Não disponível")
    exibir["situacao"] = "Relação já identificada com o IORM"
    st.dataframe(
        exibir.rename(
            columns={"empresa": "Empresa", "cidade": "Cidade", "ano": "Ano", "projeto": "Projeto/histórico",
                     "fonte": "Fonte", "situacao": "Situação do relacionamento"}
        )[["Empresa", "Cidade", "Projeto/histórico", "Ano", "Valor (R$)", "Fonte", "Situação do relacionamento"]],
        use_container_width=True, hide_index=True,
    )
    st.caption(
        f"{df_doacoes['empresa_id'].nunique()} empresa(s) com relação direta identificada, "
        f"{len(df_doacoes)} registro(s) de doação ligada a um projeto do IORM."
    )
    st.markdown(
        "Para ver a ficha completa (contatos, scores, evidências) de qualquer uma dessas empresas, "
        "abra **Radar de Empresas** e busque pelo nome."
    )


def render() -> None:
    dados = _shared.carregar_dados_salic(str(_shared.CAMINHO_DB))
    df_mesclado = dados["df_mesclado"]
    territorios = dados.get("territorios_osc") or []
    conexao = _shared.conectar()

    _shared.cabecalho("Oportunidades", "Empresas com maior afinidade e maior facilidade de abordagem.")

    aba_oportunidades, aba_regiao, aba_cruzada = st.tabs(["⭐ Oportunidades", "🗺️ Radar por Região", "🎗️ Linha Cruzada"])
    with aba_oportunidades:
        _aba_oportunidades(df_mesclado)
    with aba_regiao:
        _aba_radar_regiao(conexao, df_mesclado, territorios)
    with aba_cruzada:
        _aba_linha_cruzada(conexao, df_mesclado)

    conexao.close()
