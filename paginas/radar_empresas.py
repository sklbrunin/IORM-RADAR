"""Radar de Empresas: lista filtrável, ficha completa por empresa e a
ponte para o CRM ("Adicionar ao CRM")."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from processamento import busca_providers, crm, enriquecimento, filtros, geografia, metricas, pesquisa_empresa, regiao, relacionamento
from paginas import _shared


def _v(valor, padrao: str = "Não disponível") -> str:
    """Valor de célula do pandas -> texto seguro: NaN/None/vazio viram o texto padrão (nunca "nan"/"None")."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)) or str(valor).strip() in ("", "nan", "None"):
        return padrao
    return str(valor)


def _tabela_para_exibicao(df: pd.DataFrame) -> pd.DataFrame:
    exibir = df.copy()
    exibir["CNPJ"] = exibir["cnpj"].apply(_shared.formatar_cnpj)
    exibir["Confiança"] = exibir["nivel_confianca"].fillna("Não disponível")
    exibir["Valor histórico (R$)"] = exibir["valor_total"].apply(_shared.formatar_moeda)
    exibir["Região IORM"] = exibir["regiao_iorm"].apply(lambda c: regiao.rotulo(c) if pd.notna(c) else "Não classificada")
    exibir = exibir.rename(
        columns={
            "razao_social": "Empresa",
            "cidade": "Cidade",
            "estado": "UF",
            "num_incentivos": "Nº de doações",
            "score": "IORM Score",
            "contactability_score": "Contactability",
            "prioridade_prospeccao": "Prioridade",
            "tipo_dado": "Tipo de dado",
        }
    )
    exibir["Cidade"] = exibir["Cidade"].fillna("Não disponível")
    return exibir[
        [
            "Empresa", "CNPJ", "Cidade", "UF", "Região IORM", "Valor histórico (R$)", "Nº de doações",
            "IORM Score", "Contactability", "Prioridade", "Confiança", "Tipo de dado",
        ]
    ]


def _projetos_do_iorm(projetos) -> str:
    """Só os programas do IORM que a empresa apoiou (sem repetir variações de ano) — a lista completa de
    projetos de qualquer tipo fica na ficha."""
    if not isinstance(projetos, str) or not projetos:
        return "Não disponível"
    vistos, saida = set(), []
    for projeto in projetos.split(","):
        projeto = projeto.strip()
        for programa in metricas.PROGRAMAS_IORM:
            if programa in projeto.lower() and programa not in vistos:
                vistos.add(programa)
                saida.append(programa.title().replace("Da ", "da ").replace("Do ", "do "))
    return ", ".join(saida) if saida else "Não disponível"


def _tabela_linha_cruzada(df: pd.DataFrame) -> pd.DataFrame:
    exibir = df.copy()
    exibir["CNPJ"] = exibir["cnpj"].apply(_shared.formatar_cnpj)
    exibir["Valor histórico (R$)"] = exibir["valor_total"].apply(_shared.formatar_moeda)
    exibir["Região IORM"] = exibir["regiao_iorm"].apply(lambda c: regiao.rotulo(c) if pd.notna(c) else "Não classificada")
    exibir["Vínculo"] = exibir["relacionamento_tipo"].apply(
        lambda t: relacionamento.ROTULOS_TIPO.get(t, "Apoiou projeto do IORM (dado do SALIC)") if pd.notna(t) else "Apoiou projeto do IORM (dado do SALIC)"
    )
    exibir["Projetos"] = exibir["projetos"].apply(_projetos_do_iorm)
    exibir["Nome fantasia"] = exibir["nome_fantasia"].fillna("Não disponível")
    exibir = exibir.rename(columns={"razao_social": "Empresa", "cidade": "Cidade", "estado": "UF", "num_incentivos": "Nº de doações"})
    return exibir[["Empresa", "Nome fantasia", "CNPJ", "Cidade", "UF", "Região IORM", "Vínculo", "Valor histórico (R$)", "Nº de doações", "Projetos"]]


