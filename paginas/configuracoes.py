"""Configurações / Administração: explicação do sistema, fórmulas dos
scores, status da API de busca, mecanismos de incentivo, fila de
pesquisa pendente e catálogo de fontes de dados."""
from __future__ import annotations

import os
from datetime import datetime

import pandas as pd
import streamlit as st

from processamento import busca_providers, contact_providers, descoberta_empresas, fontes_dados, incentivos_providers, mecanismos
from paginas import _shared


def _aba_sobre() -> None:
    st.markdown(
        """
        O **IORM Radar** é uma ferramenta de inteligência para apoiar a captação de recursos
        do **Instituto Oswaldo Ribeiro de Mendonça**. Esta versão utiliza dados públicos e
        oficiais e **não pretende afirmar faturamento, lucro, número de funcionários ou intenção
        futura de doação** quando essas informações não estão disponíveis. Quando um dado não
        existe na fonte consultada, o sistema mostra literalmente **"Não disponível"**.
        """
    )
    _shared.secao("Identidade visual", "🎨")
    if _shared.CAMINHO_LOGO.exists():
        col_a, col_b = st.columns([1, 4])
        col_a.image(str(_shared.CAMINHO_LOGO_TRANSPARENTE if _shared.CAMINHO_LOGO_TRANSPARENTE.exists() else _shared.CAMINHO_LOGO), width=80)
        col_b.success("Logo oficial do IORM em uso em toda a plataforma (cabeçalhos e barra lateral).")
    else:
        st.warning(
            "Nenhuma logo encontrada. Coloque o arquivo oficial do IORM em "
            "`assets/logo-iorm.png` — o sistema passa a usá-la automaticamente."
        )


def _aba_scores() -> None:
    _shared.secao("Critérios do IORM Score", "📈", "Máximo 100 pontos.")
    st.markdown(
        """
        | Critério | Pontos |
        |---|---|
        | Tem histórico de incentivo via Lei Rouanet | 10 |
        | CNPJ confirmado matematicamente | 15 |
        | Doação detalhada por projeto/ano disponível | 15 |
        | Empresa em cidade estratégica do IORM | 25 |
        | Algum projeto financiado é um programa do IORM | 20 |
        | Valor histórico ≥ R$ 500 mil | 15 |
        | Valor histórico ≥ R$ 100 mil (e < 500 mil) | 10 |
        | Valor histórico ≥ R$ 10 mil (e < 100 mil) | 5 |
        """
    )
    _shared.secao("Critérios do Contactability Score", "📶", "Máximo 100 pontos.")
    st.markdown(
        """
        | Critério | Pontos |
        |---|---|
        | Site oficial encontrado | 10 |
        | E-mail institucional encontrado | 20 |
        | Telefone institucional encontrado | 10 |
        | LinkedIn da empresa encontrado | 10 |
        | Instagram oficial encontrado | 5 |
        | Evidência de ESG identificada | 15 |
        | Evidência de responsabilidade social identificada | 15 |
        | Instituto/fundação identificado | 15 |
        | Contato profissional relevante confirmado | 20 |
        """
    )
    _shared.secao("Prioridade de Prospecção", "🎯")
    st.code(
        "base = 0,5 × IORM Score + 0,5 × Contactability Score\n"
        "Prioridade de Prospecção = mín(100, base + 10 se houver evidência de ESG/\n"
        "                                responsabilidade social/instituto/fundação)"
    )
    _shared.secao("Aderência de editais", "📋", "0 a 10.")
    st.markdown(
        """
        Seis critérios (área, território, público, elegibilidade, valor, prazo), cada um de 0 a 10.
        A nota final é a média ponderada só dos critérios com dado disponível — nunca inventamos
        nota para um critério sem informação. Pesos: área 25%, território 20%, público 15%,
        elegibilidade 15%, valor 10%, prazo 15%. Critério sem dado aparece como “Não identificado na
        fonte” e a ficha informa com quantos dos 6 critérios a nota foi calculada. No Dashboard, “alta
        aderência” exige nota ≥ 7,0 com pelo menos 3 critérios avaliados e edital ABERTO (prazo real futuro
        confirmado, com link da fonte).
        """
    )


