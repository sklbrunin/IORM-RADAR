"""Configurações / Administração: explicação do sistema, fórmulas dos
scores, status da API de busca, mecanismos de incentivo, fila de
pesquisa pendente e catálogo de fontes de dados."""
from __future__ import annotations

import os

import pandas as pd
import streamlit as st

from processamento import busca_providers, contact_providers, mecanismos
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
        elegibilidade 15%, valor 10%, prazo 15%.
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


def _aba_mecanismos() -> None:
    _shared.secao("Mecanismos de incentivo/captação", "⚖️", "Arquitetura multi-fonte — status real de cada integração.")
    contagem = mecanismos.contar_por_status()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🟢 Integradas", contagem["INTEGRADA"])
    c2.metric("🟡 Parciais", contagem["PARCIAL"])
    c3.metric("🔵 Manuais", contagem["MANUAL"])
    c4.metric("🔴 Indisponíveis", contagem["INDISPONIVEL"])

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


def _aba_fontes() -> None:
    dados = _shared.carregar_dados_salic(str(_shared.CAMINHO_DB))
    df_fontes = dados["df_fontes"]
    _shared.secao("Fontes de Dados já integradas", "📚")
    if df_fontes.empty:
        st.info("Nenhuma fonte registrada ainda.")
    else:
        st.dataframe(
            df_fontes.rename(columns={"nome": "Nome", "url": "URL", "tipo": "Finalidade", "coletado_em": "Última coleta"}),
            use_container_width=True, hide_index=True,
        )


def render() -> None:
    _shared.cabecalho("Configurações", "Como o sistema funciona, os scores, as fontes e a fila de pesquisa.")

    aba_sobre, aba_scores, aba_busca, aba_mecanismos, aba_fila, aba_fontes = st.tabs(
        ["Sobre", "Scores", "Inteligência de Contatos", "Mecanismos de Incentivo", "Fila de Pesquisa", "Fontes de Dados"]
    )
    with aba_sobre:
        _aba_sobre()
    with aba_scores:
        _aba_scores()
    with aba_busca:
        _aba_busca()
    with aba_mecanismos:
        _aba_mecanismos()
    with aba_fila:
        _aba_fila()
    with aba_fontes:
        _aba_fontes()
