"""CRM de Captação: pipeline (estilo Kanban), interações e follow-ups.

Toda oportunidade pode (opcionalmente) estar ligada a uma empresa do
Radar — sem precisar recadastrar nada."""
from __future__ import annotations

import re
from datetime import date

import pandas as pd
import streamlit as st
from streamlit_sortables import sort_items

from processamento import crm, osc
from paginas import _shared

def _estilo_kanban() -> str:
    """CSS do quadro Kanban. O componente roda num iframe: ele NÃO enxerga as variáveis CSS da página, então as cores do
    tema ativo (claro/escuro) são injetadas aqui como valores."""
    c = _shared.tokens_do_tema()
    return f"""
.sortable-component {{ display: flex; gap: 0.7rem; overflow-x: auto; padding-bottom: 0.5rem; }}
.sortable-container {{
    background: {c['superficie-alt']}; border: 1px solid {c['borda']};
    border-radius: 10px; min-width: 210px; flex: 1 1 0;
}}
.sortable-container-header {{
    font-weight: 800; color: {c['navy']} !important; font-size: 0.74rem; text-transform: uppercase;
    letter-spacing: 0.03em; padding: 0.6rem 0.7rem 0.5rem 0.7rem; border-bottom: 2px solid {c['borda']};
}}
.sortable-container-body {{ padding: 0.5rem; min-height: 120px; }}
.sortable-item {{
    background: {c['superficie']} !important; color: {c['navy']} !important; border: 1px solid {c['borda']}; border-left: 4px solid {c['azul-claro']};
    border-radius: 8px; padding: 0.55rem 0.65rem; margin-bottom: 0.5rem; font-size: 0.82rem; cursor: grab;
    text-align: left; white-space: normal; line-height: 1.35;
}}
.sortable-item:hover {{ border-color: {c['azul']}; color: {c['navy']} !important; }}
.sortable-item:focus {{ color: {c['navy']} !important; }}
.sortable-item.dragging {{ opacity: 0.6; }}
"""

_PADRAO_ID_CARTAO = re.compile(r"^#(\d+)")


def _rotulo_cartao(op: dict) -> str:
    empresa_nome = op.get("empresa_nome") or "Sem empresa vinculada"
    valor = _shared.formatar_moeda(op["valor_potencial"]) if op["valor_potencial"] else "Valor não informado"
    return f"#{op['id']} — {op['titulo']} · {empresa_nome} · {valor}"


def _linha_para_dict(linha) -> dict:
    return dict(linha)


def _formulario_nova_oportunidade(conexao, df_empresas: pd.DataFrame, programas_osc: list[dict]) -> None:
    with st.expander("➕ Nova oportunidade", expanded=False):
        opcoes_empresa = {"Nenhuma (oportunidade avulsa)": None}
        for linha in df_empresas.sort_values("razao_social").itertuples():
            opcoes_empresa[f"{linha.razao_social} ({linha.cidade or 'cidade não disponível'})"] = linha.id
        opcoes_programa = ["Nenhum"] + [p["nome"] for p in programas_osc]

        with st.form("form_nova_oportunidade", clear_on_submit=True):
            titulo = st.text_input("Título *")
            empresa_escolha = st.selectbox("Empresa (opcional)", list(opcoes_empresa.keys()))
            programa_escolha = st.selectbox(
                "Programa/projeto do IORM relacionado (opcional)", opcoes_programa,
                help="Vem do Cérebro da OSC — associar a oportunidade a um programa ajuda a priorizar.",
            )
            col_a, col_b, col_c = st.columns(3)
            mecanismo = col_a.text_input("Mecanismo", placeholder="Ex: Lei Rouanet")
            valor_potencial = col_b.number_input("Valor potencial (R$)", min_value=0.0, step=1000.0)
            probabilidade = col_c.slider("Probabilidade (%)", 0, 100, 20)
            responsavel = st.text_input("Responsável")
            enviar = st.form_submit_button("Criar oportunidade")

        if enviar:
            if not titulo:
                st.error("Título é obrigatório.")
            else:
                op_id = crm.criar_oportunidade(
                    conexao,
                    {
                        "empresa_id": opcoes_empresa[empresa_escolha], "titulo": titulo,
                        "mecanismo": mecanismo or None, "valor_potencial": valor_potencial or None,
                        "probabilidade": probabilidade, "responsavel": responsavel or None,
                        "programa_relacionado": programa_escolha if programa_escolha != "Nenhum" else None,
                    },
                )
                st.success(f"Oportunidade '{titulo}' criada (nº {op_id}).")
                _shared.limpar_cache()
                st.rerun()