def _aba_busca() -> None:
    provider = busca_providers.obter_provider_ativo()
    usa_busca_ao_vivo = isinstance(provider, busca_providers.SerpApiProvider)

    _shared.secao("Status da API de busca", "🔌")
    if usa_busca_ao_vivo:
        st.markdown(
            "<div class='iorm-info'>🟢 <b>SerpApi configurada</b> — o botão Pesquisar/Atualizar na ficha "
            "da empresa busca automaticamente (site, LinkedIn, ESG) e grava os resultados com nível de "
            "confiança MÉDIO/BAIXO (pesquisa automática, ainda sem revisão humana).</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            "<div class='iorm-limitacao'>🔴 <b>Nenhuma API de busca configurada.</b> O botão "
            "Pesquisar/Atualizar registra a empresa numa fila manual, processada por um agente com "
            "ferramentas de busca fora do navegador.</div>",
            unsafe_allow_html=True,
        )

    with st.expander("Como ativar a busca automática (SerpApi)"):
        st.markdown(
            """
            1. Crie uma conta gratuita em [serpapi.com](https://serpapi.com/).
            2. Copie sua chave em "Your Account → API Key".
            3. Copie `.env.example` para `.env` na raiz do projeto e cole a chave em `SERPAPI_API_KEY=`.
            4. Reinicie a dashboard (`streamlit run app.py`).

            Tier gratuito atual: ~100-250 buscas/mês. **A chave nunca deve ir no código** — o `.env`
            já está no `.gitignore`, então não é versionado nem enviado para o GitHub.
            """
        )

    st.caption(
        "Comparação de opções pesquisada em 2026 (ver docs/decisoes.md): Google Custom Search API está "
        "fechada para novos clientes; Bing Search API foi aposentada em ago/2025; Brave Search API passou "
        "a exigir cartão de crédito. SerpApi foi escolhida por ter tier gratuito real, sem cartão."
    )

    _shared.secao("Arquitetura de provedores (SearchProvider)", "🧩")
    st.markdown(
        "O sistema usa uma camada de abstração (`processamento/busca_providers.py`) — trocar de "
        "provedor no futuro (Brave, Tavily etc.) é só implementar uma nova classe, sem reescrever o "
        "resto do sistema. Provider ativo agora: **" + provider.nome + "**."
    )

    _shared.secao("Provedores de contatos (ContactProvider)", "🔌",
                  "Cada provedor devolve contatos que passam pelo mesmo funil: normalizar → validar → banco → evidência.")
    conexao = _shared.conectar()
    provedores = [
        contact_providers.ReceitaFederalContactProvider(),
        contact_providers.WebSearchContactProvider(conexao),
        contact_providers.HunterContactProvider(),
    ]
    linhas = [{
        "Provedor": p.nome,
        "Custo": {"GRATUITO": "Gratuito", "CAMADA_GRATUITA": "Camada gratuita limitada", "PAGO": "Pago"}.get(p.custo, p.custo),
        "Credencial exigida (variável de ambiente)": p.credencial_env or "Nenhuma",
        "Situação": "✅ Disponível" if p.disponivel() else "⛔ Sem credencial configurada",
    } for p in provedores]
    st.dataframe(
        pd.DataFrame(linhas), hide_index=True, use_container_width=True,
        column_config={"Provedor": st.column_config.TextColumn(width=260), "Custo": st.column_config.TextColumn(width=180),
                       "Credencial exigida (variável de ambiente)": st.column_config.TextColumn(width=300),
                       "Situação": st.column_config.TextColumn(width=240)},
    )
    st.caption("Só o nome da variável aparece aqui — os valores ficam no arquivo `.env` (fora do Git). "
               "Avaliação completa dos provedores em `docs/decisoes.md`.")


