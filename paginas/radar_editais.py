"""Radar de Editais: oportunidades de financiamento (editais, chamadas, prêmios, fundos, patrocínios).

Regra central: a visão padrão mostra só o que ainda dá para aproveitar — editais ABERTOS (prazo real
que ainda não passou, com link para conferir). O que não dá para afirmar fica em "Não confirmados";
o que já passou (ou é registro de teste) fica em "Encerrados e histórico" — guardado, nunca apagado.
A aderência é sempre explicada critério a critério; onde a fonte não informa, diz "Não identificado na fonte"."""
from __future__ import annotations

from datetime import date, datetime

import streamlit as st

from processamento import busca_editais, busca_providers, editais, fontes_dados, links_editais, osc
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
_BADGE_SITUACAO = {
    editais.SITUACAO_ABERTO: ("🟢", "ABERTO", "iorm-badge-verde"),
    editais.SITUACAO_ENCERRADO: ("🔴", "ENCERRADO", "iorm-badge-vermelho"),
    editais.SITUACAO_NAO_CONFIRMADO: ("⚪", "NÃO CONFIRMADO", "iorm-badge-cinza"),
}
_ROTULOS_CRITERIO = {
    "area": "Área de atuação", "territorio": "Território", "publico": "Público", "elegibilidade": "Elegibilidade",
    "valor": "Valor", "prazo": "Prazo",
}
_ABAS = {"abertos": "🟢 Abertos", "nao_confirmados": "⚪ Não confirmados", "encerrados": "📁 Encerrados e histórico"}
_ABA_BUSCA = "🔍 Buscar e cadastrar"


def _v(edital, chave, padrao=None):
    try:
        valor = edital[chave]
    except (KeyError, IndexError):
        return padrao
    return padrao if valor is None else valor


# --------------------------------------------------------------------------- blocos da ficha
def _bloco_links(edital, chave: str, conexao=None, candidato: bool = False) -> None:
    """VER EDITAL / INSCREVER-SE com a honestidade exigida: o botão de edital só é "VER EDITAL"
    quando a página não é portal genérico; o de inscrição só existe se um link de inscrição foi
    encontrado — do contrário, o texto diz que não foi localizado."""
    url = _v(edital, "url")
    url_inscricao = _v(edital, "url_inscricao")
    status = _v(edital, "link_status", "NAO_VERIFICADO")
    generico_provavel = _v(edital, "link_generico_provavel", False) or status == links_editais.STATUS_GENERICO

    col_a, col_b = st.columns(2)
    with col_a:
        if not url:
            st.markdown("<div class='iorm-aviso'>Este edital não tem link cadastrado.</div>", unsafe_allow_html=True)
        elif generico_provavel:
            st.link_button("↗ Abrir portal (página genérica)", url, use_container_width=True)
            motivo = _v(edital, "link_generico_motivo") or _v(edital, "link_motivo") or "endereço genérico"
            st.caption(f"⚠ Não é a página específica do edital: {motivo}.")
        else:
            st.link_button("VER EDITAL", url, type="primary", use_container_width=True)
    with col_b:
        if url_inscricao:
            verificada = bool(_v(edital, "inscricao_verificada", 0))
            st.link_button("INSCREVER-SE", url_inscricao, use_container_width=True)
            st.caption("✓ Link de inscrição verificado (responde)." if verificada else "Link de inscrição ainda não verificado.")
        else:
            st.markdown("<div class='iorm-aviso'>Link direto de inscrição não localizado.</div>", unsafe_allow_html=True)

    if not candidato:
        rotulo = links_editais.ROTULOS_STATUS.get(status, status)
        verificado_em = _v(edital, "link_verificado_em")
        st.caption(
            f"Verificação do link: {rotulo}"
            + (f" — {_v(edital, 'link_motivo')}" if _v(edital, "link_motivo") else "")
            + (f" · verificado em {_shared.formatar_data(verificado_em)}" if verificado_em else "")
        )
        if conexao is not None and url and st.button("🔄 Verificar link agora", key=f"verificar_link_{chave}"):
            with st.spinner("Acessando a página do edital..."):
                editais.verificar_e_registrar(conexao, edital["id"])
            _shared.limpar_cache()
            st.rerun()


