"""Cérebro da OSC: a "memória institucional" que o Radar de Editais usa
para calcular aderência. Vem pré-cadastrado com o IORM usando só fatos
já verificados (site oficial, achados do módulo de enriquecimento e o
próprio cadastro CNPJ interno) — tudo marcado com sua origem."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from processamento import osc
from paginas import _shared

TIPOS_TERRITORIO = ["cidade", "estado", "regiao"]
TIPOS_LINK = ["site", "instagram", "linkedin", "facebook", "youtube", "transparencia", "outro"]
TIPOS_DOCUMENTO = ["estatuto", "certificado", "relatorio", "apresentacao", "projeto", "outro"]


def _secao_identidade(conexao, perfil) -> None:
    st.markdown("#### Identidade")
    st.markdown(_shared.badge_origem(perfil["origem"]), unsafe_allow_html=True)
    if perfil["fonte"]:
        st.caption(f"Fonte: {perfil['fonte']}")

    with st.form("form_identidade"):
        col_a, col_b = st.columns(2)
        nome = col_a.text_input("Nome", value=perfil["nome"] or "")
        nome_fantasia = col_b.text_input("Nome fantasia", value=perfil["nome_fantasia"] or "")
        cnpj = col_a.text_input("CNPJ", value=perfil["cnpj"] or "")
        ano_fundacao = col_b.number_input("Ano de fundação", min_value=1900, max_value=2100, value=perfil["ano_fundacao"] or 2000, step=1)
        natureza_juridica = st.text_input("Natureza jurídica", value=perfil["natureza_juridica"] or "", placeholder="Não preenchido")
        missao = st.text_area("Missão", value=perfil["missao"] or "")
        visao = st.text_area("Visão", value=perfil["visao"] or "", placeholder="Não preenchido")
        valores = st.text_area("Valores", value=perfil["valores"] or "", placeholder="Não preenchido")
        descricao = st.text_area("Descrição institucional", value=perfil["descricao"] or "")
        salvar = st.form_submit_button("💾 Salvar identidade")

    if salvar:
        osc.criar_ou_atualizar_osc(
            conexao, perfil["id"],
            {
                "nome": nome, "nome_fantasia": nome_fantasia or None, "cnpj": cnpj or None,
                "missao": missao or None, "visao": visao or None, "valores": valores or None,
                "descricao": descricao or None, "ano_fundacao": int(ano_fundacao) if ano_fundacao else None,
                "natureza_juridica": natureza_juridica or None,
            },
        )
        st.success("Identidade atualizada.")
        _shared.limpar_cache()
        st.rerun()


def _secao_territorios(conexao, osc_id: int) -> None:
    st.markdown("#### Atuação territorial")
    territorios = conexao.execute("SELECT * FROM osc_territorios WHERE osc_id = ? ORDER BY tipo, valor", (osc_id,)).fetchall()
    if not territorios:
        _shared.estado_vazio("Nenhum território cadastrado ainda.")
    else:
        for t in territorios:
            prioridade = "⭐ prioritário" if t["prioritario"] else ""
            st.markdown(f"- **{t['tipo']}**: {t['valor']} {prioridade} — {_shared.badge_origem(t['origem'])}", unsafe_allow_html=True)

    with st.form("form_territorio", clear_on_submit=True):
        col_a, col_b, col_c = st.columns([2, 3, 2])
        tipo = col_a.selectbox("Tipo", TIPOS_TERRITORIO)
        valor = col_b.text_input("Cidade/Estado/Região")
        prioritario = col_c.checkbox("Prioritário")
        enviar = st.form_submit_button("➕ Adicionar território")
    if enviar and valor:
        osc.adicionar_territorio(conexao, osc_id, tipo, valor.strip(), prioritario=prioritario, origem="MANUAL", fonte="Cadastro manual")
        st.success(f"Território '{valor}' adicionado.")
        _shared.limpar_cache()
        st.rerun()


def _secao_temas(conexao, osc_id: int) -> None:
    st.markdown("#### Temas de atuação")
    temas = conexao.execute("SELECT * FROM osc_areas_atuacao WHERE osc_id = ? ORDER BY tema", (osc_id,)).fetchall()
    if temas:
        st.markdown(" ".join(f"<span class='iorm-badge iorm-badge-verde'>{t['tema']}</span>" for t in temas), unsafe_allow_html=True)
    else:
        _shared.estado_vazio("Nenhum tema cadastrado ainda.")

    with st.form("form_tema", clear_on_submit=True):
        col_a, col_b = st.columns([4, 1])
        novo_tema = col_a.text_input("Novo tema (livre — não há lista fechada)")
        enviar = col_b.form_submit_button("➕ Adicionar")
    if enviar and novo_tema:
        osc.adicionar_area_atuacao(conexao, osc_id, novo_tema.strip(), origem="MANUAL", fonte="Cadastro manual")
        st.success(f"Tema '{novo_tema}' adicionado.")
        _shared.limpar_cache()
        st.rerun()


def _secao_palavras_chave(conexao, osc_id: int) -> None:
    st.markdown("#### Palavras-chave institucionais")
    st.caption("Usadas pelo Radar de Editais para comparar aderência com editais cadastrados.")
    palavras = conexao.execute("SELECT * FROM osc_palavras_chave WHERE osc_id = ? ORDER BY palavra", (osc_id,)).fetchall()
    if palavras:
        st.markdown(" ".join(f"<span class='iorm-badge iorm-badge-azul'>{p['palavra']}</span>" for p in palavras), unsafe_allow_html=True)
    else:
        _shared.estado_vazio("Nenhuma palavra-chave cadastrada ainda.")

    with st.form("form_palavra", clear_on_submit=True):
        col_a, col_b = st.columns([4, 1])
        nova = col_a.text_input("Nova palavra-chave")
        enviar = col_b.form_submit_button("➕ Adicionar")
    if enviar and nova:
        osc.adicionar_palavra_chave(conexao, osc_id, nova, origem="MANUAL", fonte="Cadastro manual")
        st.success(f"Palavra-chave '{nova}' adicionada.")
        _shared.limpar_cache()
        st.rerun()


def _secao_programas(conexao, osc_id: int) -> None:
    st.markdown("#### Programas e projetos")
    programas = conexao.execute("SELECT * FROM osc_programas WHERE osc_id = ? ORDER BY nome", (osc_id,)).fetchall()
    if not programas:
        _shared.estado_vazio("Nenhum programa cadastrado ainda.")
    else:
        for p in programas:
            with st.expander(f"{p['nome']} {'· ' + p['tema'] if p['tema'] else ''}"):
                st.markdown(_shared.badge_origem(p["origem"]), unsafe_allow_html=True)
                st.markdown(f"- **Público:** {p['publico'] or 'Não disponível'}")
                st.markdown(f"- **Faixa etária:** {p['faixa_etaria'] or 'Não disponível'}")
                st.markdown(f"- **Cidade/Estado:** {p['cidade'] or 'Não disponível'} / {p['estado'] or 'Não disponível'}")
                st.markdown(f"- **Objetivos:** {p['objetivos'] or 'Não disponível'}")
                st.markdown(f"- **ODS relacionados:** {p['ods'] or 'Não disponível'}")
                st.markdown(f"- **Orçamento:** {_shared.formatar_moeda(p['orcamento']) if p['orcamento'] else 'Não disponível'}")
                st.markdown(f"- **Status:** {p['status']}")
                if p["fonte"]:
                    st.caption(f"Fonte: {p['fonte']}")

    with st.form("form_programa", clear_on_submit=True):
        st.markdown("Adicionar novo programa")
        col_a, col_b = st.columns(2)
        nome = col_a.text_input("Nome do programa")
        tema = col_b.text_input("Tema")
        publico = col_a.text_input("Público")
        faixa_etaria = col_b.text_input("Faixa etária")
        cidade = col_a.text_input("Cidade")
        estado = col_b.text_input("Estado", value="SP")
        objetivos = st.text_area("Objetivos")
        ods = st.text_input("ODS relacionados (ex: ODS 4, ODS 10)")
        orcamento = st.number_input("Orçamento (R$, opcional)", min_value=0.0, step=1000.0)
        enviar = st.form_submit_button("➕ Adicionar programa")
    if enviar and nome:
        osc.adicionar_programa(
            conexao, osc_id,
            {"nome": nome, "tema": tema or None, "publico": publico or None, "faixa_etaria": faixa_etaria or None,
             "cidade": cidade or None, "estado": estado or None, "objetivos": objetivos or None, "ods": ods or None,
             "orcamento": orcamento or None, "origem": "MANUAL", "fonte": "Cadastro manual"},
        )
        st.success(f"Programa '{nome}' adicionado.")
        _shared.limpar_cache()
        st.rerun()


def _secao_mecanismos(conexao, osc_id: int) -> None:
    st.markdown("#### Leis e mecanismos utilizados")
    mecanismos = conexao.execute("SELECT * FROM osc_mecanismos WHERE osc_id = ? ORDER BY nome", (osc_id,)).fetchall()
    if not mecanismos:
        _shared.estado_vazio("Nenhum mecanismo cadastrado ainda.")
    else:
        for m in mecanismos:
            st.markdown(f"- **{m['nome']}** — {_shared.badge_origem(m['origem'])}", unsafe_allow_html=True)
            if m["observacao"]:
                st.caption(m["observacao"])

    with st.form("form_mecanismo", clear_on_submit=True):
        col_a, col_b = st.columns([2, 3])
        nome = col_a.text_input("Nome do mecanismo (ex: Lei de Incentivo ao Esporte)")
        observacao = col_b.text_input("Observação (opcional)")
        enviar = st.form_submit_button("➕ Adicionar mecanismo")
    if enviar and nome:
        osc.adicionar_mecanismo(conexao, osc_id, nome.strip(), observacao or None, origem="MANUAL", fonte="Cadastro manual")
        st.success(f"Mecanismo '{nome}' adicionado.")
        _shared.limpar_cache()
        st.rerun()


def _secao_links(conexao, osc_id: int) -> None:
    st.markdown("#### Links institucionais")
    links = conexao.execute("SELECT * FROM osc_links WHERE osc_id = ? ORDER BY tipo", (osc_id,)).fetchall()
    if not links:
        _shared.estado_vazio("Nenhum link cadastrado ainda.")
    else:
        for l in links:
            st.markdown(f"- **{l['tipo']}**: [{l['url']}]({l['url']}) — {_shared.badge_origem(l['origem'])}", unsafe_allow_html=True)

    with st.form("form_link", clear_on_submit=True):
        col_a, col_b = st.columns([1, 3])
        tipo = col_a.selectbox("Tipo", TIPOS_LINK)
        url = col_b.text_input("URL")
        enviar = st.form_submit_button("➕ Adicionar link")
    if enviar and url:
        osc.adicionar_link(conexao, osc_id, tipo, url.strip(), origem="MANUAL", fonte="Cadastro manual")
        st.success("Link adicionado.")
        _shared.limpar_cache()
        st.rerun()


def _secao_documentos(conexao, osc_id: int) -> None:
    st.markdown("#### Documentos")
    st.caption(
        "Estrutura pronta para o futuro — ainda sem upload de arquivo nem leitura automática de "
        "conteúdo. Por enquanto, registre nome/descrição e uma referência (link ou caminho)."
    )
    documentos = conexao.execute("SELECT * FROM osc_documentos WHERE osc_id = ? ORDER BY criado_em DESC", (osc_id,)).fetchall()
    if not documentos:
        _shared.estado_vazio("Nenhum documento registrado ainda.")
    else:
        df_docs = pd.DataFrame([dict(d) for d in documentos]).fillna("—")
        st.dataframe(
            df_docs[["tipo", "nome", "descricao", "referencia", "origem"]].rename(
                columns={"tipo": "Tipo", "nome": "Nome", "descricao": "Descrição", "referencia": "Referência", "origem": "Origem"}
            ),
            use_container_width=True, hide_index=True,
        )

    with st.form("form_documento", clear_on_submit=True):
        col_a, col_b = st.columns(2)
        tipo = col_a.selectbox("Tipo", TIPOS_DOCUMENTO)
        nome = col_b.text_input("Nome do documento")
        descricao = st.text_input("Descrição (opcional)")
        referencia = st.text_input("Referência (link ou caminho, opcional)")
        enviar = st.form_submit_button("➕ Registrar documento")
    if enviar and nome:
        osc.adicionar_documento(conexao, osc_id, tipo, nome, descricao or None, referencia or None, origem="MANUAL")
        st.success(f"Documento '{nome}' registrado.")
        _shared.limpar_cache()
        st.rerun()


def render() -> None:
    conexao = _shared.conectar()
    perfil = osc.obter_osc_principal(conexao)

    _shared.cabecalho("Cérebro da OSC", "A memória institucional do IORM — usada pelo Radar de Editais para calcular aderência.")

    abas = st.tabs([
        "Identidade", "Território", "Programas", "Temas", "Mecanismos", "Links", "Documentos", "Palavras-chave",
    ])
    with abas[0]:
        _secao_identidade(conexao, perfil)
    with abas[1]:
        _secao_territorios(conexao, perfil["id"])
    with abas[2]:
        _secao_programas(conexao, perfil["id"])
    with abas[3]:
        _secao_temas(conexao, perfil["id"])
    with abas[4]:
        _secao_mecanismos(conexao, perfil["id"])
    with abas[5]:
        _secao_links(conexao, perfil["id"])
    with abas[6]:
        _secao_documentos(conexao, perfil["id"])
    with abas[7]:
        _secao_palavras_chave(conexao, perfil["id"])

    conexao.close()