_ROTULO_ESTADO_PROVEDOR = {
    descoberta_empresas.STATUS_DISPONIVEL: "✅ Disponível", descoberta_empresas.STATUS_SEM_CREDENCIAL: "🔑 Sem credencial",
    descoberta_empresas.STATUS_SEM_COTA: "🟠 Sem cota", descoberta_empresas.STATUS_INDISPONIVEL: "⛔ Indisponível",
}
_ROTULO_ULTIMO = {"CONCLUIDO": "✅ Concluído", "DISPONIVEL": "—", "SEM_CREDENCIAL": "🔑 Sem credencial", "SEM_COTA": "🟠 Sem cota",
                   "INDISPONIVEL": "⛔ Indisponível", "ERRO": "🔴 Erro", "DESABILITADO": "⏸ Desligado"}


def _alternar_provedor(nome: str) -> None:
    conexao = _shared.conectar()
    descoberta_empresas.criar_tabelas(conexao)
    descoberta_empresas.definir_habilitado(conexao, nome, bool(st.session_state.get(f"descob_hab_{nome}")))
    conexao.close()


def _aba_descoberta() -> None:
    conexao = _shared.conectar()
    descoberta_empresas.criar_tabelas(conexao)
    _shared.secao(
        "Provedores de descoberta de empresas", "🌎",
        "Encontram empresas NOVAS em todo o Brasil. A Região IORM vem primeiro (nível 1: cidades do IORM → 2: estado → 3: outros estados → "
        "4: Brasil), mas não é restrição. Descobrir uma empresa não a torna prospect nem parceira do IORM.")
    linhas = descoberta_empresas.situacao_providers(conexao)
    tabela = pd.DataFrame([{
        "Provedor": l["rotulo"], "Situação": _ROTULO_ESTADO_PROVEDOR.get(l["estado"], l["estado"]),
        "Ligado": "Sim" if l["habilitado"] else "Não", "Custo": l["custo"], "Como o app acessa": l["acesso"],
        "Última execução": _fmt_dt(l["ultima_execucao"]) if l["ultima_execucao"] else "Nunca",
        "Resultado da última": _ROTULO_ULTIMO.get(l["ultimo_status"], "—"),
        "Origens registradas": l["origens_registradas"], "Duplicatas (existentes)": l["existentes"],
        "Possíveis duplicatas": l["possiveis_duplicatas"], "Erros": l["erros"],
        "Créditos no mês": l["creditos_no_mes"],
        "Validado com serviço real": "Sim" if l["validado"] else "Não (sem chave/plano)",
    } for l in linhas])
    st.dataframe(tabela, hide_index=True, use_container_width=True, column_config={
        "Provedor": st.column_config.TextColumn(width=200), "Situação": st.column_config.TextColumn(width=160),
        "Custo": st.column_config.TextColumn(width=420), "Como o app acessa": st.column_config.TextColumn(width=420),
        "Última execução": st.column_config.TextColumn(width=170), "Resultado da última": st.column_config.TextColumn(width=160),
        "Validado com serviço real": st.column_config.TextColumn(width=190)})
    for l in linhas:
        if l["estado"] != descoberta_empresas.STATUS_DISPONIVEL and l["motivo"]:
            st.caption(f"**{l['rotulo']}:** {l['motivo']}")
        if l["observacao_validacao"] and not l["validado"]:
            st.caption(f"**{l['rotulo']} — atenção:** {l['observacao_validacao']}")

    st.markdown("**Ligar / desligar provedores**")
    colunas = st.columns(len(linhas))
    for coluna, l in zip(colunas, linhas):
        coluna.toggle(l["rotulo"], value=l["habilitado"], key=f"descob_hab_{l['provider']}", on_change=_alternar_provedor, args=(l["provider"],))
    st.caption(
        f"Meta diária: **{descoberta_empresas.empresas_novas_por_dia()} empresas novas** (`EMPRESAS_NOVAS_POR_DIA`) · limite por provedor por "
        f"execução: **{descoberta_empresas.limite_por_provider('') or descoberta_empresas.LIMITE_POR_PROVIDER_PADRAO}** (`LIMITE_POR_PROVIDER` ou "
        "`LIMITE_POR_PROVIDER_<NOME>`) · teto mensal opcional por provedor: `DESCOBERTA_LIMITE_MENSAL_<NOME>`. "
        "A SerpApi Maps vem desligada porque divide a cota mensal com o enriquecimento.")

    with st.expander("Conectores do Claude (Apollo, Lusha, Snov.io) × este aplicativo — o que é verdade"):
        st.markdown(
            "- **Os conectores (MCP) que aparecem no Claude Code funcionam só dentro do Claude**, para o desenvolvedor consultar contas. "
            "O aplicativo Streamlit e a rotina diária **não conseguem chamá-los**.\n"
            "- Para o app descobrir empresas sozinho, cada serviço precisa de **chave/credencial de API própria** no `.env` "
            f"(Apollo: `APOLLO_API_KEY` · Lusha: `LUSHA_API_KEY` · Snov.io: `SNOV_CLIENT_ID` e `SNOV_CLIENT_SECRET`).\n"
            "- **Apollo:** a documentação oficial informa que a busca de organizações pela API é exclusiva de planos pagos (a conta gratuita recebe HTTP 403).\n"
            "- **Lusha e Snov.io:** planos gratuitos/trial têm poucos créditos (Lusha: 1 crédito por 25 empresas; Snov.io gratuito: 1 página por busca).\n"
            "- **Sem chave, o provedor aparece como “Sem credencial” e é pulado** — nunca é dado como funcionando.")

    _shared.secao("Candidatas sem CNPJ — aguardando validação", "🕵️",
                  "Empresas achadas por provedores que não informam CNPJ. Ficam fora dos prospects e da fila de enriquecimento até a equipe validar.")
    candidatas = pd.read_sql_query(
        """SELECT e.id, e.razao_social AS Empresa, e.cidade AS Cidade, e.estado AS UF, e.dominio AS Site, e.origem_descoberta AS Origem,
                  e.possivel_duplicata_de AS "Possível duplicata de (id)"
           FROM empresas e WHERE e.estagio_cadastro = 'CANDIDATA' ORDER BY e.id DESC LIMIT 200""", conexao)
    if candidatas.empty:
        _shared.estado_vazio("Nenhuma candidata aguardando validação.", "🕵️")
    else:
        st.dataframe(candidatas.drop(columns=["id"]), hide_index=True, use_container_width=True)
        opcoes = {f"{r.Empresa} — {r.Cidade or '?'}/{r.UF or '?'} (#{r.id})": int(r.id) for r in candidatas.itertuples()}
        escolha = st.selectbox("Validar candidata", list(opcoes), key="descob_cand_escolha")
        cnpj = st.text_input("CNPJ confirmado (14 dígitos)", key="descob_cand_cnpj")
        justificativa = st.text_input("Ou justificativa da validação manual (sem CNPJ)", key="descob_cand_just")
        if st.button("Confirmar como empresa validada", key="descob_cand_confirmar"):
            r = descoberta_empresas.promover_candidata(conexao, opcoes[escolha], cnpj or None, justificativa)
            if r["ok"]:
                _shared.limpar_cache()
                st.success("Empresa validada — agora entra na base de prospects.")
                st.rerun()
            else:
                st.error(r["motivo"])
    conexao.close()


