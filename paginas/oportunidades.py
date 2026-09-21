"""Oportunidades: recomendações do radar (não confundir com o pipeline do
CRM — aqui é "quem parece uma boa oportunidade", lá é "trabalho de
captação ativo").

Três abas:
  Oportunidades    -> só PROSPECTS (quem já tem relacionamento com o IORM
                      fica em Linha Cruzada).
  Radar por Região -> navegação POLO -> cidades da região -> empresas ->
                      ficha completa, tudo clicável.
  Linha Cruzada    -> empresas com relacionamento, com ficha completa."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from processamento import geografia, regiao
from paginas import _shared, radar_empresas


def _aba_oportunidades(df_mesclado: pd.DataFrame) -> None:
    _shared.secao(
        "Prospects recomendados", "⭐",
        "Ranking do radar (IORM Score + Contactability), apenas empresas ainda tratadas como prospect e dentro da "
        "Região IORM (cidades de atuação ou região dos polos).",
    )
    base = df_mesclado[
        df_mesclado["eh_prospect"]
        & df_mesclado["regiao_iorm"].isin(["CIDADE_ATUACAO", "REGIAO_PROXIMA"])
        & (df_mesclado["num_incentivos"] > 0)
    ].sort_values("prioridade_prospeccao", ascending=False)
    empresa_id = radar_empresas.tabela_selecionavel(
        base, "oportunidades", vazio="Nenhuma oportunidade encontrada com os dados atuais.",
    )
    radar_empresas.ficha_da_selecao(df_mesclado, empresa_id)

    _shared.secao("Rankings de prospects", "🏆")
    prospects = df_mesclado[df_mesclado["eh_prospect"]]
    col_a, col_b, col_c = st.columns(3)
    largura = {"Empresa": st.column_config.TextColumn(width=330)}
    with col_a:
        st.markdown("##### Top 10 — Valor histórico")
        top = prospects.sort_values("valor_total", ascending=False).head(10).copy()
        top["Valor (R$)"] = top["valor_total"].apply(_shared.formatar_moeda)
        st.dataframe(top[["razao_social", "cidade", "Valor (R$)"]].rename(columns={"razao_social": "Empresa", "cidade": "Cidade"}),
                     use_container_width=True, hide_index=True, column_config={**largura, "Valor (R$)": st.column_config.TextColumn(width=150)})
    with col_b:
        st.markdown("##### Top 10 — IORM Score")
        top = prospects.sort_values("score", ascending=False).head(10)
        st.dataframe(top[["razao_social", "cidade", "score"]].rename(columns={"razao_social": "Empresa", "cidade": "Cidade", "score": "Score"}),
                     use_container_width=True, hide_index=True, column_config=largura)
    with col_c:
        st.markdown("##### Top 10 — Prioridade de Prospecção")
        top = prospects.sort_values("prioridade_prospeccao", ascending=False).head(10)
        st.dataframe(top[["razao_social", "cidade", "prioridade_prospeccao"]].rename(
            columns={"razao_social": "Empresa", "cidade": "Cidade", "prioridade_prospeccao": "Prioridade"}),
            use_container_width=True, hide_index=True, column_config=largura)


# ------------------------------------------------------------------ região
def _contagem_por_cidade(df_mesclado: pd.DataFrame) -> pd.DataFrame:
    base = df_mesclado.copy()
    base["cidade_norm"] = base["cidade"].apply(regiao.normalizar_cidade)
    return base.groupby("cidade_norm").agg(
        prospects=("eh_prospect", "sum"), com_relacionamento=("linha_cruzada", "sum"), total=("id", "count"),
    )


def _resumo_polo(polo: str, cidades: list[str], contagem: pd.DataFrame) -> dict:
    chaves = [regiao.normalizar_cidade(c) for c in cidades]
    sub = contagem.reindex(chaves).fillna(0)
    return {"cidades": len(cidades), "prospects": int(sub["prospects"].sum()),
            "relacionamento": int(sub["com_relacionamento"].sum()), "total": int(sub["total"].sum())}


def _ir_para(polo: str | None = None, cidade: str | None = None) -> None:
    st.session_state["reg_polo"] = polo
    st.session_state["reg_cidade"] = cidade
    # Limpa seleções de linha antigas: senão a linha clicada antes "reaparece" e o clique volta a disparar.
    for chave in [k for k in st.session_state if str(k).startswith(("reg_tab_cidades_", "tabela_reg_"))]:
        del st.session_state[chave]


def _aba_radar_regiao(conexao, df_mesclado: pd.DataFrame, polos: list[str]) -> None:
    regiao_por_polo = geografia.municipios_por_polo(conexao)
    contagem = _contagem_por_cidade(df_mesclado)
    polo_atual = st.session_state.get("reg_polo")
    cidade_atual = st.session_state.get("reg_cidade")

    if not polos:
        _shared.estado_vazio("Nenhum polo cadastrado. Cadastre as cidades de atuação em Cérebro da OSC → Território.", "🗺️")
        return

    # -------- trilha de navegação (breadcrumb) + voltar
    trilha = ["Região"] + ([polo_atual] if polo_atual else []) + ([cidade_atual] if cidade_atual else [])
    st.markdown(" › ".join(f"**{t}**" if i == len(trilha) - 1 else t for i, t in enumerate(trilha)))
    if polo_atual:
        col_v1, col_v2, _ = st.columns([1.3, 1.6, 4])
        col_v1.button("← Visão regional", on_click=_ir_para, key="reg_voltar_regiao")
        if cidade_atual:
            col_v2.button(f"← Região de {polo_atual}", on_click=_ir_para, args=(polo_atual, None), key="reg_voltar_polo")

    # -------- nível 0: os 4 polos
    if not polo_atual:
        _shared.secao("Os polos do IORM", "🗺️", "Cada polo reúne as cidades da sua região (IBGE). Escolha um polo para explorar.")
        colunas = st.columns(min(4, len(polos)))
        for coluna, polo in zip(colunas, polos):
            cidades = [polo] + [l["municipio"] for l in regiao_por_polo.get(polo, [])]
            r = _resumo_polo(polo, cidades, contagem)
            with coluna:
                st.markdown(
                    f"<div class='iorm-cartao'><div class='iorm-cartao-titulo'>📍 {polo}</div>"
                    f"<div><b>{r['cidades']}</b> cidade(s) na região</div>"
                    f"<div><b>{r['prospects']}</b> prospect(s)</div>"
                    f"<div><b>{r['relacionamento']}</b> com relacionamento</div></div>",
                    unsafe_allow_html=True,
                )
                st.button(f"Ver região de {polo}", key=f"reg_polo_{polo}", on_click=_ir_para, args=(polo, None), use_container_width=True)
        outras = [l for l in geografia.listar(conexao) if l["origem"] == geografia.ORIGEM_IBGE]
        if outras:
            fonte = outras[0]["fonte"]
            st.caption(f"Fonte da região: {fonte}. Ipuã e Orlândia compartilham a mesma região imediata. "
                       "Municípios podem ser ajustados em Cérebro da OSC → Território.")
        else:
            st.markdown("<div class='iorm-aviso'>A região dos polos ainda não foi sincronizada com o IBGE. "
                        "Vá em Cérebro da OSC → Território → “Sincronizar região com o IBGE”.</div>", unsafe_allow_html=True)
        return

    # -------- nível 1: cidades da região do polo
    cidades_polo = [{"cidade": polo_atual, "papel": "Polo (cidade de atuação)", "fonte": "Cérebro da OSC"}] + [
        {"cidade": l["municipio"], "papel": "Cidade da região" + (" (manual)" if l["origem"] == geografia.ORIGEM_MANUAL else ""),
         "fonte": l["fonte"]}
        for l in regiao_por_polo.get(polo_atual, [])
    ]
    if not cidade_atual:
        _shared.secao(f"Região do polo {polo_atual}", "🏙️", "Clique em uma cidade para ver as empresas dela.")
        tabela = pd.DataFrame(cidades_polo)
        chaves = tabela["cidade"].apply(regiao.normalizar_cidade)
        sub = contagem.reindex(chaves).fillna(0).reset_index(drop=True)
        tabela["Prospects"] = sub["prospects"].astype(int)
        tabela["Com relacionamento"] = sub["com_relacionamento"].astype(int)
        tabela["Total de empresas"] = sub["total"].astype(int)
        exibir = tabela.rename(columns={"cidade": "Cidade", "papel": "Papel", "fonte": "Fonte"})[
            ["Cidade", "Papel", "Prospects", "Com relacionamento", "Total de empresas", "Fonte"]]
        evento = st.dataframe(
            exibir, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row",
            key=f"reg_tab_cidades_{polo_atual}", height=min(38 + 35 * len(exibir), 520),
            column_config={"Cidade": st.column_config.TextColumn(width=200), "Papel": st.column_config.TextColumn(width=210),
                           "Fonte": st.column_config.TextColumn(width=460)},
        )
        if evento.selection.rows:
            cidade_clicada = exibir.iloc[evento.selection.rows[0]]["Cidade"]
            _ir_para(polo_atual, cidade_clicada)
            st.rerun()
        st.caption("👆 Clique em uma cidade da tabela para ver as empresas dela.")
        col_a, col_b = st.columns(2)
        with col_a:
            _shared.grafico_barras(exibir.set_index("Cidade")["Prospects"], "Prospects")
        with col_b:
            _shared.grafico_barras(exibir.set_index("Cidade")["Com relacionamento"], "Com relacionamento", cor="#F0900F")
        return

    # -------- nível 2: empresas da cidade
    alvo = regiao.normalizar_cidade(cidade_atual)
    da_cidade = df_mesclado[df_mesclado["cidade"].apply(regiao.normalizar_cidade) == alvo]
    m1, m2, m3 = st.columns(3)
    m1.metric("Empresas na cidade", len(da_cidade))
    m2.metric("Prospects", int(da_cidade["eh_prospect"].sum()))
    m3.metric("Com relacionamento", int(da_cidade["linha_cruzada"].sum()))

    st.markdown("##### 🎯 Prospects")
    id_prospect = radar_empresas.tabela_selecionavel(
        da_cidade[da_cidade["eh_prospect"]].sort_values("prioridade_prospeccao", ascending=False),
        f"reg_prospects_{alvo}", vazio="Nenhum prospect nesta cidade.",
    )
    st.markdown("##### 🎗️ Empresas com relacionamento (Linha Cruzada)")
    id_cruzada = radar_empresas.tabela_selecionavel(
        da_cidade[da_cidade["linha_cruzada"]], f"reg_cruzada_{alvo}", radar_empresas._tabela_linha_cruzada,
        vazio="Nenhuma empresa com relacionamento nesta cidade.",
    )
    radar_empresas.ficha_da_selecao(df_mesclado, id_prospect or id_cruzada)


def _aba_linha_cruzada(df_mesclado: pd.DataFrame) -> None:
    _shared.secao(
        "Linha Cruzada", "🎗️",
        "Empresas com relação já comprovada com o IORM. Continuam na base; só ficam fora da lista de prospecção. "
        "Clique em uma linha para ver a ficha completa.",
    )
    df = df_mesclado[df_mesclado["linha_cruzada"]].sort_values("valor_total", ascending=False)
    empresa_id = radar_empresas.tabela_selecionavel(
        df, "oport_cruzada", radar_empresas._tabela_linha_cruzada, vazio="Nenhuma empresa com relacionamento identificada ainda.",
    )
    radar_empresas.ficha_da_selecao(df_mesclado, empresa_id)


def render() -> None:
    dados = _shared.carregar_dados_salic(str(_shared.CAMINHO_DB))
    df_mesclado = dados["df_mesclado"]
    polos = _shared.obter_territorio_osc()
    conexao = _shared.conectar()

    _shared.cabecalho("Oportunidades", "Prospects prioritários, radar por região e empresas com relacionamento.")

    aba_oportunidades, aba_regiao, aba_cruzada = st.tabs(["⭐ Oportunidades", "🗺️ Radar por Região", "🎗️ Linha Cruzada"], key="aba_oportunidades")
    with aba_oportunidades:
        _aba_oportunidades(df_mesclado)
    with aba_regiao:
        _aba_radar_regiao(conexao, df_mesclado, polos)
    with aba_cruzada:
        _aba_linha_cruzada(df_mesclado)

    conexao.close()