@st.dialog("Remover oportunidade do Pipeline?")
def _confirmar_remocao(op: dict) -> None:
    """Confirmação obrigatória: nada sai do Pipeline sem o usuário clicar em Remover."""
    st.markdown(f"**#{op['id']} — {op['titulo']}**")
    st.markdown(f"Empresa: {op.get('empresa_nome') or 'Sem empresa vinculada'} · Estágio: {op['estagio']}")
    st.caption(
        "A oportunidade sai do Pipeline. A empresa, os contatos e o histórico de interações continuam guardados, "
        "e você pode restaurá-la depois em “Removidas”."
    )
    motivo = st.text_input("Motivo (opcional)", key=f"motivo_remocao_{op['id']}")
    col_cancelar, col_remover = st.columns(2)
    if col_cancelar.button("Cancelar", key=f"cancelar_remocao_{op['id']}", use_container_width=True):
        st.rerun()
    if col_remover.button("Remover", type="primary", key=f"confirmar_remocao_{op['id']}", use_container_width=True):
        conexao = _shared.conectar()
        crm.remover_oportunidade(conexao, op["id"], motivo)
        conexao.close()
        _shared.limpar_cache()
        st.toast(f"Oportunidade #{op['id']} removida do Pipeline.", icon="🗑")
        st.rerun()


def _secao_remover(oportunidades: list[dict]) -> None:
    """Remoção logo abaixo do quadro: escolhe a oportunidade e abre a janela de confirmação."""
    if not oportunidades:
        return
    opcoes = {f"#{op['id']} — {op['titulo']} ({op['estagio']})": op for op in oportunidades}
    col_sel, col_btn = st.columns([4, 1])
    escolha = col_sel.selectbox("Remover uma oportunidade do Pipeline", list(opcoes.keys()), index=None,
                                placeholder="Escolha a oportunidade a remover", key="remover_escolha")
    col_btn.write("")
    if col_btn.button("🗑 Remover…", key="remover_abrir", disabled=escolha is None, use_container_width=True):
        _confirmar_remocao(opcoes[escolha])


def _secao_removidas(conexao) -> None:
    removidas = crm.listar_removidas(conexao)
    if not removidas:
        return
    with st.expander(f"🗂 Removidas do Pipeline ({len(removidas)}) — restaurar"):
        for r in removidas:
            col_txt, col_btn = st.columns([4, 1])
            motivo = f" · motivo: {r['motivo_remocao']}" if r["motivo_remocao"] else ""
            col_txt.markdown(
                f"**#{r['id']} — {r['titulo']}** · {r['empresa_nome'] or 'Sem empresa'} · {r['estagio']} · "
                f"removida em {_shared.formatar_data(r['removida_em'])}{motivo}"
            )
            if col_btn.button("Restaurar", key=f"restaurar_{r['id']}", use_container_width=True):
                crm.restaurar_oportunidade(conexao, r["id"])
                _shared.limpar_cache()
                st.rerun()


def assinatura_do_quadro(oportunidades: list[dict]) -> str:
    """Identifica o CONTEÚDO do quadro (quais cartões, em qual coluna e com qual título). É parte da chave do
    componente Kanban: o componente guarda o próprio estado no navegador e, com chave fixa, continuava mostrando
    o cartão removido até recarregar a página. Mudou o conteúdo → chave nova → o quadro é remontado na hora."""
    import hashlib

    bruto = "|".join(f"{op['id']}:{op['estagio']}:{_rotulo_cartao(op)}" for op in sorted(oportunidades, key=lambda o: o["id"]))
    return hashlib.md5(bruto.encode("utf-8")).hexdigest()[:10]