def _badge_situacao(situacao: str) -> str:
    emoji, texto, classe = _BADGE_SITUACAO.get(situacao, ("⚪", situacao, "iorm-badge-cinza"))
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
    """Nota final + os seis critérios com a explicação usada no cálculo. Nada de justificativa
    inventada: critério sem dado na fonte aparece como "Não identificado na fonte"."""
    st.markdown(f"### Aderência: {_shared.formatar_nota(resultado['nota_final'])}")
    if resultado["nota_final"] is None:
        st.caption("Não há dados suficientes no edital para calcular a aderência.")
    else:
        avaliados, total = resultado.get("criterios_avaliados"), resultado.get("criterios_total")
        if avaliados is not None:
            aviso = " — poucos dados na fonte, trate a nota com cautela" if avaliados < 3 else ""
            st.caption(f"Nota calculada com {avaliados} de {total} critérios (só entram os que a fonte permite avaliar){aviso}.")
    for detalhe in resultado.get("detalhes", []):
        nome = _ROTULOS_CRITERIO.get(detalhe["criterio"], detalhe["criterio"])
        nota = detalhe["nota"]
        if nota is None:
            texto_nota, explicacao = "Não identificado na fonte", detalhe["motivo"]
        else:
            texto_nota, explicacao = _shared.formatar_nota(nota), detalhe["motivo"]
        st.markdown(
            f"<div class='iorm-crit'><span class='iorm-badge {_cor_nota(nota)}'>{nome}: {texto_nota}</span>"
            f"<span class='iorm-crit-texto'>{explicacao}</span></div>",
            unsafe_allow_html=True,
        )


def _prazo_texto(edital) -> str:
    texto = _shared.formatar_data(_v(edital, "data_encerramento"))
    try:
        dias = (datetime.fromisoformat(str(edital["data_encerramento"])[:10]).date() - date.today()).days
    except (KeyError, TypeError, ValueError):
        return texto
    if dias > 1:
        return f"{texto} (faltam {dias} dias)"
    if dias == 1:
        return f"{texto} (falta 1 dia)"
    if dias == 0:
        return f"{texto} (encerra hoje)"
    return f"{texto} (encerrou há {abs(dias)} dia(s))"


def _valor_texto(edital) -> str:
    if _v(edital, "valor_texto"):
        return edital["valor_texto"]
    if _v(edital, "valor_numerico"):
        return _shared.formatar_moeda(edital["valor_numerico"])
    return "Não identificado na fonte"


def _bloco_confirmar_prazo(edital, conexao) -> None:
    """Editais sem prazo confirmado: mostra a data que a página traz (com o trecho literal) para a
    equipe conferir e confirmar — ou permite informar a data. Nada vira "aberto" sem essa confirmação."""
    sugerido = _v(edital, "prazo_sugerido")
    with st.container(border=True):
        st.markdown("**Confirmar prazo** — o edital só passa a “Aberto” quando a equipe confirma a data de encerramento.")
        if sugerido:
            st.markdown(
                f"A página do edital menciona **{_shared.formatar_data(sugerido)}**: "
                f"_“{_v(edital, 'prazo_sugerido_trecho', '')}”_"
            )
            if st.button(f"✔ Confirmar {_shared.formatar_data(sugerido)} como data de encerramento",
                         key=f"confirmar_prazo_{edital['id']}"):
                editais.confirmar_prazo(conexao, edital["id"])
                _shared.limpar_cache()
                st.rerun()
        else:
            st.caption("Nenhuma data foi encontrada na página (ou o link ainda não foi verificado). Se souber o prazo, informe abaixo.")
        col_d, col_b = st.columns([2, 2])
        data_manual = col_d.date_input("Informar o prazo manualmente", value=None, format="DD/MM/YYYY", key=f"prazo_manual_{edital['id']}")
        col_b.write("")
        if col_b.button("Salvar prazo informado", key=f"salvar_prazo_{edital['id']}", disabled=data_manual is None):
            editais.confirmar_prazo(conexao, edital["id"], data_manual.isoformat())
            _shared.limpar_cache()
            st.rerun()


