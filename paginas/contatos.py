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

from processamento import enriquecimento
from paginas import _shared

_CONFIG_LARGURA_EMPRESA = {
    "Empresa": st.column_config.TextColumn("Empresa", width=600),
    "Nome": st.column_config.TextColumn("Nome", width=280),
    "Cargo": st.column_config.TextColumn("Cargo", width=620),
    "Fonte": st.column_config.TextColumn("Fonte", width=460),
    "Site": st.column_config.LinkColumn("Site", display_text="Abrir ↗", width="small"),
    "LinkedIn": st.column_config.LinkColumn("LinkedIn", display_text="Abrir ↗", width="small"),
    "Instagram": st.column_config.LinkColumn("Instagram", display_text="Abrir ↗", width="small"),
    "Perfil (LinkedIn)": st.column_config.LinkColumn("Perfil (LinkedIn)", display_text="Abrir ↗", width=130),
    "Link da fonte": st.column_config.LinkColumn("Link da fonte", display_text="Abrir ↗", width=120),
    "Área": st.column_config.TextColumn("Área", width=190),
    "Área do e-mail": st.column_config.TextColumn("Área do e-mail", width=170),
    "E-mail institucional": st.column_config.TextColumn("E-mail institucional", width=280),
    "E-mail profissional": st.column_config.TextColumn("E-mail profissional", width=190),
    "Telefone institucional": st.column_config.TextColumn("Telefone institucional", width=180),
    "Telefone profissional": st.column_config.TextColumn("Telefone profissional", width=180),
    "Tipo": st.column_config.TextColumn("Tipo", width=110),
    "Prioridade": st.column_config.TextColumn("Prioridade", width=130),
    "Confiança": st.column_config.TextColumn("Confiança", width=110),
    "Data da pesquisa": st.column_config.TextColumn("Data da pesquisa", width=200),
}