def _kanban(conexao, oportunidades: list[dict]) -> None:
    _shared.secao(
        "Pipeline de Captação", "🔀",
        "Arraste um card para outra coluna para mudar o estágio — a alteração é salva no banco na hora.",
    )

    por_id = {op["id"]: op for op in oportunidades}
    estrutura = [
        {"header": estagio, "items": [_rotulo_cartao(op) for op in oportunidades if op["estagio"] == estagio]}
        for estagio in crm.ESTAGIOS
    ]

    resultado = sort_items(
        estrutura, multi_containers=True, direction="horizontal",
        custom_style=_estilo_kanban(), key=f"kanban_pipeline_{assinatura_do_quadro(oportunidades)}",
    )

    # Compara com o estado salvo: qualquer cartão que apareça agora sob um header
    # diferente do estágio atual no banco foi arrastado — persiste e recarrega.
    moveu = False
    for container in resultado:
        novo_estagio = container["header"]
        for rotulo in container["items"]:
            m = _PADRAO_ID_CARTAO.match(rotulo)
            if not m:
                continue
            op_id = int(m.group(1))
            op = por_id.get(op_id)
            if op and op["estagio"] != novo_estagio:
                crm.mover_estagio(conexao, op_id, novo_estagio)
                moveu = True

    if moveu:
        st.toast("Estágio atualizado.", icon="✅")
        _shared.limpar_cache()
        st.rerun()

    st.caption(
        " · ".join(f"{estagio}: {len([op for op in oportunidades if op['estagio'] == estagio])}" for estagio in crm.ESTAGIOS)
    )


def _secao_detalhe(conexao, oportunidades: list[dict]) -> None:
    _shared.secao("Detalhe da oportunidade", "📄")
    if not oportunidades:
        _shared.estado_vazio("Nenhuma oportunidade cadastrada ainda. Use '➕ Nova oportunidade' acima.", "🤝")
        return

    opcoes = {f"#{op['id']} — {op['titulo']} ({op['estagio']})": op["id"] for op in oportunidades}
    escolha = st.selectbox("Selecione uma oportunidade", list(opcoes.keys()))
    op_id = opcoes[escolha]
    op = next(o for o in oportunidades if o["id"] == op_id)

    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Valor potencial", _shared.formatar_moeda(op["valor_potencial"]) if op["valor_potencial"] else "Não disponível")
    col_b.metric("Probabilidade", _shared.formatar_percentual(op["probabilidade"]) if op["probabilidade"] is not None else "Não disponível")
    col_c.metric("Estágio atual", op["estagio"])

    st.markdown(f"**Empresa vinculada:** {op.get('empresa_nome') or 'Nenhuma'}")
    st.markdown(f"**Programa/projeto do IORM relacionado:** {op.get('programa_relacionado') or 'Não disponível'}")
    st.markdown(f"**Mecanismo:** {op['mecanismo'] or 'Não disponível'}")
    st.markdown(f"**Responsável:** {op['responsavel'] or 'Não disponível'}")

    if st.button("🗑 Remover esta oportunidade do Pipeline…", key=f"remover_detalhe_{op_id}"):
        _confirmar_remocao(op)

    novo_estagio = st.selectbox("Mover para estágio", crm.ESTAGIOS, index=crm.ESTAGIOS.index(op["estagio"]), key=f"estagio_{op_id}")
    if novo_estagio != op["estagio"] and st.button("Mover estágio", key=f"mover_{op_id}"):
        crm.mover_estagio(conexao, op_id, novo_estagio)
        st.success(f"Oportunidade movida para '{novo_estagio}'.")
        _shared.limpar_cache()
        st.rerun()

    st.markdown("##### Próxima ação")
    with st.form(f"form_proxima_acao_{op_id}"):
        col_a, col_b = st.columns(2)
        data_acao = col_a.date_input("Data", value=None)
        prioridade = col_b.selectbox("Prioridade", crm.PRIORIDADES)
        descricao_acao = st.text_input("Descrição", value=op["proxima_acao_descricao"] or "")
        salvar_acao = st.form_submit_button("Salvar próxima ação")
    if salvar_acao:
        crm.atualizar_proxima_acao(
            conexao, op_id, data_acao.isoformat() if data_acao else None, descricao_acao or None, prioridade
        )
        st.success("Próxima ação atualizada.")
        _shared.limpar_cache()
        st.rerun()

    st.markdown("##### Timeline da oportunidade")
    interacoes = crm.listar_interacoes(conexao, op_id)
    if not interacoes:
        _shared.estado_vazio("Nenhuma interação registrada ainda.", "🕒")
    else:
        for i in interacoes:  # já vem ordenado por data DESC
            texto = i["tipo"]
            if i["descricao"]:
                texto += f" — {i['descricao']}"
            meta = []
            if i["responsavel"]:
                meta.append(f"por {i['responsavel']}")
            if i["resultado"]:
                meta.append(f"resultado: {i['resultado']}")
            meta_html = f"<div class='iorm-timeline-meta'>{' · '.join(meta)}</div>" if meta else ""
            st.markdown(
                f"<div class='iorm-timeline-item'><span class='iorm-timeline-data'>{_shared.formatar_data(i['data'])}</span>"
                f"<div><span class='iorm-timeline-texto'>{texto}</span>{meta_html}</div></div>",
                unsafe_allow_html=True,
            )

    with st.form(f"form_interacao_{op_id}", clear_on_submit=True):
        st.markdown("Registrar nova interação")
        col_a, col_b = st.columns(2)
        tipo = col_a.selectbox("Tipo", crm.TIPOS_INTERACAO)
        data_interacao = col_b.date_input("Data da interação", value=date.today())
        responsavel_interacao = st.text_input("Responsável")
        descricao_interacao = st.text_area("Descrição")
        resultado = st.text_input("Resultado")
        proxima_acao_texto = st.text_input("Próxima ação sugerida")
        enviar_interacao = st.form_submit_button("Registrar interação")
    if enviar_interacao:
        crm.registrar_interacao(
            conexao,
            {
                "oportunidade_id": op_id, "tipo": tipo, "data": data_interacao.isoformat(),
                "responsavel": responsavel_interacao or None, "descricao": descricao_interacao or None,
                "resultado": resultado or None, "proxima_acao": proxima_acao_texto or None,
            },
        )
        st.success("Interação registrada.")
        _shared.limpar_cache()
        st.rerun()