def configuracao_colunas() -> dict:
    """Larguras em pixels pensadas para os nomes mais longos da base (razões
    sociais de até ~90 caracteres) — o detalhe completo sempre aparece na ficha."""
    return {
        "Empresa": st.column_config.TextColumn("Empresa", width=640),
        "Nome fantasia": st.column_config.TextColumn("Nome fantasia", width=220),
        "CNPJ": st.column_config.TextColumn("CNPJ", width=150),
        "Cidade": st.column_config.TextColumn("Cidade", width=170),
        "UF": st.column_config.TextColumn("UF", width=55),
        "Região IORM": st.column_config.TextColumn("Região IORM", width=150),
        "Vínculo": st.column_config.TextColumn("Vínculo", width=290),
        "Valor histórico (R$)": st.column_config.TextColumn("Valor histórico (R$)", width=170),
        "Nº de doações": st.column_config.NumberColumn("Nº de doações", width=115),
        "IORM Score": st.column_config.NumberColumn("IORM Score", width=105),
        "Contactability": st.column_config.NumberColumn("Contactability", width=120),
        "Prioridade": st.column_config.NumberColumn("Prioridade", width=100),
        "Confiança": st.column_config.TextColumn("Confiança", width=110),
        "Tipo de dado": st.column_config.TextColumn("Tipo de dado", width=115),
        "Projetos": st.column_config.TextColumn("Projetos do IORM apoiados", width=330),
    }


def tabela_selecionavel(df: pd.DataFrame, chave: str, formatador=None, vazio: str = "Nenhuma empresa encontrada.") -> int | None:
    """Tabela em que CLICAR numa linha seleciona a empresa (devolve o id).
    Reutilizada pelo Radar, Linha Cruzada e Radar por Região."""
    if df.empty:
        _shared.estado_vazio(vazio)
        return None
    df = df.reset_index(drop=True)
    exibir = (formatador or _tabela_para_exibicao)(df)
    evento = st.dataframe(
        exibir, use_container_width=True, hide_index=True, column_config=configuracao_colunas(),
        on_select="rerun", selection_mode="single-row", key=f"tabela_{chave}", height=min(38 + 35 * len(exibir), 460),
    )
    linhas = evento.selection.rows if evento is not None else []
    st.caption("👆 Clique em uma linha para abrir a ficha completa da empresa logo abaixo.")
    return int(df.iloc[linhas[0]]["id"]) if linhas else None


def ficha_da_selecao(df_mesclado: pd.DataFrame, empresa_id: int | None) -> None:
    if empresa_id is None:
        return
    _shared.secao("Ficha da empresa", "🔎")
    _renderizar_ficha(df_mesclado, empresa_id)

def _renderizar_filtros(df_empresas: pd.DataFrame) -> pd.DataFrame:
    estados_disponiveis = ["Todos"] + sorted(df_empresas["estado"].dropna().unique().tolist())
    cidades_disponiveis = ["Todas"] + sorted(df_empresas["cidade"].dropna().unique().tolist())

    for chave, valor in filtros.FILTROS_PADRAO.items():
        chave_form = f"form_{chave}"
        if chave_form not in st.session_state:
            st.session_state[chave_form] = valor
    if "filtros_aplicados" not in st.session_state:
        st.session_state["filtros_aplicados"] = filtros.FILTROS_PADRAO.copy()
    if st.session_state.get("_limpar_filtros_pendente"):
        for chave, valor in filtros.FILTROS_PADRAO.items():
            st.session_state[f"form_{chave}"] = valor
        st.session_state["filtros_aplicados"] = filtros.FILTROS_PADRAO.copy()
        st.session_state["_limpar_filtros_pendente"] = False

    st.sidebar.markdown("---")
    st.sidebar.subheader("Filtros — Radar de Empresas")
    regioes_disponiveis = ["Todas"] + [c for c in regiao.CAMADAS if c in df_empresas.get("regiao_iorm", pd.Series(dtype=str)).unique()]
    with st.sidebar.form("form_filtros"):
        st.selectbox("Estado", estados_disponiveis, key="form_estado")
        st.selectbox("Cidade", cidades_disponiveis, key="form_cidade")
        st.selectbox(
            "Região IORM", regioes_disponiveis, key="form_regiao",
            format_func=lambda r: "Todas" if r == "Todas" else regiao.rotulo(r),
            help="Cidade de atuação / Região próxima / Interesse estratégico / Fora da região — configurado em Cérebro da OSC → Território.",
        )
        st.slider("Score mínimo (IORM Score)", 0, 100, key="form_score_min")
        st.selectbox("CNPJ", ["Todos", "Confirmado", "Não confirmado"], key="form_cnpj")
        st.selectbox("Tipo de informação", ["Todos", "Agregado", "Detalhado"], key="form_tipo")
        st.selectbox(
            "Ordenar por", ["IORM Score", "Valor histórico", "Número de doações", "Nome", "Cidade"], key="form_ordenar"
        )
        col_a, col_b = st.columns(2)
        aplicar = col_a.form_submit_button("Aplicar Filtros", use_container_width=True)
        limpar = col_b.form_submit_button("Limpar Filtros", use_container_width=True)

    if aplicar:
        st.session_state["filtros_aplicados"] = {chave: st.session_state[f"form_{chave}"] for chave in filtros.FILTROS_PADRAO}
    if limpar:
        st.session_state["_limpar_filtros_pendente"] = True
        st.rerun()

    st.sidebar.caption("A tabela só muda depois de clicar em **Aplicar Filtros**.")
    return filtros.aplicar_filtros(df_empresas, st.session_state["filtros_aplicados"])


