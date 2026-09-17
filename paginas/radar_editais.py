"""Radar de Editais: cadastro de oportunidades (editais, chamadas,
prêmios, fundos, patrocínios) + motor de aderência explicável contra o
perfil do Cérebro da OSC.

Busca automática real via SerpApi quando configurada (ver
processamento/busca_editais.py) — sem chave, cai no cadastro manual/por
agente, do mesmo jeito que o módulo de Contatos já funcionava."""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from processamento import busca_editais, busca_providers, editais, osc
from paginas import _shared

_ROTULOS_STATUS = {
    "ENCONTRADO": "Encontrado", "EM_ANALISE": "Em análise", "ADERENTE": "Aderente",
    "NAO_ADERENTE": "Não aderente", "INTERESSANTE": "Interessante", "EM_PREPARACAO": "Em preparação",
    "INSCRITO": "Inscrito", "APROVADO": "Aprovado", "REPROVADO": "Reprovado", "ENCERRADO": "Encerrado",
}
_ROTULOS_TIPO = {
    "EDITAL": "Edital", "CHAMADA_PUBLICA": "Chamada pública", "PREMIO": "Prêmio",
    "FINANCIAMENTO": "Financiamento", "FUNDO": "Fundo", "PATROCINIO": "Patrocínio",
    "CHAMADA_INSTITUTO_FUNDACAO": "Chamada de instituto/fundação", "OUTRO": "Outro",
}
_ROTULOS_SITUACAO = {
    "ABERTO": ("🟢", "Inscrições abertas", "iorm-badge-verde"),
    "ENCERRADO": ("🔴", "Encerrado", "iorm-badge-vermelho"),
    "PROXIMO": ("🔵", "Em breve", "iorm-badge-azul"),
    "NAO_CONFIRMADO": ("⚪", "Status não confirmado", "iorm-badge-cinza"),
}


def _badge_situacao(situacao: str) -> str:
    emoji, texto, classe = _ROTULOS_SITUACAO.get(situacao, ("⚪", situacao, "iorm-badge-cinza"))
    return f"<span class='iorm-badge {classe}'>{emoji} {texto}</span>"


def _cor_nota(nota: float | None) -> str:
    if nota is None:
        return "iorm-badge-cinza"
    if nota >= 7:
        return "iorm-badge-verde"
    if nota >= 4:
        return "iorm-badge-laranja"
    return "iorm-badge-cinza"


def _mostrar_aderencia(resultado: dict) -> None:
    nota_final = resultado["nota_final"]
    texto_nota = f"{nota_final:.1f}/10" if nota_final is not None else "Não calculável (faltam dados)"
    st.markdown(f"### Aderência: {texto_nota}")

    criterios = [
        ("Área de atuação", resultado["nota_area"]),
        ("Território", resultado["nota_territorio"]),
        ("Público", resultado["nota_publico"]),
        ("Elegibilidade", resultado["nota_elegibilidade"]),
        ("Valor", resultado["nota_valor"]),
        ("Prazo", resultado["nota_prazo"]),
    ]
    cols = st.columns(len(criterios))
    for col, (nome, nota) in zip(cols, criterios):
        texto = f"{nota:.1f}/10" if nota is not None else "s/ dado"
        col.markdown(f"<span class='iorm-badge {_cor_nota(nota)}'>{nome}: {texto}</span>", unsafe_allow_html=True)

    if resultado["motivos_recomendacao"]:
        st.markdown("**Por que recomendamos este edital?**")
        for motivo in resultado["motivos_recomendacao"]:
            st.markdown(f"- {motivo}")
    if resultado["pontos_atencao"]:
        st.markdown("**Pontos de atenção:**")
        for ponto in resultado["pontos_atencao"]:
            st.markdown(f"- {ponto}")