def _ficha_edital(edital, resultado: dict, conexao) -> None:
    """Ficha completa: situação (com o motivo), dados, requisitos, links, aderência e fonte."""
    situacao, motivo = editais.situacao_efetiva(edital)
    st.markdown(_badge_situacao(situacao), unsafe_allow_html=True)
    st.caption(motivo)
    if _v(edital, "origem_descoberta") == editais.ORIGEM_TESTE:
        st.markdown(
            "<div class='iorm-limitacao'><b>Registro de teste — não é um edital real.</b> Foi cadastrado "
            "durante o desenvolvimento para testar a aderência; não use como oportunidade.</div>",
            unsafe_allow_html=True,
        )

    if situacao == editais.SITUACAO_NAO_CONFIRMADO and _v(edital, "origem_descoberta") != editais.ORIGEM_TESTE:
        _bloco_confirmar_prazo(edital, conexao)

    nd = "Não identificado na fonte"
    col_a, col_b = st.columns(2)
    col_a.markdown(f"**Instituição:** {_v(edital, 'organizacao_promotora', nd)}")
    col_b.markdown(f"**Tipo:** {_ROTULOS_TIPO.get(edital['tipo'], edital['tipo'])}")
    col_a.markdown(f"**Área temática:** {_v(edital, 'area_tematica', nd)}")
    col_b.markdown(f"**Público:** {_v(edital, 'publico', nd)}")
    col_a.markdown(f"**Localização / território:** {_v(edital, 'territorio', nd)}")
    col_b.markdown(f"**Valor:** {_valor_texto(edital)}")
    col_a.markdown(f"**Abertura:** {_shared.formatar_data(edital['data_abertura']) if _v(edital, 'data_abertura') else nd}")
    col_b.markdown(f"**Encerramento:** {_prazo_texto(edital) if _v(edital, 'data_encerramento') else nd}")

    if _v(edital, "descricao"):
        st.markdown(f"**Descrição:** {edital['descricao']}")
    st.markdown(f"**Requisitos:** {_v(edital, 'requisitos', nd)}")

    _bloco_links(edital, str(edital["id"]), conexao)
    st.caption(f"Fonte: {edital['fonte']} · Coletado em {_shared.formatar_data(edital['coletado_em'])}")

    _mostrar_aderencia(resultado)

    novo_status = st.selectbox(
        "Acompanhamento interno (status)", list(_ROTULOS_STATUS.keys()),
        index=list(_ROTULOS_STATUS.keys()).index(edital["status"]),
        format_func=lambda x: _ROTULOS_STATUS[x], key=f"status_{edital['id']}",
    )
    if novo_status != edital["status"] and st.button("Salvar novo status", key=f"salvar_status_{edital['id']}"):
        editais.atualizar_status(conexao, edital["id"], novo_status)
        st.success("Status atualizado.")
        _shared.limpar_cache()
        st.rerun()


def _lista(itens: list, perfil: dict, conexao, foco: int | None, vazio: str, chave: str) -> None:
    """Uma linha expansível por edital, com o título COMPLETO. O edital em foco (vindo do Dashboard)
    vem primeiro e já aberto."""
    if not itens:
        _shared.estado_vazio(vazio, "📋")
        return
    if foco is not None:
        itens = sorted(itens, key=lambda e: e["id"] != foco)
    for edital in itens:
        dados = dict(edital)
        resultado = editais.calcular_aderencia(dados, perfil)
        partes = [dados["titulo"], f"Aderência {_shared.formatar_nota(resultado['nota_final'])}"]
        if dados.get("data_encerramento"):
            partes.append(f"até {_shared.formatar_data(dados['data_encerramento'])}")
        with st.expander("  ·  ".join(partes), expanded=(dados["id"] == foco)):
            _ficha_edital(dados, resultado, conexao)