def _acao_adicionar_ao_crm(conexao, empresa) -> None:
    ja_tem = crm.empresa_ja_tem_oportunidade_aberta(conexao, int(empresa["id"]))
    if ja_tem:
        st.info("Esta empresa já está no CRM com uma oportunidade em aberto. Veja em **CRM de Captação**.")
        return

    with st.form(f"form_crm_{empresa['id']}"):
        st.markdown("Criar oportunidade no CRM para esta empresa:")
        titulo = st.text_input("Título da oportunidade", value=f"Captação — {empresa['razao_social']}")
        mecanismo = st.selectbox("Mecanismo pretendido", ["Lei Rouanet", "Lei de Incentivo ao Esporte", "Doação direta", "Outro"])
        valor_potencial = st.number_input("Valor potencial (R$, opcional)", min_value=0.0, step=1000.0)
        responsavel = st.text_input("Responsável pela captação (opcional)")
        enviar = st.form_submit_button("➕ Adicionar ao CRM", use_container_width=True)

    if enviar:
        oportunidade_id = crm.criar_oportunidade(
            conexao,
            {
                "empresa_id": int(empresa["id"]),
                "titulo": titulo,
                "mecanismo": mecanismo,
                "valor_potencial": valor_potencial or None,
                "responsavel": responsavel or None,
            },
        )
        st.success(f"Oportunidade criada no CRM (nº {oportunidade_id}). Veja em **CRM de Captação**.")
        _shared.limpar_cache()


def _calcular_proxima_acao(conexao, empresa, df_pesquisas: pd.DataFrame, ja_no_crm: bool) -> tuple[str, str]:
    """Decide a ação mais provável que o captador precisa tomar agora,
    só a partir de sinais que já existem no banco — nunca uma
    recomendação inventada. Devolve (ícone, texto)."""
    if empresa["linha_cruzada"] and not empresa["reabrir_prospeccao"]:
        return "🎗️", (
            "Esta empresa <b>já tem relacionamento com o IORM</b> — não é prospecção nova. Cuide do relacionamento: "
            "registre interações no <b>Pipeline</b> ou avalie propor um novo projeto."
        )
    if df_pesquisas.empty:
        return "🔍", "Esta empresa ainda não foi pesquisada — clique em <b>Pesquisar/Atualizar dados</b> para buscar site, contatos e evidências."
    if not ja_no_crm and (empresa["score"] or 0) >= 70:
        return "➕", "Empresa prioritária (IORM Score ≥ 70) e ainda fora do Pipeline — considere <b>Adicionar ao CRM</b>."
    if not ja_no_crm:
        return "🧭", "Empresa já pesquisada, mas ainda fora do Pipeline — avalie os dados abaixo antes de decidir sobre uma abordagem."
    ultima_pesquisa = df_pesquisas.iloc[0]
    dias_desde_pesquisa = None
    try:
        data_pesquisa = pd.to_datetime(ultima_pesquisa["executado_em"]).tz_localize(None)
        dias_desde_pesquisa = (pd.Timestamp.now() - data_pesquisa).days
    except Exception:
        pass
    if dias_desde_pesquisa is not None and dias_desde_pesquisa > 90:
        return "🔄", f"Última pesquisa foi há {dias_desde_pesquisa} dias — considere <b>atualizar os dados</b> antes da próxima abordagem."
    return "📋", "Esta empresa já está no Pipeline — acompanhe o andamento e registre interações em <b>Pipeline</b>."


