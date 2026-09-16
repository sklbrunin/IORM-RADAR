"""Radar de Editais: cadastro de oportunidades (editais, chamadas,
prêmios, fundos, patrocínios) + motor de aderência explicável contra o
perfil do Cérebro da OSC.

Sem busca automática nesta versão — ver aviso na tela e em
docs/decisoes.md sobre o motivo."""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from processamento import editais, osc
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


def render() -> None:
    conexao = _shared.conectar()
    perfil_osc_row = osc.obter_osc_principal(conexao)
    _shared.cabecalho("Radar de Editais", "Oportunidades de financiamento — editais, chamadas, prêmios, patrocínios e fundos.")

    st.markdown(
        '<div class="iorm-limitacao"><b>Busca automática indisponível.</b> Este ambiente ainda não tem '
        "nenhuma fonte de editais conectada (nenhuma API/portal foi integrado nesta etapa). As "
        "oportunidades abaixo são as que já foram <b>cadastradas manualmente</b> (ou por um agente de "
        "pesquisa, do mesmo jeito que o módulo de Contatos funciona). O motor de aderência já funciona "
        "de verdade sobre o que estiver cadastrado.</div>",
        unsafe_allow_html=True,
    )

    if perfil_osc_row is None:
        st.warning("Cadastre o perfil da OSC em **Cérebro da OSC** antes de calcular aderência.")
        conexao.close()
        return
    perfil = osc.carregar_perfil_completo(conexao, perfil_osc_row["id"])

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
                st.markdown(f"**URL:** {edital['url']}")
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