# --------------------------------------------------------------------------- cadastro e busca
def _formulario_novo_edital(conexao) -> None:
    with st.expander("➕ Cadastrar oportunidade manualmente", expanded=False):
        with st.form("form_novo_edital", clear_on_submit=True):
            col_a, col_b = st.columns(2)
            titulo = col_a.text_input("Título *")
            organizacao = col_b.text_input("Organização promotora")
            tipo = col_a.selectbox("Tipo", list(_ROTULOS_TIPO.keys()), format_func=lambda x: _ROTULOS_TIPO[x])
            status = col_b.selectbox("Status inicial", list(_ROTULOS_STATUS.keys()), format_func=lambda x: _ROTULOS_STATUS[x])
            url = st.text_input("URL da página do edital")
            fonte = st.text_input("Fonte *", placeholder="Ex: site oficial do programa, e-mail recebido, indicação de parceiro...")
            descricao = st.text_area("Descrição")
            col_c, col_d = st.columns(2)
            territorio = col_c.text_input("Território elegível", placeholder="Ex: Município de Guaíra/SP, ou Nacional")
            publico = col_d.text_input("Público elegível")
            area = st.text_input("Área temática")
            requisitos = st.text_area("Requisitos / elegibilidade")
            col_e, col_f, col_g = st.columns(3)
            valor_texto = col_e.text_input("Valor (texto livre)")
            valor_numerico = col_f.number_input("Valor (número, opcional)", min_value=0.0, step=1000.0)
            data_encerramento = col_g.date_input("Data de encerramento", value=None, format="DD/MM/YYYY")
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
                        "area_tematica": area or None, "valor_texto": valor_texto or None,
                        "valor_numerico": valor_numerico or None,
                        "data_encerramento": data_encerramento.isoformat() if data_encerramento else None,
                    },
                )
                st.success(f"Oportunidade '{titulo}' cadastrada (nº {edital_id}).")
                _shared.limpar_cache()
                st.rerun()


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
        situacao, motivo = editais.situacao_efetiva(candidato)
        with st.expander(f"{candidato['titulo']}  ·  Aderência {_shared.formatar_nota(resultado_aderencia['nota_final'])}"):
            st.markdown(_badge_situacao(situacao), unsafe_allow_html=True)
            st.caption(motivo)
            if candidato["descricao"]:
                st.markdown(f"**Trecho encontrado:** {candidato['descricao']}")
            st.caption(f"Fonte: {candidato['fonte']} · URL: {candidato['url']}")
            _bloco_links(candidato, f"cand_{i}", candidato=True)
            _mostrar_aderencia(resultado_aderencia)
            if st.button("➕ Importar para oportunidades cadastradas", key=f"importar_edital_{i}"):
                edital_id = editais.criar_edital(conexao, candidato)
                editais.salvar_aderencia(conexao, edital_id, perfil_osc_row["id"], resultado_aderencia)
                with st.spinner("Verificando o link do edital..."):
                    editais.verificar_e_registrar(conexao, edital_id)
                st.success(f"Importado e link verificado (nº {edital_id}). Ele entra em Abertos só se a fonte trouxer um prazo futuro.")
                _shared.limpar_cache()
                st.rerun()


def _secao_fontes_cadastradas(conexao) -> None:
    """Usa as Fontes de Dados cadastradas (Configurações → Fontes de Dados) do tipo Editais."""
    fontes = [f for f in fontes_dados.listar(conexao, somente_ativas=True) if f["tipo"] == "Editais"]
    _shared.secao("Fontes cadastradas pela equipe", "🗂️",
                  "Fontes de Editais ativas em Configurações → Fontes de Dados. Só as que oferecem feed RSS/Atom são coletadas automaticamente.")
    if not fontes:
        st.caption("Nenhuma fonte ativa do tipo Editais. Cadastre uma em Configurações → Fontes de Dados.")
        return
    for f in fontes:
        st.markdown(f"- **{f['nome']}** — {fontes_dados.ROTULOS_ACESSO.get(f['metodo_acesso'], f['metodo_acesso'])}")
    if st.button("🔄 Consultar fontes cadastradas agora", key="consultar_fontes_editais"):
        with st.spinner("Consultando as fontes..."):
            resultados = [fontes_dados.coletar_fonte(conexao, f["id"]) for f in fontes]
        for r in resultados:
            st.markdown(f"- **{r['fonte']}:** {r['mensagem']}")
        _shared.limpar_cache()


def _filtrar(itens: list, termo: str, tipo: str) -> list:
    termo = (termo or "").strip().lower()
    resultado = []
    for e in itens:
        if tipo != "Todos" and e["tipo"] != tipo:
            continue
        if termo and termo not in " ".join(str(e[c] or "") for c in ("titulo", "descricao", "territorio", "organizacao_promotora", "area_tematica")).lower():
            continue
        resultado.append(e)
    return resultado