def _secao_relacionamento(conexao, empresa, df_historico: pd.DataFrame) -> None:
    """Vínculo com o IORM: o que prova a relação, de onde vem, e os
    controles manuais (classificar / reabrir prospecção com justificativa)."""
    empresa_id = int(empresa["id"])
    if empresa["linha_cruzada"]:
        _shared.secao(
            "Relacionamento com o IORM (Linha Cruzada)", "🎗️",
            "Empresa com vínculo comprovado — não aparece como prospect normal, mas continua na base com todo o histórico.",
        )
        tipo = empresa.get("relacionamento_tipo")
        if pd.notna(tipo) and tipo:
            rotulo_tipo = relacionamento.ROTULOS_TIPO.get(tipo, tipo)
            fonte = empresa.get("relacionamento_fonte")
            st.markdown(f"**Tipo de vínculo:** {rotulo_tipo}")
            st.markdown(f"**Fonte:** {fonte if pd.notna(fonte) and fonte else 'Não disponível'}")
            if pd.notna(empresa.get("relacionamento_em")):
                st.caption(f"Classificado em {_shared.formatar_data(empresa['relacionamento_em'])}")
        else:
            st.markdown("**Tipo de vínculo:** " + relacionamento.ROTULOS_TIPO[relacionamento.TIPO_DOACAO]
                        + " — identificado nos dados do SALIC (ainda não sincronizado no cadastro).")

        if not df_historico.empty:
            ligados = df_historico[df_historico["projeto"].apply(metricas._projeto_ligado_iorm)]
            if not ligados.empty:
                st.markdown("**Projetos do IORM apoiados:**")
                tabela = ligados.copy()
                tabela["valor"] = tabela["valor"].apply(_shared.formatar_moeda)
                tabela["ano"] = tabela["ano"].fillna("Não disponível")
                st.dataframe(
                    tabela.rename(columns={"ano": "Ano", "projeto": "Projeto do IORM", "valor": "Valor", "fonte": "Fonte",
                                            "tipo_incentivo": "Lei/Mecanismo", "url_fonte": "URL da fonte"})[
                        ["Ano", "Projeto do IORM", "Valor", "Lei/Mecanismo", "Fonte", "URL da fonte"]],
                    use_container_width=True, hide_index=True,
                    column_config={"Projeto do IORM": st.column_config.TextColumn(width="large"),
                                   "URL da fonte": st.column_config.LinkColumn("URL da fonte", display_text="Abrir ↗")},
                )
        if empresa["reabrir_prospeccao"]:
            st.markdown(
                f"<div class='iorm-aviso'><b>Prospecção reaberta</b> por decisão da equipe: "
                f"{empresa['reabrir_justificativa']}</div>", unsafe_allow_html=True,
            )
        with st.expander("Ajustar classificação (exige justificativa)"):
            justificativa = st.text_input("Justificativa", key=f"just_rel_{empresa_id}",
                                          placeholder="Ex: apoio foi de outra empresa homônima / nova abordagem aprovada em reunião")
            col_x, col_y = st.columns(2)
            if empresa["reabrir_prospeccao"]:
                if col_x.button("Voltar a tratar só como Linha Cruzada", key=f"fechar_pros_{empresa_id}"):
                    relacionamento.reabrir_prospeccao(conexao, empresa_id, False, None)
                    _shared.limpar_cache()
                    st.rerun()
            elif col_x.button("Reabrir prospecção desta empresa", key=f"reabrir_pros_{empresa_id}"):
                try:
                    relacionamento.reabrir_prospeccao(conexao, empresa_id, True, justificativa)
                    _shared.limpar_cache()
                    st.rerun()
                except ValueError as erro:
                    st.error(str(erro))
            if col_y.button("Não é relacionamento (voltar a prospect)", key=f"nao_rel_{empresa_id}"):
                try:
                    relacionamento.marcar_manual(conexao, empresa_id, False, justificativa)
                    _shared.limpar_cache()
                    st.rerun()
                except ValueError as erro:
                    st.error(str(erro))
    else:
        with st.expander("🎗️ Marcar como empresa com relacionamento com o IORM"):
            st.caption("Use quando a equipe sabe de uma parceria/doação que não está nos dados coletados.")
            justificativa = st.text_input("Justificativa e fonte da informação", key=f"just_marcar_{empresa_id}")
            if st.button("Mover para Linha Cruzada", key=f"marcar_rel_{empresa_id}"):
                try:
                    relacionamento.marcar_manual(conexao, empresa_id, True, justificativa)
                    _shared.limpar_cache()
                    st.rerun()
                except ValueError as erro:
                    st.error(str(erro))


