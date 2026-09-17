"""Inteligência de Contatos: visão consolidada de tudo que o módulo de
enriquecimento já encontrou, com exportação para a equipe de captação.

Duas tabelas propositalmente separadas (não uma tabela única de 14
colunas, que ficava ilegível): canais institucionais da EMPRESA (site,
e-mail, telefone, redes) e PESSOAS identificadas publicamente (nome,
cargo, departamento, perfil, fonte, confiança) — nunca misturando as
duas coisas."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from paginas import _shared

_CONFIG_LARGURA_EMPRESA = {
    "Empresa": st.column_config.TextColumn("Empresa", width="large"),
    "Nome": st.column_config.TextColumn("Nome", width="medium"),
    "Cargo": st.column_config.TextColumn("Cargo", width="large"),
    "Departamento": st.column_config.TextColumn("Departamento", width="medium"),
    "Fonte": st.column_config.TextColumn("Fonte", width="large"),
    "Site": st.column_config.LinkColumn("Site", display_text="Abrir ↗", width="small"),
    "LinkedIn": st.column_config.LinkColumn("LinkedIn", display_text="Abrir ↗", width="small"),
    "Instagram": st.column_config.LinkColumn("Instagram", display_text="Abrir ↗", width="small"),
    "Perfil": st.column_config.LinkColumn("Perfil", display_text="Abrir ↗", width="small"),
}


def _tabela_canais_empresa(df: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por EMPRESA: canais institucionais encontrados (não
    pessoas). E-mail/telefone só aparecem aqui quando o tipo de contato
    era institucional (não confunde com contato pessoal de alguém)."""
    agrupado = df.groupby(["empresa_id", "empresa", "cidade", "estado"], as_index=False).agg(
        site=("site", "first"),
        linkedin=("linkedin", "first"),
        instagram=("instagram", "first"),
        email=("email", lambda s: next((v for v in s if pd.notna(v)), None)),
        telefone=("telefone", lambda s: next((v for v in s if pd.notna(v)), None)),
        confianca=("nivel_confianca", "first"),
        fonte=("fonte", "first"),
    )
    for coluna in ["site", "linkedin", "instagram", "email", "telefone"]:
        agrupado[coluna] = agrupado[coluna].fillna("Não disponível")
    return agrupado.rename(
        columns={"empresa": "Empresa", "cidade": "Cidade", "estado": "UF", "email": "E-mail institucional",
                 "telefone": "Telefone institucional", "site": "Site", "linkedin": "LinkedIn",
                 "instagram": "Instagram", "confianca": "Confiança", "fonte": "Fonte"}
    )[["Empresa", "Cidade", "UF", "Site", "E-mail institucional", "Telefone institucional", "LinkedIn", "Instagram", "Confiança", "Fonte"]]