def _aba_mecanismos() -> None:
    _shared.secao("Mecanismos de incentivo/captação", "⚖️", "Arquitetura multi-fonte — status real de cada integração.")
    contagem = mecanismos.contar_por_status()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🟢 Integradas", contagem["INTEGRADA"])
    c2.metric("🟡 Parciais", contagem["PARCIAL"])
    c3.metric("🔵 Manuais", contagem["MANUAL"])
    c4.metric("🔴 Indisponíveis", contagem["INDISPONIVEL"])

    conexao = _shared.conectar()
    resumo = incentivos_providers.resumo_por_mecanismo(conexao)
    conexao.close()
    _shared.secao("Incentivos já coletados, por mecanismo", "🧮")
    if not resumo:
        st.info("Nenhum incentivo coletado ainda.")
    else:
        tabela = pd.DataFrame([{
            "Mecanismo": incentivos_providers.ROTULOS_MECANISMO.get(r["mecanismo"], "Não classificado"),
            "Registros": _shared.formatar_numero(r["registros"]), "Empresas": _shared.formatar_numero(r["empresas"]),
            "Valor total": _shared.formatar_moeda(r["valor_total"]), "UFs": r["ufs"] or "—",
        } for r in resumo])
        st.dataframe(tabela, use_container_width=True, hide_index=True, column_config={
            "Mecanismo": st.column_config.TextColumn(width=320), "Valor total": st.column_config.TextColumn(width=240)})
    _shared.secao("Como cada mecanismo é (ou não) coletado", "🔌",
                  "Provedores em processamento/incentivos_providers.py. Só há coleta onde existe fonte pública estruturada e verificada.")
    for provider in incentivos_providers.provedores_padrao().values():
        integrado = provider.status == incentivos_providers.STATUS_INTEGRADO
        rotulo_estado = "🟢 Integrado" if integrado else "🔴 Integração ainda não disponível"
        with st.expander(f"{rotulo_estado} — {provider.nome}"):
            st.markdown(f"**Esfera:** {provider.esfera}  \n**Fonte:** {provider.fonte_nome}")
            if provider.fonte_url:
                st.markdown(f"[Abrir fonte]({provider.fonte_url})")
            st.markdown(f"**O que foi verificado (18/09/2026):** {provider.investigacao}")

    _shared.secao("Registro geral de mecanismos", "⚖️")
    for mecanismo in mecanismos.listar_mecanismos():
        with st.expander(f"{mecanismo['nome']} — {mecanismo['esfera']}"):
            st.markdown(_shared.badge_status_integracao(mecanismo["status"]), unsafe_allow_html=True)
            st.markdown(
                f"""
                - **Órgão responsável:** {mecanismo['orgao']}
                - **Fonte:** {mecanismo['fonte']}
                - **Método de coleta:** {mecanismo['metodo_coleta']}
                - **Campos disponíveis:** {mecanismo['campos_disponiveis']}
                - **Última verificação:** {_shared.formatar_data(mecanismo['ultima_verificacao'])}
                """
            )
            if mecanismo["url"]:
                st.markdown(f"[Abrir fonte]({mecanismo['url']})")
            st.caption(mecanismo["observacao"])