def _tabela_canais_empresa(df: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por EMPRESA: canais institucionais encontrados (não
    pessoas). E-mail/telefone só aparecem aqui quando o tipo de contato
    era institucional (não confunde com contato pessoal de alguém). A
    "área" do e-mail descreve a caixa postal (financeiro@, rh@...), nunca
    uma pessoa."""
    agrupado = df.groupby(["empresa_id", "empresa", "cidade", "estado"], as_index=False).agg(
        site=("site", "first"),
        linkedin=("linkedin", "first"),
        instagram=("instagram", "first"),
        email=("email", lambda s: next((v for v in s if pd.notna(v)), None)),
        telefone=("telefone", lambda s: next((v for v in s if pd.notna(v)), None)),
        confianca=("nivel_confianca", "first"),
        fonte=("fonte", "first"),
    )
    agrupado["area_email"] = agrupado["email"].apply(
        lambda e: (enriquecimento.area_do_email(e) or "Não identificada") if isinstance(e, str) and e else "—")
    for coluna in ["site", "linkedin", "instagram", "email", "telefone"]:
        agrupado[coluna] = agrupado[coluna].fillna("Não disponível")
    agrupado["tipo"] = "Institucional"
    return agrupado.rename(
        columns={"empresa": "Empresa", "cidade": "Cidade", "estado": "UF", "email": "E-mail institucional",
                 "area_email": "Área do e-mail", "telefone": "Telefone institucional", "site": "Site", "linkedin": "LinkedIn",
                 "instagram": "Instagram", "confianca": "Confiança", "fonte": "Fonte", "tipo": "Tipo"}
    )[["Empresa", "Cidade", "UF", "Tipo", "Site", "E-mail institucional", "Área do e-mail", "Telefone institucional",
       "LinkedIn", "Instagram", "Confiança", "Fonte"]]


def _tabela_pessoas(df: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por PESSOA identificada publicamente — nunca um e-mail
    pessoal inventado; quando não há e-mail/telefone profissional
    encontrado especificamente para essa pessoa, mostra "Não disponível".
    O link "Perfil" só existe quando a fonte trouxe um perfil público (ex:
    LinkedIn); pessoas do quadro societário da Receita não têm perfil."""
    pessoas = df[df["tipo_contato"] == "PESSOA_CARGO"].copy()
    if pessoas.empty:
        return pessoas
    pessoas["nome"] = pessoas["nome"].fillna("Nome não identificado")
    pessoas["cargo"] = pessoas["cargo"].fillna("Não disponível")
    pessoas["departamento"] = pessoas.apply(
        lambda l: l["departamento"] if pd.notna(l["departamento"]) and l["departamento"]
        else (enriquecimento.classificar_area(l["cargo"]) or "Não disponível"), axis=1)
    pessoas["perfil"] = pessoas["valor"].apply(lambda v: v if isinstance(v, str) and v.startswith("http") else None)
    pessoas["email_profissional"] = pessoas["valor"].apply(
        lambda v: v if isinstance(v, str) and "@" in v and not v.startswith("http") else "Não disponível")
    pessoas["telefone_profissional"] = "Não disponível"
    pessoas["prioridade"] = pessoas["prioridade"].fillna("—")
    return pessoas.rename(
        columns={"empresa": "Empresa", "nome": "Nome", "cargo": "Cargo", "departamento": "Área", "prioridade": "Prioridade",
                 "perfil": "Perfil (LinkedIn)", "email_profissional": "E-mail profissional",
                 "telefone_profissional": "Telefone profissional", "nivel_confianca": "Confiança",
                 "fonte": "Fonte", "url_fonte": "Link da fonte", "coletado_em": "Data da pesquisa"}
    )[["Empresa", "Nome", "Cargo", "Área", "Prioridade", "Perfil (LinkedIn)", "E-mail profissional", "Telefone profissional",
       "Confiança", "Fonte", "Link da fonte", "Data da pesquisa"]]


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

    aba_empresas, aba_pessoas = st.tabs(["🏢 Canais da empresa", "👤 Pessoas identificadas"], key="aba_contatos")

    with aba_empresas:
        _shared.secao("Canais institucionais", "🏢", "Site, e-mail, telefone e redes oficiais da empresa — não pessoas.")
        tabela_empresas = _tabela_canais_empresa(df_contatos_export)
        busca_emp = st.text_input("Buscar empresa", key="busca_canais", placeholder="Digite parte do nome da empresa")
        if busca_emp:
            tabela_empresas = tabela_empresas[tabela_empresas["Empresa"].str.contains(busca_emp, case=False, na=False)]
        st.caption(f"{len(tabela_empresas)} empresa(s) com canais registrados.")
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
        col_f1, col_f2, col_f3 = st.columns([2, 1.5, 1.5])
        busca = col_f1.text_input("Buscar por empresa, nome ou cargo", key="busca_pessoas")
        area_sel = col_f2.selectbox("Área", ["Todas"] + [a for a, _ in enriquecimento.AREAS_PROFISSIONAIS])
        prioridade_sel = col_f3.selectbox("Prioridade", ["Todas", "PRIORIDADE_1", "PRIORIDADE_2", "PRIORIDADE_3", "Sem prioridade"])
        base_pessoas = df_contatos_export.copy()
        if prioridade_sel == "Sem prioridade":
            base_pessoas = base_pessoas[base_pessoas["prioridade"].isna()]
        elif prioridade_sel != "Todas":
            base_pessoas = base_pessoas[base_pessoas["prioridade"] == prioridade_sel]

        tabela_pessoas = _tabela_pessoas(base_pessoas)
        if not tabela_pessoas.empty:
            if area_sel != "Todas":
                tabela_pessoas = tabela_pessoas[tabela_pessoas["Área"] == area_sel]
            if busca:
                alvo = (tabela_pessoas["Empresa"] + " " + tabela_pessoas["Nome"] + " " + tabela_pessoas["Cargo"])
                tabela_pessoas = tabela_pessoas[alvo.str.contains(busca, case=False, na=False)]
        if tabela_pessoas.empty:
            _shared.estado_vazio("Nenhuma pessoa identificada ainda com esse filtro.", "👤")
        else:
            st.caption(f"{len(tabela_pessoas)} pessoa(s). Origem \"quadro societário — Receita Federal\" = sócio/administrador registrado no CNPJ, não necessariamente responsável por ESG/marketing.")
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
