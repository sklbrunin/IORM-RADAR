"""Oportunidades IORM: recomendações do radar (não confundir com o
pipeline do CRM — aqui é "quem parece uma boa oportunidade", lá é
"oportunidades que já viraram trabalho de captação ativo")."""
from __future__ import annotations

import streamlit as st

from paginas import _shared


def render() -> None:
    dados = _shared.carregar_dados_salic(str(_shared.CAMINHO_DB))
    df_mesclado, df_cidades = dados["df_mesclado"], dados["df_cidades"]

    _shared.cabecalho("Oportunidades", "Empresas com maior afinidade e maior facilidade de abordagem.")
    _shared.secao(
        "Empresas recomendadas", "⭐",
        "Gerado pelo radar (IORM Score + Contactability Score). Para acompanhar o trabalho de "
        "captação em andamento, use o Pipeline.",
    )

    df_oportunidades = df_mesclado[
        df_mesclado["cidade_estrategica"] & (df_mesclado["num_incentivos"] > 0)
    ].sort_values("prioridade_prospeccao", ascending=False)

    if df_oportunidades.empty:
        _shared.estado_vazio("Nenhuma oportunidade encontrada com os dados atuais.")
    else:
        exibir = df_oportunidades.copy()
        exibir["Projetos"] = exibir["projetos"].fillna("Não disponível")
        exibir["Valor histórico (R$)"] = exibir["valor_total"].apply(_shared.formatar_moeda)
        exibir = exibir.rename(
            columns={"razao_social": "Empresa", "cidade": "Cidade", "num_incentivos": "Nº de doações",
                     "score": "IORM Score", "contactability_score": "Contactability", "prioridade_prospeccao": "Prioridade"}
        )
        st.dataframe(
            exibir[["Empresa", "Cidade", "Valor histórico (R$)", "Nº de doações", "Projetos", "IORM Score", "Contactability", "Prioridade"]],
            use_container_width=True, hide_index=True, column_config=_shared.CONFIG_COLUNA_EMPRESA,
        )

    _shared.secao("Radar das 4 Cidades", "🗺️", "Ipuã, Guaíra, Miguelópolis e Orlândia — Miguelópolis aparece mesmo com 0 registros.")
    st.dataframe(
        df_cidades.assign(**{"Valor histórico (R$)": df_cidades["valor"].apply(_shared.formatar_moeda)}).rename(
            columns={"cidade": "Cidade", "empresas": "Empresas", "doacoes": "Doações"}
        )[["Cidade", "Empresas", "Valor histórico (R$)", "Doações"]],
        use_container_width=True, hide_index=True,
    )
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("#### Empresas por cidade")
        st.bar_chart(df_cidades.set_index("cidade")["empresas"])
    with col_b:
        st.markdown("#### Valor histórico por cidade (R$)")
        st.bar_chart(df_cidades.set_index("cidade")["valor"])

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
