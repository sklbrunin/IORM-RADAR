"""Inteligência de Contatos: visão consolidada de tudo que o módulo de
enriquecimento já encontrou, com exportação para a equipe de captação."""
from __future__ import annotations

import streamlit as st

from paginas import _shared


def render() -> None:
    dados = _shared.carregar_dados_salic(str(_shared.CAMINHO_DB))
    estatisticas_contatos = dados["estatisticas_contatos"]
    df_contatos_export = dados["df_contatos_export"]

    _shared.cabecalho("Contatos", "Presença digital, canais institucionais e pessoas encontradas.")

    _shared.secao("Visão geral", "📊")
    d1, d2, d3, d4, d5 = st.columns(5)
    d1.metric("Empresas pesquisadas", estatisticas_contatos["empresas_pesquisadas"])
    d2.metric("Sites encontrados", estatisticas_contatos["sites_encontrados"])
    d3.metric("LinkedIns encontrados", estatisticas_contatos["linkedins_encontrados"])
    d4.metric("Instagrams encontrados", estatisticas_contatos["instagrams_encontrados"])
    d5.metric("E-mails institucionais", estatisticas_contatos["emails_institucionais"])
    d6, d7, d8, d9, _ = st.columns(5)
    d6.metric("Telefones institucionais", estatisticas_contatos["telefones_institucionais"])
    d7.metric("Contatos profissionais", estatisticas_contatos["contatos_profissionais"])
    d8.metric("Empresas com ESG", estatisticas_contatos["empresas_com_esg"])
    d9.metric("Institutos/fundações", estatisticas_contatos["empresas_com_instituto_fundacao"])
    st.caption(f"Total de evidências registradas: {estatisticas_contatos['total_evidencias']}")

    _shared.secao("Contatos encontrados", "📇")
    if df_contatos_export.empty:
        _shared.estado_vazio(
            "Nenhum contato encontrado ainda. Use o botão Pesquisar/Atualizar na ficha de uma empresa "
            "(Radar de Empresas) para adicioná-la à fila de pesquisa.", "🔍",
        )
        return

    prioridade_sel = st.selectbox("Filtrar por prioridade", ["Todas", "PRIORIDADE_1", "PRIORIDADE_2", "PRIORIDADE_3", "Sem prioridade"])
    exibir = df_contatos_export.copy()
    if prioridade_sel == "Sem prioridade":
        exibir = exibir[exibir["prioridade"].isna()]
    elif prioridade_sel != "Todas":
        exibir = exibir[exibir["prioridade"] == prioridade_sel]

    colunas_texto = ["nome", "cargo", "departamento", "email", "telefone", "site", "linkedin", "instagram", "prioridade"]
    exibir_tabela = exibir.copy()
    for coluna in colunas_texto:
        exibir_tabela[coluna] = exibir_tabela[coluna].fillna("—")
    exibir_tabela = exibir_tabela.rename(
        columns={"empresa": "Empresa", "cidade": "Cidade", "estado": "UF", "nome": "Nome", "cargo": "Cargo",
                 "departamento": "Área", "email": "E-mail", "telefone": "Telefone", "site": "Site",
                 "linkedin": "LinkedIn", "instagram": "Instagram", "prioridade": "Prioridade",
                 "nivel_confianca": "Confiança", "fonte": "Fonte"}
    )
    st.dataframe(
        exibir_tabela[["Empresa", "Cidade", "UF", "Nome", "Cargo", "Área", "E-mail", "Telefone", "Site", "LinkedIn", "Instagram", "Prioridade", "Confiança", "Fonte"]],
        use_container_width=True, hide_index=True, column_config=_shared.CONFIG_COLUNA_EMPRESA,
    )

    colunas_exportacao = {
        "empresa": "Empresa", "cnpj": "CNPJ", "cidade": "Cidade", "estado": "UF", "nome": "Nome", "cargo": "Cargo",
        "departamento": "Departamento", "email": "E-mail", "telefone": "Telefone", "site": "Site",
        "linkedin": "LinkedIn", "instagram": "Instagram", "prioridade": "Prioridade", "nivel_confianca": "Confiança",
        "fonte": "Fonte", "url_fonte": "URL", "coletado_em": "Data da coleta",
    }
    df_export = exibir.copy()
    df_export["cnpj"] = df_export["cnpj"].apply(_shared.formatar_cnpj)
    df_export = df_export.rename(columns=colunas_exportacao)[list(colunas_exportacao.values())]
    csv_contatos = df_export.to_csv(index=False).encode("utf-8-sig")
    st.download_button("Baixar contatos (CSV)", data=csv_contatos, file_name="iorm_radar_contatos.csv", mime="text/csv")