def _aba_fila() -> None:
    fila = _shared.carregar_fila_pesquisa()
    _shared.secao("Fila de pesquisa pendente", "🗂️", f"{len(fila)} empresa(s) aguardando pesquisa manual.")
    if fila:
        st.dataframe(pd.DataFrame(fila), use_container_width=True, hide_index=True)
    else:
        _shared.estado_vazio("Fila vazia no momento.", "✅")


def _fmt_dt(texto) -> str:
    if not texto:
        return "—"
    try:
        return datetime.fromisoformat(texto).astimezone().strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return _shared.formatar_data(texto)


def _cartao_fonte(conexao, f) -> None:
    ativa = bool(f["ativo"])
    titulo = f"{'🟢' if ativa else '⚪'} {f['nome']}  ·  {f['tipo']}" + ("" if ativa else "  ·  inativa")
    with st.expander(titulo):
        st.markdown(
            f"**Como consultar:** {fontes_dados.ROTULOS_ACESSO.get(f['metodo_acesso'], f['metodo_acesso'])}"
            + (f" — {f['acesso_detalhe']}" if f["acesso_detalhe"] else "")
        )
        st.markdown(f"**URL:** {f['url']}")
        c1, c2, c3 = st.columns(3)
        c1.metric("Frequência", fontes_dados.ROTULOS_FREQUENCIA.get(f["frequencia"], f["frequencia"]))
        c2.metric("Última consulta", _fmt_dt(f["ultima_consulta"]))
        c3.metric("Próxima consulta", _fmt_dt(f["proxima_consulta"]) if ativa else "Fonte inativa")
        if f["ultimo_resultado"]:
            st.caption(f"Último resultado: {f['ultimo_resultado']}")
        st.caption(f"Cadastrada em {_shared.formatar_data(f['criado_em'])}")

        with st.form(f"form_fonte_{f['id']}"):
            col_a, col_b = st.columns(2)
            nome = col_a.text_input("Nome", value=f["nome"])
            tipo = col_b.selectbox("Tipo", fontes_dados.TIPOS, index=fontes_dados.TIPOS.index(f["tipo"]) if f["tipo"] in fontes_dados.TIPOS else 0)
            url = st.text_input("URL", value=f["url"])
            col_c, col_d = st.columns(2)
            categoria = col_c.text_input("Categoria", value=f["categoria"] or "")
            freq_chaves = list(fontes_dados.FREQUENCIAS)
            frequencia = col_d.selectbox("Frequência de consulta", freq_chaves, index=freq_chaves.index(f["frequencia"]),
                                         format_func=lambda x: fontes_dados.ROTULOS_FREQUENCIA[x])
            descricao = st.text_area("Descrição", value=f["descricao"] or "")
            observacoes = st.text_area("Observações", value=f["observacoes"] or "")
            ativo = st.checkbox("Fonte ativa", value=ativa)
            salvar = st.form_submit_button("Salvar alterações")
        if salvar:
            try:
                fontes_dados.atualizar(conexao, f["id"], {"nome": nome, "tipo": tipo, "url": url, "categoria": categoria,
                                                          "frequencia": frequencia, "descricao": descricao, "observacoes": observacoes})
                fontes_dados.definir_ativo(conexao, f["id"], ativo)
                _shared.limpar_cache()
                st.rerun()
            except ValueError as erro:
                st.error(str(erro))

        col_x, col_y = st.columns(2)
        if col_x.button("🔎 Avaliar como consultar", key=f"avaliar_fonte_{f['id']}", use_container_width=True):
            with st.spinner("Acessando a fonte..."):
                fontes_dados.registrar_avaliacao(conexao, f["id"], fontes_dados.avaliar_acesso(f["url"]))
            st.rerun()
        if col_y.button("🔄 Consultar agora", key=f"consultar_fonte_{f['id']}", use_container_width=True):
            with st.spinner("Consultando a fonte..."):
                resultado = fontes_dados.coletar_fonte(conexao, f["id"])
            _shared.limpar_cache()
            st.session_state[f"resultado_fonte_{f['id']}"] = resultado["mensagem"]
            st.rerun()
        if st.session_state.get(f"resultado_fonte_{f['id']}"):
            st.info(st.session_state[f"resultado_fonte_{f['id']}"])