def _formulario_novo_edital(conexao) -> None:
    with st.expander("➕ Cadastrar oportunidade manualmente", expanded=False):
        with st.form("form_novo_edital", clear_on_submit=True):
            col_a, col_b = st.columns(2)
            titulo = col_a.text_input("Título *")
            organizacao = col_b.text_input("Organização promotora")
            tipo = col_a.selectbox("Tipo", list(_ROTULOS_TIPO.keys()), format_func=lambda x: _ROTULOS_TIPO[x])
            status = col_b.selectbox("Status inicial", list(_ROTULOS_STATUS.keys()), format_func=lambda x: _ROTULOS_STATUS[x])
            url = st.text_input("URL")
            fonte = st.text_input("Fonte *", placeholder="Ex: site oficial do programa, e-mail recebido, indicação de parceiro...")
            descricao = st.text_area("Descrição")
            col_c, col_d = st.columns(2)
            territorio = col_c.text_input("Território elegível", placeholder="Ex: Município de Guaíra/SP, ou Nacional")
            publico = col_d.text_input("Público elegível")
            requisitos = st.text_area("Requisitos / elegibilidade")
            col_e, col_f, col_g = st.columns(3)
            valor_texto = col_e.text_input("Valor (texto livre)")
            valor_numerico = col_f.number_input("Valor (número, opcional)", min_value=0.0, step=1000.0)
            data_encerramento = col_g.date_input("Data de encerramento", value=None)
            enviar = st.form_submit_button("Cadastrar oportunidade")

        if enviar:
            if not titulo or not fonte:
                st.error("Título e Fonte são obrigatórios — não dá pra rastrear um edital sem saber de onde ele veio.")
            else:
                edital_id = editais.criar_edital(
                    conexao,
                    {
                        "titulo": titulo, "organizacao_promotora": organizacao or None, "tipo": tipo,
                        "status": status, "url": url or None, "fonte": fonte, "descricao": descricao or None,
                        "territorio": territorio or None, "publico": publico or None, "requisitos": requisitos or None,
                        "valor_texto": valor_texto or None, "valor_numerico": valor_numerico or None,
                        "data_encerramento": data_encerramento.isoformat() if data_encerramento else None,
                    },
                )
                st.success(f"Oportunidade '{titulo}' cadastrada (nº {edital_id}).")
                _shared.limpar_cache()
                st.rerun()


def _busca_manual(lista_editais: list) -> list:
    with st.expander("🔎 Pesquisar oportunidade (busca manual nas cadastradas)", expanded=False):
        col_a, col_b, col_c = st.columns(3)
        palavra_chave = col_a.text_input("Palavra-chave")
        territorio_busca = col_b.text_input("Território (cidade/estado)")
        tipo_busca = col_c.selectbox("Tipo", ["Todos"] + list(_ROTULOS_TIPO.keys()), format_func=lambda x: _ROTULOS_TIPO.get(x, x))
        buscar = st.button("Filtrar")

    if not buscar:
        return lista_editais

    resultado = lista_editais
    if palavra_chave:
        termo = palavra_chave.lower()
        resultado = [e for e in resultado if termo in f"{e['titulo']} {e['descricao'] or ''}".lower()]
    if territorio_busca:
        termo = territorio_busca.lower()
        resultado = [e for e in resultado if termo in (e["territorio"] or "").lower()]
    if tipo_busca != "Todos":
        resultado = [e for e in resultado if e["tipo"] == tipo_busca]
    return resultado


def _secao_busca_automatica(conexao, perfil: dict, perfil_osc_row) -> None:
    provider = busca_providers.obter_provider_ativo()
    usa_busca_ao_vivo = isinstance(provider, busca_providers.SerpApiProvider)

    _shared.secao(
        "Buscar oportunidades reais", "🔍",
        "Pesquisa em fontes públicas (governo, Mapa das OSC/IPEA, Prosas) usando o território e os "
        "temas cadastrados no Cérebro da OSC — nunca inventa edital.",
    )
    if not usa_busca_ao_vivo:
        st.markdown(
            '<div class="iorm-limitacao"><b>Busca automática indisponível agora.</b> Nenhuma chave de '
            "API de busca está configurada (ver Configurações → Inteligência de Contatos). Cadastre "
            "editais manualmente abaixo, ou peça a um agente de pesquisa para encontrá-los.</div>",
            unsafe_allow_html=True,
        )
        return

    if st.button(f"🔍 Buscar oportunidades agora (via {provider.nome})", key="buscar_editais_auto"):
        with st.spinner("Pesquisando em fontes públicas..."):
            resultado_busca = busca_editais.buscar_editais(perfil, provider=provider)
        st.session_state["candidatos_editais"] = resultado_busca

    resultado_busca = st.session_state.get("candidatos_editais")
    if not resultado_busca:
        return

    if resultado_busca["erros"]:
        st.error("A busca não pôde ser concluída: " + " ".join(set(resultado_busca["erros"])))
        return

    candidatos = resultado_busca["candidatos"]
    urls_ja_cadastradas = {e["url"] for e in editais.listar_editais(conexao) if e["url"]}
    candidatos_novos = [c for c in candidatos if c["url"] not in urls_ja_cadastradas]

    if not candidatos:
        st.warning(
            "Busca concluída, mas nenhum resultado foi encontrado nas fontes pesquisadas para o "
            "território/temas cadastrados no momento."
        )
        return

    st.success(f"{len(candidatos)} resultado(s) encontrado(s), {len(candidatos_novos)} ainda não cadastrado(s).")
    for i, candidato in enumerate(candidatos_novos):
        resultado_aderencia = editais.calcular_aderencia(candidato, perfil)
        nota_texto = f"{resultado_aderencia['nota_final']:.1f}/10" if resultado_aderencia["nota_final"] is not None else "s/ nota"
        with st.expander(f"{candidato['titulo']} — Aderência {nota_texto}"):
            st.markdown(_badge_situacao(candidato["situacao_inscricao"]), unsafe_allow_html=True)
            if candidato["descricao"]:
                st.markdown(f"**Trecho encontrado:** {candidato['descricao']}")
            st.caption(f"Fonte: {candidato['fonte']}")
            if candidato["url"]:
                st.link_button("↗ Abrir fonte", candidato["url"])
            _mostrar_aderencia(resultado_aderencia)
            if st.button("➕ Importar para oportunidades cadastradas", key=f"importar_edital_{i}"):
                edital_id = editais.criar_edital(conexao, candidato)
                editais.salvar_aderencia(conexao, edital_id, perfil_osc_row["id"], resultado_aderencia)
                st.success(f"Importado (nº {edital_id}).")
                _shared.limpar_cache()
                st.rerun()


