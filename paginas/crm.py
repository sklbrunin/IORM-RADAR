"""CRM de Captação: pipeline (estilo Kanban), interações e follow-ups.

Toda oportunidade pode (opcionalmente) estar ligada a uma empresa do
Radar — sem precisar recadastrar nada."""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from processamento import crm, osc
from paginas import _shared


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


def _kanban(conexao, oportunidades: list[dict]) -> None:
    _shared.secao("Pipeline de Captação", "🔀", "Arraste mentalmente: mude o estágio na ficha da oportunidade abaixo.")
    colunas = st.columns(len(crm.ESTAGIOS))
    for coluna, estagio in zip(colunas, crm.ESTAGIOS):
        with coluna:
            st.markdown(f"<div class='iorm-kanban-titulo'>{estagio}</div>", unsafe_allow_html=True)
            itens = [op for op in oportunidades if op["estagio"] == estagio]
            st.caption(f"{len(itens)} oportunidade(s)")
            for op in itens:
                empresa_nome = op.get("empresa_nome") or "Sem empresa vinculada"
                valor = _shared.formatar_moeda(op["valor_potencial"]) if op["valor_potencial"] else "Valor não informado"
                st.markdown(
                    f"<div class='iorm-kanban-cartao'><b>{op['titulo']}</b><br>{empresa_nome}<br>"
                    f"<span class='iorm-kanban-cartao-valor'>{valor}</span></div>",
                    unsafe_allow_html=True,
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
    else:
        _shared.estado_vazio(
            "Nenhuma oportunidade no Pipeline ainda. Crie uma acima ou use 'Adicionar ao CRM' na ficha "
            "de uma empresa (Radar de Empresas).", "🤝",
        )

    _secao_detalhe(conexao, oportunidades)

    conexao.close()