def _renderizar_ficha(df_mesclado: pd.DataFrame, empresa_id: int) -> None:
    conexao = _shared.conectar()
    empresa = df_mesclado[df_mesclado["id"] == empresa_id].iloc[0]
    df_historico = metricas.historico_empresa(conexao, empresa_id)
    df_presenca = metricas.presenca_digital_empresa(conexao, empresa_id)
    df_contatos = metricas.contatos_empresa(conexao, empresa_id)
    df_evidencias = metricas.evidencias_empresa(conexao, empresa_id)
    df_pesquisas = metricas.historico_pesquisa_empresa(conexao, empresa_id)
    ja_no_crm = crm.empresa_ja_tem_oportunidade_aberta(conexao, int(empresa_id))

    qtd_projetos = df_historico["projeto"].dropna().nunique() if not df_historico.empty else 0
    projetos_iorm = [
        p for p in (df_historico["projeto"].dropna().unique().tolist() if not df_historico.empty else [])
        if metricas._projeto_ligado_iorm(p)
    ]

    st.markdown(f"## {empresa['razao_social']}")
    st.markdown(f"**Nome fantasia:** {_v(empresa.get('nome_fantasia'))}")
    badges = [f"<span class='iorm-badge iorm-badge-azul'>📍 {_v(empresa['cidade'], 'Cidade não disponível')}</span>"]
    camada_regiao = empresa.get("regiao_iorm")
    if pd.notna(camada_regiao) and camada_regiao != "FORA_DA_REGIAO":
        badges.append(_shared.badge_regiao_iorm(camada_regiao))
    polos = geografia.polos_da_cidade(conexao, empresa["cidade"], _shared.obter_territorio_osc())
    for polo in polos:
        badges.append(f"<span class='iorm-badge iorm-badge-azul'>Polo {polo}</span>")
    if empresa["linha_cruzada"]:
        badges.append("<span class='iorm-badge iorm-badge-laranja'>🎗️ Linha Cruzada — relacionamento com o IORM</span>")
    if ja_no_crm:
        badges.append("<span class='iorm-badge iorm-badge-cinza'>🤝 No Pipeline</span>")
    st.markdown(" ".join(badges), unsafe_allow_html=True)
    st.caption(f"Fonte cadastral: {_v(empresa['fonte'])}")

    _secao_relacionamento(conexao, empresa, df_historico)

    icone_acao, texto_acao = _calcular_proxima_acao(conexao, empresa, df_pesquisas, ja_no_crm)
    _shared.proxima_acao(texto_acao, icone_acao)

    # ---------------- Resumo estratégico ----------------
    _shared.secao(
        "Resumo estratégico", "📊",
        '"Essa empresa vale uma abordagem?" — os números que respondem essa pergunta, num só lugar.',
    )
    col_a, col_b, col_c = st.columns(3)
    col_a.metric("IORM Score", f"{empresa['score']}/100")
    col_b.metric("Contactability Score", f"{empresa['contactability_score']}/100")
    col_c.metric("Prioridade de Prospecção", f"{empresa['prioridade_prospeccao']}/100")
    with st.expander("Como esses scores foram calculados?"):
        st.markdown(
            "- **IORM Score** mede afinidade/histórico com o IORM (Região IORM, valor histórico, "
            "projeto ligado ao IORM, CNPJ confirmado, detalhamento disponível).\n"
            "- **Região IORM** (25 pts no máximo) tem 4 camadas configuráveis em Cérebro da OSC → "
            "Território: Cidade de atuação (25) → Região próxima (15) → Interesse estratégico (8) → "
            "Fora da região (0).\n"
            "- **Contactability Score** mede o quão fácil é abordar a empresa (site, e-mail, telefone, "
            "LinkedIn, ESG identificado).\n"
            "- **Prioridade de Prospecção** combina os dois: `0,5×IORM Score + 0,5×Contactability Score`, "
            "com bônus de 10 pontos se houver evidência de ESG/responsabilidade social/instituto/fundação.\n\n"
            "A tabela completa de pontos por critério está em **Configurações**."
        )

    col_d, col_e, col_f, col_g = st.columns(4)
    col_d.metric("Cidade / UF", f"{_v(empresa['cidade'], '—')} / {_v(empresa['estado'], '—')}")
    col_e.metric("Região IORM", regiao.rotulo(camada_regiao) if pd.notna(camada_regiao) else "Não classificada")
    col_f.metric("CNPJ", _shared.formatar_cnpj(empresa["cnpj"]))
    col_g.metric("Situação cadastral", _v(empresa["status"]))
    st.metric("Valor histórico", _shared.formatar_moeda(empresa["valor_total"]))

    col_h, col_i, col_j = st.columns(3)
    col_h.metric("Nº de doações", int(empresa["num_incentivos"]) if pd.notna(empresa["num_incentivos"]) else 0)
    col_i.metric("Projetos identificados", qtd_projetos)
    col_j.metric("Projetos ligados ao IORM", len(set(projetos_iorm)) if projetos_iorm else "Nenhum")

    if projetos_iorm:
        st.markdown(
            "<div class='iorm-info'>✓ Esta empresa já apoiou projeto(s) do próprio IORM: <b>"
            + ", ".join(sorted(set(projetos_iorm))) + "</b></div>",
            unsafe_allow_html=True,
        )
    elif empresa["cidade_estrategica"]:
        st.markdown(
            "<div class='iorm-info'>📍 Empresa localizada numa das cidades de atuação do IORM — proximidade "
            "territorial, mas sem evidência ainda de apoio direto a um projeto do IORM.</div>",
            unsafe_allow_html=True,
        )
    else:
        _shared.estado_vazio("Nenhuma evidência de relação direta com o IORM identificada ainda.", "🔍")

    if not df_historico.empty:
        with st.expander("Ver histórico de incentivos completo (ano, lei/mecanismo, projeto, fonte)"):
            exibir_hist = df_historico.copy()
            exibir_hist["valor"] = exibir_hist["valor"].apply(_shared.formatar_moeda)
            exibir_hist["ano"] = exibir_hist["ano"].fillna("Não disponível")
            exibir_hist["projeto"] = exibir_hist["projeto"].fillna("Não disponível (valor agregado)")
            st.dataframe(
                exibir_hist.rename(columns={"ano": "Ano", "projeto": "Projeto", "valor": "Valor", "fonte": "Fonte", "tipo_incentivo": "Lei/Mecanismo"})[
                    ["Ano", "Lei/Mecanismo", "Projeto", "Valor", "Fonte"]
                ],
                use_container_width=True, hide_index=True,
            )

    # ---------------- Inteligência de contato ----------------
    _shared.secao(
        "Inteligência de contato", "📇",
        '"Quem posso procurar, e como?" — canais e pessoas encontrados, cada um com fonte e confiança.',
    )
    col_canais, col_pessoas = st.columns(2)
    with col_canais:
        st.markdown("**Canais institucionais**")
        if df_presenca.empty and df_contatos.empty:
            _shared.estado_vazio("Nenhum canal de contato pesquisado ainda.", "🌐")
        else:
            canais_institucionais = df_contatos[df_contatos["tipo_contato"] != "PESSOA_CARGO"] if not df_contatos.empty else df_contatos
            linhas_canais = []  # (icone, texto_html, confianca, fonte_ou_area)
            ordem_conf = {"ALTO": 0, "MEDIO": 1, "BAIXO": 2, "NAO_CONFIRMADO": 3}
            if not df_presenca.empty:
                for linha in df_presenca.sort_values(by="nivel_confianca", key=lambda s: s.map(ordem_conf)).itertuples():
                    icone = {"site": "🌐", "linkedin": "💼", "instagram": "📷", "facebook": "📘", "youtube": "▶️"}.get(linha.tipo, "🔗")
                    legivel = linha.url.split("://", 1)[-1]
                    linhas_canais.append((icone, f"<b>{linha.tipo.capitalize()}</b>: <a href='{linha.url}' target='_blank'>{legivel}</a>",
                                          linha.nivel_confianca, linha.fonte))
            if canais_institucionais is not None and not canais_institucionais.empty:
                for linha in canais_institucionais.itertuples():
                    if "EMAIL" in linha.tipo_contato:
                        area = linha.departamento if isinstance(linha.departamento, str) and linha.departamento else (enriquecimento.area_do_email(linha.valor) or "área não identificada")
                        texto, icone = f"<b>E-mail institucional</b> ({area}): {linha.valor}", "✉️"
                    elif "TELEFONE" in linha.tipo_contato or "WHATSAPP" in linha.tipo_contato:
                        texto, icone = f"<b>Telefone institucional</b>: {linha.valor}", "📞"
                    else:
                        texto, icone = f"<b>Formulário/contato</b>: <a href='{linha.valor}' target='_blank'>{linha.valor.split('://', 1)[-1]}</a>", "🔗"
                    linhas_canais.append((icone, texto, linha.nivel_confianca, linha.fonte))

            def _mostrar(itens):
                for icone, texto, conf, fonte in itens:
                    st.markdown(
                        f"{icone} {texto} &nbsp;<span class='iorm-badge iorm-badge-cinza'>{conf}</span>"
                        f"<br><span style='color:var(--iorm-cinza);font-size:0.76rem;'>Fonte: {fonte}</span>",
                        unsafe_allow_html=True,
                    )

            _mostrar(linhas_canais[:6])
            if len(linhas_canais) > 6:
                with st.expander(f"Ver mais {len(linhas_canais) - 6} canal(is)"):
                    _mostrar(linhas_canais[6:])
    with col_pessoas:
        st.markdown("**Pessoas identificadas publicamente**")
        pessoas = df_contatos[df_contatos["tipo_contato"] == "PESSOA_CARGO"] if not df_contatos.empty else df_contatos
        if pessoas is None or pessoas.empty:
            _shared.estado_vazio("Nenhuma pessoa/cargo identificado ainda.", "👤")
        else:
            for linha in pessoas.itertuples():
                nome = linha.nome or "Nome não identificado"
                cargo = f" — {linha.cargo}" if linha.cargo else ""
                st.markdown(
                    f"👤 **{nome}**{cargo} &nbsp;·&nbsp; <span class='iorm-badge iorm-badge-cinza'>{linha.nivel_confianca}</span><br>"
                    f"<a href='{linha.valor}' style='font-size:0.82rem;'>{linha.valor}</a>",
                    unsafe_allow_html=True,
                )

    # ---------------- Evidências ----------------
    _shared.secao("Evidências (ESG, responsabilidade social, instituto/fundação)", "🌱", "De onde veio cada informação — sempre com fonte.")
    if df_evidencias.empty:
        _shared.estado_vazio("Nenhuma evidência pesquisada ainda para esta empresa.")
    else:
        st.dataframe(
            df_evidencias.rename(
                columns={"categoria": "Categoria", "descricao": "Descrição", "url": "URL", "fonte": "Fonte", "nivel_confianca": "Confiança"}
            ),
            use_container_width=True, hide_index=True,
        )

    if not df_pesquisas.empty:
        ultima = df_pesquisas.iloc[0]
        mapa_status = {
            "SUCESSO": "✅ Pesquisa concluída", "PARCIAL": "🟡 Pesquisa concluída parcialmente",
            "FALHA": "🔴 Não foi possível concluir a pesquisa",
        }
        st.caption(
            f"Última pesquisa: {mapa_status.get(ultima['status'], ultima['status'])} em "
            f"{_shared.formatar_data(ultima['executado_em'])} — {ultima['quantidade_fontes']} fonte(s), "
            f"{ultima['quantidade_contatos']} contato(s), {ultima['quantidade_redes']} rede(s), "
            f"{ultima['quantidade_evidencias']} evidência(s)."
        )

    _shared.secao("Ações", "⚡")
    provider_ativo = busca_providers.obter_provider_ativo()
    usa_busca_ao_vivo = isinstance(provider_ativo, busca_providers.SerpApiProvider)

    col_pesq, col_crm, col_fonte = st.columns(3)
    with col_pesq:
        rotulo = "🔍 Pesquisar / Atualizar dados" if usa_busca_ao_vivo else "🔍 Pesquisar / Atualizar dados"
        if st.button(rotulo, key=f"pesquisar_{empresa_id}", use_container_width=True):
            if usa_busca_ao_vivo:
                with st.spinner(f"Pesquisando com {provider_ativo.nome}..."):
                    resultado = pesquisa_empresa.pesquisar_empresa(
                        conexao, empresa_id, empresa["razao_social"], empresa["cidade"], empresa["estado"],
                        provider=provider_ativo,
                    )
                total_achados = resultado["presenca_digital"] + resultado["evidencias"] + resultado["contatos"]
                if resultado["erros"]:
                    st.error(
                        "A busca não pôde ser concluída: " + " ".join(resultado["erros"])
                        + (f" (mesmo assim, {total_achados} resultado(s) foram salvos antes da falha.)" if total_achados else "")
                    )
                elif total_achados:
                    st.success(
                        f"Pesquisa concluída: {resultado['presenca_digital']} presença(s) digital(is), "
                        f"{resultado['contatos']} contato(s) e {resultado['evidencias']} evidência(s) "
                        "encontrados (confiança MÉDIA/BAIXA — revise antes de usar em uma abordagem)."
                    )
                else:
                    st.warning("Pesquisa concluída, mas nenhum resultado relevante foi encontrado para esta empresa.")
                _shared.limpar_cache()
                st.rerun()
            else:
                _shared.adicionar_fila_pesquisa(empresa_id, empresa["razao_social"])
                st.warning(
                    "Solicitação registrada na fila de pesquisa. Nenhuma API de busca está configurada "
                    "agora (ver Configurações → Inteligência de Contatos) — a pesquisa será feita por um "
                    "agente com ferramentas de busca fora do navegador."
                )
    with col_crm:
        with st.expander("➕ Adicionar ao CRM", expanded=False):
            _acao_adicionar_ao_crm(conexao, empresa)
    with col_fonte:
        if empresa["url_fonte"]:
            st.link_button("↗ Abrir fonte oficial", empresa["url_fonte"], use_container_width=True)
        else:
            st.button("↗ Abrir fonte oficial", disabled=True, use_container_width=True, help="Nenhuma URL de fonte disponível.")

    if not usa_busca_ao_vivo:
        st.caption(
            "💡 O botão de pesquisa está usando a fila manual porque não há chave de API de busca "
            "configurada. Veja como ativar a busca automática em Configurações."
        )

    conexao.close()