def render() -> None:
    conexao = _shared.conectar()
    perfil_osc_row = osc.obter_osc_principal(conexao)
    _shared.cabecalho("Radar de Editais", "Oportunidades de financiamento — editais, chamadas, prêmios, patrocínios e fundos.")

    if perfil_osc_row is None:
        st.warning("Cadastre o perfil da OSC em **Cérebro da OSC** antes de calcular aderência.")
        conexao.close()
        return
    perfil = osc.carregar_perfil_completo(conexao, perfil_osc_row["id"])

    _secao_busca_automatica(conexao, perfil, perfil_osc_row)
    _formulario_novo_edital(conexao)

    lista_editais = editais.listar_editais(conexao)
    _shared.secao(f"Oportunidades cadastradas ({len(lista_editais)})", "📋")

    if not lista_editais:
        _shared.estado_vazio("Nenhuma oportunidade cadastrada ainda. Use o formulário acima para começar.", "📋")
        conexao.close()
        return

    if st.button("🧭 Encontrar oportunidades para minha OSC (recalcular aderência de todas)"):
        for edital in lista_editais:
            resultado = editais.calcular_aderencia(dict(edital), perfil)
            editais.salvar_aderencia(conexao, edital["id"], perfil_osc_row["id"], resultado)
        st.success("Aderência recalculada para todas as oportunidades cadastradas, com base no perfil atual da OSC.")
        _shared.limpar_cache()
        st.rerun()

    lista_editais = _busca_manual(lista_editais)

    for edital in lista_editais:
        resultado = editais.calcular_aderencia(dict(edital), perfil)
        nota_texto = f"{resultado['nota_final']:.1f}/10" if resultado["nota_final"] is not None else "s/ nota"
        with st.expander(f"{edital['titulo']} — {_ROTULOS_STATUS.get(edital['status'], edital['status'])} — Aderência {nota_texto}"):
            situacao = edital["situacao_inscricao"] if "situacao_inscricao" in edital.keys() else "NAO_CONFIRMADO"
            st.markdown(_badge_situacao(situacao), unsafe_allow_html=True)
            col_a, col_b = st.columns(2)
            col_a.markdown(f"**Organização:** {edital['organizacao_promotora'] or 'Não disponível'}")
            col_b.markdown(f"**Tipo:** {_ROTULOS_TIPO.get(edital['tipo'], edital['tipo'])}")
            col_a.markdown(f"**Território:** {edital['territorio'] or 'Não disponível'}")
            col_b.markdown(f"**Público:** {edital['publico'] or 'Não disponível'}")
            col_a.markdown(f"**Valor:** {edital['valor_texto'] or (_shared.formatar_moeda(edital['valor_numerico']) if edital['valor_numerico'] else 'Não disponível')}")
            col_b.markdown(f"**Encerramento:** {_shared.formatar_data(edital['data_encerramento'])}")
            if edital["descricao"]:
                st.markdown(f"**Descrição:** {edital['descricao']}")
            if edital["url"]:
                st.link_button("↗ Abrir fonte", edital["url"])
            st.caption(f"Fonte: {edital['fonte']} · Coletado em {_shared.formatar_data(edital['coletado_em'])}")

            _mostrar_aderencia(resultado)

            novo_status = st.selectbox(
                "Status", list(_ROTULOS_STATUS.keys()), index=list(_ROTULOS_STATUS.keys()).index(edital["status"]),
                format_func=lambda x: _ROTULOS_STATUS[x], key=f"status_{edital['id']}",
            )
            if novo_status != edital["status"]:
                if st.button("Salvar novo status", key=f"salvar_status_{edital['id']}"):
                    editais.atualizar_status(conexao, edital["id"], novo_status)
                    st.success("Status atualizado.")
                    _shared.limpar_cache()
                    st.rerun()

    conexao.close()