def _tabela_pessoas(df: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por PESSOA identificada publicamente — nunca um e-mail
    pessoal inventado; quando não há e-mail/telefone profissional
    encontrado especificamente para essa pessoa, mostra "Não disponível"."""
    pessoas = df[df["tipo_contato"] == "PESSOA_CARGO"].copy()
    if pessoas.empty:
        return pessoas
    pessoas["nome"] = pessoas["nome"].fillna("Nome não identificado")
    pessoas["cargo"] = pessoas["cargo"].fillna("Não disponível")
    pessoas["departamento"] = pessoas["departamento"].fillna("Não disponível")
    pessoas["email_profissional"] = "Não disponível"
    pessoas["telefone_profissional"] = "Não disponível"
    pessoas["perfil"] = pessoas["valor"]
    return pessoas.rename(
        columns={"empresa": "Empresa", "nome": "Nome", "cargo": "Cargo", "departamento": "Departamento",
                 "perfil": "Perfil", "email_profissional": "E-mail profissional",
                 "telefone_profissional": "Telefone profissional", "nivel_confianca": "Confiança",
                 "fonte": "Fonte", "coletado_em": "Data da pesquisa"}
    )[["Empresa", "Nome", "Cargo", "Departamento", "Perfil", "E-mail profissional", "Telefone profissional",
       "Confiança", "Fonte", "Data da pesquisa"]]


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
    d7.metric("Pessoas identificadas", estatisticas_contatos["contatos_profissionais"])
    d8.metric("Empresas com ESG", estatisticas_contatos["empresas_com_esg"])
    d9.metric("Institutos/fundações", estatisticas_contatos["empresas_com_instituto_fundacao"])
    st.caption(f"Total de evidências registradas: {estatisticas_contatos['total_evidencias']}")

    if df_contatos_export.empty:
        _shared.estado_vazio(
            "Nenhum contato encontrado ainda. Use o botão Pesquisar/Atualizar na ficha de uma empresa "
            "(Radar de Empresas) para adicioná-la à fila de pesquisa.", "🔍",
        )
        return

    aba_empresas, aba_pessoas = st.tabs(["🏢 Canais da empresa", "👤 Pessoas identificadas"])

    with aba_empresas:
        _shared.secao("Canais institucionais", "🏢", "Site, e-mail, telefone e redes oficiais da empresa — não pessoas.")
        tabela_empresas = _tabela_canais_empresa(df_contatos_export)
        st.dataframe(
            tabela_empresas, use_container_width=True, hide_index=True,
            column_config=_CONFIG_LARGURA_EMPRESA, height=min(35 + 36 * len(tabela_empresas), 560),
        )

    with aba_pessoas:
        _shared.secao(
            "Pessoas identificadas publicamente", "👤",
            "Prioriza cargos em Responsabilidade Social/ESG/Sustentabilidade/Relações Institucionais/"
            "Marketing/Comunicação/Fiscal/Diretoria — nunca presume cargo, só o que a fonte já mostrava.",
        )
        prioridade_sel = st.selectbox("Filtrar por prioridade", ["Todas", "PRIORIDADE_1", "PRIORIDADE_2", "PRIORIDADE_3", "Sem prioridade"])
        base_pessoas = df_contatos_export.copy()
        if prioridade_sel == "Sem prioridade":
            base_pessoas = base_pessoas[base_pessoas["prioridade"].isna()]
        elif prioridade_sel != "Todas":
            base_pessoas = base_pessoas[base_pessoas["prioridade"] == prioridade_sel]

        tabela_pessoas = _tabela_pessoas(base_pessoas)
        if tabela_pessoas.empty:
            _shared.estado_vazio("Nenhuma pessoa identificada ainda com esse filtro.", "👤")
        else:
            st.dataframe(
                tabela_pessoas, use_container_width=True, hide_index=True,
                column_config=_CONFIG_LARGURA_EMPRESA, height=min(35 + 36 * len(tabela_pessoas), 560),
            )

    colunas_exportacao = {
        "empresa": "Empresa", "cnpj": "CNPJ", "cidade": "Cidade", "estado": "UF", "nome": "Nome", "cargo": "Cargo",
        "departamento": "Departamento", "email": "E-mail", "telefone": "Telefone", "site": "Site",
        "linkedin": "LinkedIn", "instagram": "Instagram", "prioridade": "Prioridade", "nivel_confianca": "Confiança",
        "fonte": "Fonte", "url_fonte": "URL", "coletado_em": "Data da coleta",
    }
    df_export = df_contatos_export.copy()
    df_export["cnpj"] = df_export["cnpj"].apply(_shared.formatar_cnpj)
    df_export = df_export.rename(columns=colunas_exportacao)[list(colunas_exportacao.values())]
    csv_contatos = df_export.to_csv(index=False).encode("utf-8-sig")
    st.download_button("⬇ Baixar contatos (CSV)", data=csv_contatos, file_name="iorm_radar_contatos.csv", mime="text/csv")