def render() -> None:
    conexao = _shared.conectar()
    dados = _shared.carregar_dados_salic(str(_shared.CAMINHO_DB))
    df_empresas = dados["df_empresas"]

    perfil_osc_row = osc.obter_osc_principal(conexao)
    programas_osc = osc.carregar_perfil_completo(conexao, perfil_osc_row["id"])["programas"] if perfil_osc_row else []

    _shared.cabecalho("Pipeline", "Acompanhe cada oportunidade de captação, do primeiro contato ao fechamento.")

    oportunidades = [_linha_para_dict(o) for o in crm.listar_oportunidades(conexao)]

    valor_total = crm.valor_potencial_total(oportunidades)
    follow_ups = crm.classificar_follow_ups(oportunidades, hoje=date.today())

    _shared.secao("Visão geral", "📊")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Valor potencial em aberto", _shared.formatar_moeda(valor_total))
    col2.metric("Follow-ups atrasados", len(follow_ups["atrasadas"]))
    col3.metric("Follow-ups de hoje", len(follow_ups["hoje"]))
    col4.metric("Sem follow-up definido", len(follow_ups["sem_followup"]))

    _formulario_nova_oportunidade(conexao, df_empresas, programas_osc)

    if oportunidades:
        _kanban(conexao, oportunidades)
        _secao_remover(oportunidades)
    else:
        _shared.estado_vazio(
            "Nenhuma oportunidade no Pipeline ainda. Crie uma acima ou use 'Adicionar ao CRM' na ficha "
            "de uma empresa (Radar de Empresas).", "🤝",
        )

    _secao_detalhe(conexao, oportunidades)
    _secao_removidas(conexao)

    conexao.close()