def _aba_fontes() -> None:
    conexao = _shared.conectar()
    _shared.secao(
        "Central de Fontes de Dados", "🗂️",
        "Achou um portal de editais, uma base de incentivos ou um feed útil? Cadastre aqui. O sistema avalia COMO a fonte pode ser "
        "consultada (feed, API, página pública ou só manual) — sem inventar coleta. Fontes de Editais com feed RSS/Atom alimentam "
        "o Radar de Editais; as demais ficam registradas para consulta manual ou integração futura.",
    )
    with st.expander("➕ Cadastrar nova fonte", expanded=False):
        with st.form("form_nova_fonte", clear_on_submit=True):
            col_a, col_b = st.columns(2)
            nome = col_a.text_input("Nome da fonte *", placeholder="Ex: Portal de Editais XYZ")
            tipo = col_b.selectbox("Tipo *", fontes_dados.TIPOS)
            url = st.text_input("URL *", placeholder="https://...")
            col_c, col_d = st.columns(2)
            categoria = col_c.text_input("Categoria", placeholder="Ex: Cultura, Esporte, Infância")
            frequencia = col_d.selectbox("Frequência de consulta", list(fontes_dados.FREQUENCIAS),
                                         format_func=lambda x: fontes_dados.ROTULOS_FREQUENCIA[x])
            descricao = st.text_area("Descrição")
            observacoes = st.text_area("Observações")
            ativo = st.checkbox("Fonte ativa", value=True)
            enviar = st.form_submit_button("Cadastrar fonte")
        if enviar:
            try:
                fonte_id = fontes_dados.cadastrar(conexao, {"nome": nome, "tipo": tipo, "url": url, "categoria": categoria,
                                                            "frequencia": frequencia, "descricao": descricao,
                                                            "observacoes": observacoes, "ativo": ativo})
                with st.spinner("Avaliando como a fonte pode ser consultada..."):
                    fontes_dados.registrar_avaliacao(conexao, fonte_id, fontes_dados.avaliar_acesso(url))
                st.success("Fonte cadastrada e avaliada.")
                _shared.limpar_cache()
                st.rerun()
            except ValueError as erro:
                st.error(str(erro))

    cadastradas = fontes_dados.listar(conexao)
    if not cadastradas:
        _shared.estado_vazio("Nenhuma fonte cadastrada pela equipe ainda.", "🗂️")
    else:
        ativas = sum(1 for f in cadastradas if f["ativo"])
        st.caption(f"{len(cadastradas)} fonte(s) cadastrada(s) — {ativas} ativa(s).")
        for f in cadastradas:
            _cartao_fonte(conexao, f)
    conexao.close()

    dados = _shared.carregar_dados_salic(str(_shared.CAMINHO_DB))
    df_fontes = dados["df_fontes"]
    _shared.secao("Fontes já integradas ao sistema", "📚", "Bases oficiais que o sistema já consulta por conta própria.")
    if df_fontes.empty:
        st.info("Nenhuma fonte registrada ainda.")
    else:
        st.dataframe(
            df_fontes.rename(columns={"nome": "Nome", "url": "URL", "tipo": "Finalidade", "coletado_em": "Última coleta"}),
            use_container_width=True, hide_index=True,
            column_config={"Nome": st.column_config.TextColumn(width=520), "URL": st.column_config.TextColumn(width=520),
                           "Finalidade": st.column_config.TextColumn(width=520), "Última coleta": st.column_config.TextColumn(width=220)},
        )

def render() -> None:
    _shared.cabecalho("Configurações", "Como o sistema funciona, os scores, as fontes e a fila de pesquisa.")

    aba_sobre, aba_scores, aba_busca, aba_descoberta, aba_mecanismos, aba_fila, aba_fontes = st.tabs(
        ["Sobre", "Scores", "Inteligência de Contatos", "Descoberta de Empresas", "Mecanismos de Incentivo", "Fila de Pesquisa", "Fontes de Dados"],
        key="aba_configuracoes",
    )
    with aba_sobre:
        _aba_sobre()
    with aba_scores:
        _aba_scores()
    with aba_busca:
        _aba_busca()
    with aba_descoberta:
        _aba_descoberta()
    with aba_mecanismos:
        _aba_mecanismos()
    with aba_fila:
        _aba_fila()
    with aba_fontes:
        _aba_fontes()