def render() -> None:
    conexao = _shared.conectar()
    perfil_osc_row = osc.obter_osc_principal(conexao)
    _shared.cabecalho("Radar de Editais", "Oportunidades abertas para a OSC — com prazo, aderência explicada e link para conferir.")

    if perfil_osc_row is None:
        st.warning("Cadastre o perfil da OSC em **Cérebro da OSC** antes de calcular aderência.")
        conexao.close()
        return
    perfil = osc.carregar_perfil_completo(conexao, perfil_osc_row["id"])

    todos = editais.listar_editais(conexao)
    grupos = editais.agrupar_por_situacao(todos)
    historico = grupos["encerrados"] + grupos["testes"]

    # Edital pedido por outra página (ex.: Dashboard): vira o foco e leva ao tab onde ele está.
    foco = st.session_state.get("edital_em_foco")
    rotulos = dict(_ABAS)  # rótulos fixos (as contagens ficam nos números acima): a aba escolhida não se perde ao recarregar
    aba_padrao = rotulos["abertos"]
    if foco is not None:
        for chave, itens in (("abertos", grupos["abertos"]), ("nao_confirmados", grupos["nao_confirmados"]), ("encerrados", historico)):
            if any(e["id"] == foco for e in itens):
                aba_padrao = rotulos[chave]
                break
        else:
            foco = None

    c1, c2, c3 = st.columns(3)
    c1.metric("Abertos", len(grupos["abertos"]), help="Prazo de encerramento real que ainda não passou, com link da fonte.")
    c2.metric("Não confirmados", len(grupos["nao_confirmados"]), help="A fonte não informa prazo, ou não há link para conferir. Nunca tratados como abertos.")
    c3.metric("Encerrados e histórico", len(historico), help="Prazo vencido, encerrado pela fonte/equipe, ou registro de teste. Guardados, nunca apagados.")

    col_f1, col_f2 = st.columns([3, 1])
    termo = col_f1.text_input("Pesquisar nos editais", placeholder="Palavra-chave, território, instituição ou área", key="busca_editais_termo")
    tipo = col_f2.selectbox("Tipo", ["Todos"] + list(_ROTULOS_TIPO.keys()), format_func=lambda x: _ROTULOS_TIPO.get(x, x), key="busca_editais_tipo")

    rotulo_busca = _ABA_BUSCA
    opcoes = [rotulos["abertos"], rotulos["nao_confirmados"], rotulos["encerrados"], rotulo_busca]
    if foco is not None:
        col_foco, col_limpar = st.columns([4, 1])
        col_foco.info("Edital aberto a partir do Dashboard — ele aparece primeiro na lista, com a ficha completa.")
        if col_limpar.button("Limpar seleção", key="limpar_foco_edital", use_container_width=True):
            st.session_state.pop("edital_em_foco", None)
            st.rerun()
    aba_abertos, aba_nc, aba_enc, aba_busca = st.tabs(opcoes, default=aba_padrao, key="aba_editais")

    with aba_abertos:
        abertos = editais.abertos_com_aderencia(_filtrar(grupos["abertos"], termo, tipo), perfil)
        st.caption("Ordenados por aderência ao perfil da OSC (do mais para o menos aderente).")
        _lista(abertos, perfil, conexao, foco,
               "Nenhum edital aberto e verificável no momento. Veja “Não confirmados”, use a busca ou cadastre um edital.", "ab")
    with aba_nc:
        st.caption("Editais encontrados que ainda não dá para afirmar que estão abertos — confira o link e a data na fonte.")
        _lista(_filtrar(grupos["nao_confirmados"], termo, tipo), perfil, conexao, foco, "Nenhum edital aguardando confirmação.", "nc")
    with aba_enc:
        st.caption("Histórico: não são oportunidades ativas. Ficam guardados para consulta.")
        _lista(_filtrar(historico, termo, tipo), perfil, conexao, foco, "Nenhum edital encerrado ainda.", "en")
    with aba_busca:
        _secao_busca_automatica(conexao, perfil, perfil_osc_row)
        _secao_fontes_cadastradas(conexao)
        _formulario_novo_edital(conexao)
        if todos and st.button("🧭 Recalcular aderência de todos os editais (registra no histórico)"):
            for edital in todos:
                resultado = editais.calcular_aderencia(dict(edital), perfil)
                editais.salvar_aderencia(conexao, edital["id"], perfil_osc_row["id"], resultado)
            st.success("Aderência recalculada para todos os editais cadastrados, com base no perfil atual da OSC.")
            _shared.limpar_cache()

    conexao.close()