def render() -> None:
    dados = _shared.carregar_dados_salic(str(_shared.CAMINHO_DB))
    df_mesclado = dados["df_mesclado"]

    _shared.cabecalho("Radar de Empresas", "Prospecção separada de quem já tem relacionamento com o IORM.")

    df_prospects = df_mesclado[df_mesclado["eh_prospect"]]
    df_linha_cruzada = df_mesclado[df_mesclado["linha_cruzada"]]

    aba_prospeccao, aba_cruzada, aba_busca, aba_historico = st.tabs([
        f"🎯 Radar de Prospecção ({len(df_prospects):,})".replace(",", "."),
        f"🎗️ Linha Cruzada — com relacionamento ({len(df_linha_cruzada)})",
        "🔎 Buscar qualquer empresa",
        "📜 Histórico de Incentivos (Lei Rouanet)",
    ])

    with aba_prospeccao:
        df_filtrado = _renderizar_filtros(df_prospects)
        _shared.secao(
            "Empresas candidatas à prospecção", "📋",
            f"{_shared.formatar_numero(len(df_filtrado))} empresa(s) após os filtros da barra lateral. Empresas que já apoiaram "
            "o IORM ficam na aba Linha Cruzada — continuam na base, só não aparecem aqui como prospect novo.",
        )
        empresa_id = tabela_selecionavel(df_filtrado, "prospeccao", vazio="Nenhuma empresa encontrada com os filtros atuais.")
        if not df_filtrado.empty:
            csv = _tabela_para_exibicao(df_filtrado).to_csv(index=False).encode("utf-8-sig")
            st.download_button("⬇ Baixar resultados (CSV)", data=csv, file_name="iorm_radar_prospeccao.csv", mime="text/csv")
        ficha_da_selecao(df_mesclado, empresa_id)

    with aba_cruzada:
        _shared.secao(
            "Empresas com relacionamento com o IORM", "🎗️",
            "Doaram/patrocinaram projetos do IORM (dados do SALIC) ou têm oportunidade ganha no Pipeline. "
            "Selecione uma linha para ver a ficha completa: histórico, projetos, valores, fontes, contatos e evidências.",
        )
        if df_linha_cruzada.empty:
            _shared.estado_vazio("Nenhuma empresa com relacionamento identificado ainda.", "🎗️")
        else:
            m1, m2, m3 = st.columns(3)
            m1.metric("Empresas com relacionamento", len(df_linha_cruzada))
            m2.metric("Valor histórico somado", _shared.formatar_moeda(df_linha_cruzada["valor_total"].sum()))
            m3.metric("Com prospecção reaberta", int(df_linha_cruzada["reabrir_prospeccao"].sum()))
        id_cruzada = tabela_selecionavel(
            df_linha_cruzada.sort_values("valor_total", ascending=False), "cruzada", _tabela_linha_cruzada,
        )
        ficha_da_selecao(df_mesclado, id_cruzada)

    with aba_busca:
        _shared.secao("Buscar qualquer empresa da base", "🔎", "Prospects e empresas com relacionamento, por nome — digite para filtrar.")
        df_ordenado = df_mesclado.sort_values("razao_social")
        opcoes = {
            f"{l.razao_social} — {_shared.formatar_cnpj(l.cnpj)} ({l.cidade or 'cidade não disponível'})"
            f"{'  [Linha Cruzada]' if l.linha_cruzada else ''}": l.id
            for l in df_ordenado.itertuples()
        }
        escolha = st.selectbox("Empresa", list(opcoes.keys()), index=None, placeholder="Digite o nome da empresa...")
        if escolha:
            ficha_da_selecao(df_mesclado, opcoes[escolha])

    with aba_historico:
        df_danca = dados["df_danca"]
        st.markdown("### Empresas que já apoiaram a Usina da Dança")
        st.caption(
            f"{len(df_danca)} registro(s) encontrado(s) citando o projeto \"Usina da Dança\" "
            "(todas as variações de nome encontradas nos dados oficiais)."
        )
        if df_danca.empty:
            _shared.estado_vazio("Nenhum registro encontrado.")
        else:
            exibir = df_danca.copy()
            exibir["valor"] = exibir["valor"].apply(_shared.formatar_moeda)
            exibir = exibir.rename(columns={"empresa": "Empresa", "ano": "Ano", "valor": "Valor", "cidade": "Cidade", "projeto": "Projeto", "fonte": "Fonte"})
            st.dataframe(
                exibir, use_container_width=True, hide_index=True,
                column_config={"Empresa": st.column_config.TextColumn(width=430), "Projeto": st.column_config.TextColumn(width=300),
                               "Valor": st.column_config.TextColumn(width=150), "Fonte": st.column_config.LinkColumn("Fonte", display_text="Abrir ↗")},
            )
            st.markdown("#### Valor por empresa")
            por_empresa = df_danca.groupby("empresa")["valor"].sum().sort_values(ascending=False)
            _shared.grafico_barras(por_empresa, "Valor (R$)")