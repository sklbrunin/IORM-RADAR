"""Radar de Empresas: lista filtrável, ficha completa por empresa e a
ponte para o CRM ("Adicionar ao CRM")."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from processamento import busca_providers, crm, filtros, metricas, pesquisa_empresa, regiao
from paginas import _shared


def _tabela_para_exibicao(df: pd.DataFrame) -> pd.DataFrame:
    exibir = df.copy()
    exibir["CNPJ"] = exibir["cnpj"].apply(_shared.formatar_cnpj)
    exibir["Confiança"] = exibir["nivel_confianca"].fillna("Não disponível")
    exibir["Valor histórico (R$)"] = exibir["valor_total"].apply(_shared.formatar_moeda)
    exibir = exibir.rename(
        columns={
            "razao_social": "Empresa",
            "cidade": "Cidade",
            "estado": "UF",
            "num_incentivos": "Nº de doações",
            "score": "IORM Score",
            "contactability_score": "Contactability",
            "prioridade_prospeccao": "Prioridade de Prospecção",
            "tipo_dado": "Tipo de dado",
        }
    )
    exibir["Cidade"] = exibir["Cidade"].fillna("Não disponível")
    return exibir[
        [
            "Empresa", "CNPJ", "Cidade", "UF", "Valor histórico (R$)", "Nº de doações",
            "IORM Score", "Contactability", "Prioridade de Prospecção", "Confiança", "Tipo de dado",
        ]
    ]


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
    badges = [f"<span class='iorm-badge iorm-badge-azul'>📍 {empresa['cidade'] or 'Cidade não disponível'}</span>"]
    camada_regiao = empresa.get("regiao_iorm")
    if pd.notna(camada_regiao) and camada_regiao != "FORA_DA_REGIAO":
        badges.append(_shared.badge_regiao_iorm(camada_regiao))
    if projetos_iorm:
        badges.append("<span class='iorm-badge iorm-badge-laranja'>🎗️ Já apoiou projeto do IORM</span>")
    if ja_no_crm:
        badges.append("<span class='iorm-badge iorm-badge-cinza'>🤝 No Pipeline</span>")
    st.markdown(" ".join(badges), unsafe_allow_html=True)
    st.caption(f"Fonte cadastral: {empresa['fonte'] or 'Não disponível'}")

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
    col_d.metric("Cidade / UF", f"{empresa['cidade'] or '—'} / {empresa['estado'] or '—'}")
    col_e.metric("Região IORM", regiao.rotulo(camada_regiao) if pd.notna(camada_regiao) else "Não classificada")
    col_f.metric("CNPJ", _shared.formatar_cnpj(empresa["cnpj"]))
    col_g.metric("Situação cadastral", empresa["status"] or "Não disponível")
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
            canais_pessoa = {"PESSOA_CARGO"}
            canais_institucionais = df_contatos[~df_contatos["tipo_contato"].isin(canais_pessoa)] if not df_contatos.empty else df_contatos
            if not df_presenca.empty:
                for linha in df_presenca.itertuples():
                    icone = {"site": "🌐", "linkedin": "💼", "instagram": "📷", "facebook": "📘", "youtube": "▶️"}.get(linha.tipo, "🔗")
                    st.markdown(f"{icone} [{linha.tipo.capitalize()}]({linha.url}) &nbsp;·&nbsp; <span class='iorm-badge iorm-badge-cinza'>{linha.nivel_confianca}</span>", unsafe_allow_html=True)
            if canais_institucionais is not None and not canais_institucionais.empty:
                for linha in canais_institucionais.itertuples():
                    icone = "✉️" if "EMAIL" in linha.tipo_contato else ("📞" if "TELEFONE" in linha.tipo_contato or "WHATSAPP" in linha.tipo_contato else "🔗")
                    st.markdown(f"{icone} {linha.valor} &nbsp;·&nbsp; <span class='iorm-badge iorm-badge-cinza'>{linha.nivel_confianca}</span>", unsafe_allow_html=True)
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
    df_empresas, df_mesclado = dados["df_empresas"], dados["df_mesclado"]

    _shared.cabecalho("Radar de Empresas", "Encontre, filtre e priorize empresas com histórico de incentivo.")

    aba_lista, aba_historico = st.tabs(["Lista e ficha da empresa", "Histórico de Incentivos (Lei Rouanet)"])

    with aba_lista:
        df_filtrado = _renderizar_filtros(df_mesclado)
        _shared.secao("Empresas mapeadas", "📋", f"{len(df_filtrado)} empresa(s) após os filtros aplicados na barra lateral.")
        if df_filtrado.empty:
            _shared.estado_vazio("Nenhuma empresa encontrada com os filtros atuais.")
        else:
            st.dataframe(_tabela_para_exibicao(df_filtrado), use_container_width=True, hide_index=True, column_config=_shared.CONFIG_COLUNA_EMPRESA)
            csv = _tabela_para_exibicao(df_filtrado).to_csv(index=False).encode("utf-8-sig")
            st.download_button("⬇ Baixar resultados (CSV)", data=csv, file_name="iorm_radar_empresas.csv", mime="text/csv")

        _shared.secao("Ficha da empresa", "🔎", "Selecione uma empresa para ver o detalhamento completo.")
        df_ordenado = df_mesclado.sort_values("razao_social")
        opcoes = {
            f"{linha.razao_social} — {_shared.formatar_cnpj(linha.cnpj)} ({linha.cidade or 'cidade não disponível'})": linha.id
            for linha in df_ordenado.itertuples()
        }
        escolha = st.selectbox("Selecione uma empresa", list(opcoes.keys()))
        _renderizar_ficha(df_mesclado, opcoes[escolha])

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
            st.dataframe(exibir, use_container_width=True, hide_index=True, column_config=_shared.CONFIG_COLUNA_EMPRESA)
            st.markdown("#### Valor por empresa")
            por_empresa = df_danca.groupby("empresa")["valor"].sum().sort_values(ascending=False)
            st.bar_chart(por_empresa)
