"""Cérebro da OSC: a "memória institucional" que o Radar de Editais usa
para calcular aderência. Vem pré-cadastrado com o IORM usando só fatos
já verificados (site oficial, achados do módulo de enriquecimento e o
próprio cadastro CNPJ interno) — tudo marcado com sua origem."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from processamento import documentos, geografia, osc, regiao
from paginas import _shared

TIPOS_TERRITORIO = ["cidade", "regiao_proxima", "interesse_estrategico", "estado"]
_ROTULOS_TIPO_TERRITORIO = {
    "cidade": "Cidade de atuação",
    "regiao_proxima": "Região próxima",
    "interesse_estrategico": "Interesse estratégico",
    "estado": "Estado",
}
TIPOS_LINK = ["site", "instagram", "linkedin", "facebook", "youtube", "transparencia", "outro"]


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
    st.markdown("#### Região IORM — priorização geográfica")
    st.caption(
        "Esta é a configuração que o Radar de Empresas e o Radar de Editais usam para priorizar por "
        "geografia. Quatro camadas, da mais forte pra mais fraca: Cidade de atuação → Região próxima → "
        "Interesse estratégico → (qualquer outra cidade, fora da região). A pontuação de cada camada é "
        "editável em `processamento/regiao.py`."
    )
    territorios = conexao.execute("SELECT * FROM osc_territorios WHERE osc_id = ? ORDER BY tipo, valor", (osc_id,)).fetchall()
    territorios_dict = [dict(t) for t in territorios]
    # Mesma regra de osc.carregar_perfil_completo: a região dos polos (IBGE + ajustes) entra como
    # 'regiao_proxima' sem duplicar cidade já cadastrada à mão — assim a tela mostra o que o score usa.
    ja_cadastradas = {t["valor"].strip().lower() for t in territorios_dict}
    derivados: list[dict] = []
    for t in geografia.territorios_derivados(conexao):  # um município pode estar na região de dois polos
        chave = t["valor"].strip().lower()
        if chave not in ja_cadastradas:
            ja_cadastradas.add(chave)
            derivados.append(t)
    territorios_dict += derivados

    if not territorios_dict:
        _shared.estado_vazio("Nenhum território cadastrado ainda.")
    else:
        grupos = regiao.cidades_por_camada(territorios_dict)
        for camada in ["CIDADE_ATUACAO", "REGIAO_PROXIMA", "INTERESSE_ESTRATEGICO"]:
            cidades_camada = grupos.get(camada, [])
            st.markdown(
                f"{_shared.badge_regiao_iorm(camada)} &nbsp; "
                f"<span style='color:var(--iorm-cinza);font-size:0.82rem;'>({regiao.pontos(camada)} pontos no IORM Score)</span>",
                unsafe_allow_html=True,
            )
            if cidades_camada:
                st.markdown(", ".join(cidades_camada))
            else:
                st.caption("Nenhuma cidade cadastrada nesta camada ainda.")
        if derivados:
            st.caption(
                f"A Região próxima inclui {len(derivados)} município(s) vindos da Região dos polos "
                "(IBGE + ajustes) — veja e edite na seção “Região dos polos” abaixo."
            )
        estados = [t for t in territorios_dict if t["tipo"] == "estado"]
        if estados:
            st.markdown(f"**Estado(s) de referência:** {', '.join(t['valor'] for t in estados)}")

        with st.expander("Ver cadastro completo (com origem/fonte de cada item)"):
            for t in territorios:
                prioridade = "⭐ prioritário" if t["prioritario"] else ""
                rotulo_tipo = _ROTULOS_TIPO_TERRITORIO.get(t["tipo"], t["tipo"])
                st.markdown(f"- **{rotulo_tipo}**: {t['valor']} {prioridade} — {_shared.badge_origem(t['origem'])}", unsafe_allow_html=True)

    with st.form("form_territorio", clear_on_submit=True):
        col_a, col_b, col_c = st.columns([2, 3, 2])
        tipo = col_a.selectbox("Camada", TIPOS_TERRITORIO, format_func=lambda t: _ROTULOS_TIPO_TERRITORIO[t])
        valor = col_b.text_input("Cidade/Estado", help="Use o nome exatamente como aparece no Radar de Empresas (ex: Barretos).")
        prioritario = col_c.checkbox("Prioritário")
        enviar = st.form_submit_button("➕ Adicionar")
    if enviar and valor:
        osc.adicionar_territorio(conexao, osc_id, tipo, valor.strip(), prioritario=prioritario, origem="MANUAL", fonte="Cadastro manual")
        st.success(f"'{valor}' adicionado como {_ROTULOS_TIPO_TERRITORIO[tipo].lower()}.")
        _shared.limpar_cache()
        st.rerun()


def _secao_regiao_polos(conexao, polos: list[str]) -> None:
    _shared.secao(
        "Região dos polos", "🗺️",
        "As cidades da região de cada polo vêm do IBGE (Região Geográfica Imediata) e podem ser ajustadas à mão.",
    )
    with st.expander("Metodologia — como a “região” de um polo é definida"):
        st.markdown(
            "- **Fonte:** IBGE, API de Localidades (`servicodados.ibge.gov.br`), divisão em **Regiões Geográficas "
            "Imediatas** (2017): municípios agrupados em torno de um centro urbano, pelos fluxos do dia a dia "
            "(trabalho, comércio, serviços).\n"
            "- **Regra:** a região de um polo = todos os municípios da mesma Região Geográfica Imediata dele. "
            "Nenhuma cidade é escolhida manualmente pelo sistema.\n"
            "- **Ajuste manual:** você pode desativar um município do IBGE ou adicionar outro a um polo — o "
            "registro guarda a origem (IBGE ou Manual) e a sincronização nunca desfaz uma decisão sua.\n"
            "- **Efeito:** essas cidades entram como *Região próxima* no IORM Score, nos filtros e no Radar por Região."
        )
    if not polos:
        st.info("Cadastre primeiro as cidades de atuação (polos) acima.")
        return

    uf = st.selectbox("UF dos polos", list(geografia.CODIGO_UF), key="regiao_uf")
    if st.button("🔄 Sincronizar região com o IBGE", key="sync_ibge"):
        with st.spinner("Consultando o IBGE..."):
            resumo = geografia.sincronizar_ibge(conexao, polos, uf)
        if resumo["erros"]:
            st.error("Alguns polos não puderam ser sincronizados: " + "; ".join(resumo["erros"]))
        st.success(f"{resumo['novos']} município(s) novo(s), {resumo['ja_existentes']} já existente(s).")
        _shared.limpar_cache()

    registros = geografia.listar(conexao, apenas_ativos=False)
    if not registros:
        _shared.estado_vazio("Região ainda não sincronizada. Clique em “Sincronizar região com o IBGE”.", "🗺️")
    else:
        df = pd.DataFrame(registros)[["id", "polo", "municipio", "uf", "regiao_imediata", "origem", "ativo", "fonte"]]
        df["ativo"] = df["ativo"].astype(bool)
        editado = st.data_editor(
            df.rename(columns={"polo": "Polo", "municipio": "Município", "uf": "UF", "regiao_imediata": "Região imediata",
                               "origem": "Origem", "ativo": "Ativo", "fonte": "Fonte"}),
            hide_index=True, use_container_width=True, key="editor_regiao",
            disabled=["id", "Polo", "Município", "UF", "Região imediata", "Origem", "Fonte"],
            column_config={"id": None, "Município": st.column_config.TextColumn(width=190),
                           "Região imediata": st.column_config.TextColumn(width=240),
                           "Fonte": st.column_config.TextColumn(width=420),
                           "Ativo": st.column_config.CheckboxColumn(width=80)},
        )
        mudou = False
        for antes, depois in zip(df.itertuples(), editado.itertuples()):
            if bool(antes.ativo) != bool(depois.Ativo):
                geografia.definir_ativo(conexao, int(antes.id), bool(depois.Ativo))
                mudou = True
        if mudou:
            _shared.limpar_cache()
            st.rerun()

    with st.form("form_regiao_manual", clear_on_submit=True):
        c1, c2, c3 = st.columns([1.2, 1.5, 0.6])
        polo = c1.selectbox("Polo", polos)
        municipio = c2.text_input("Município a adicionar")
        uf_manual = c3.text_input("UF", value="SP", max_chars=2)
        motivo = st.text_input("Motivo (obrigatório)", placeholder="Ex: atendemos alunos dessa cidade desde 2023")
        if st.form_submit_button("➕ Adicionar município à região") and municipio and motivo.strip():
            geografia.adicionar_manual(conexao, polo, municipio, uf_manual, motivo.strip())
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


def _caminho_relativo(caminho: str) -> str:
    """Mostra o caminho a partir da pasta do projeto (não expõe a árvore de pastas do usuário)."""
    try:
        return str(Path(caminho).resolve().relative_to(_shared.RAIZ_PROJETO.resolve()))
    except (ValueError, OSError):
        return Path(caminho).name


def _tamanho_legivel(bytes_: int | None) -> str:
    if not bytes_:
        return "—"
    if bytes_ < 1024:
        return f"{bytes_} bytes"
    if bytes_ < 1024 * 1024:
        return f"{bytes_ / 1024:,.1f} KB".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{bytes_ / (1024 * 1024):,.1f} MB".replace(",", "X").replace(".", ",").replace("X", ".")


def _secao_documentos(conexao, osc_id: int) -> None:
    st.markdown("#### Documentos da OSC")
    st.caption(
        "Repositório documental: o arquivo original é guardado sem alteração e o texto é extraído para "
        "busca. Nada é interpretado por IA — tudo que aparece aqui é trecho literal do documento."
    )

    with st.form("form_upload_documento", clear_on_submit=True):
        arquivos = st.file_uploader(
            "Enviar documentos (PDF, DOCX, TXT, XLSX, XLS — até 25 MB cada)",
            type=["pdf", "docx", "txt", "xlsx", "xls"], accept_multiple_files=True,
        )
        col_a, col_b = st.columns([1, 2])
        categoria = col_a.selectbox("Categoria", documentos.CATEGORIAS)
        descricao = col_b.text_input("Descrição (opcional)")
        enviar = st.form_submit_button("⬆ Enviar e processar")
    if enviar:
        if not arquivos:
            st.warning("Selecione pelo menos um arquivo.")
        for arquivo in arquivos or []:
            try:
                resultado = documentos.adicionar(
                    conexao, osc_id, arquivo.name, arquivo.getvalue(), _shared.PASTA_DOCUMENTOS_OSC,
                    categoria, descricao or None,
                )
            except ValueError as erro:
                st.error(f"{arquivo.name}: {erro}")
                continue
            if resultado["duplicado"]:
                st.info(f"{arquivo.name}: este arquivo já estava cadastrado (mesmo conteúdo) — nada foi duplicado.")
            else:
                st.success(f"{arquivo.name}: {documentos.ROTULOS_STATUS.get(resultado['status'], resultado['status'])}.")
        _shared.limpar_cache()

    lista = documentos.listar(conexao, osc_id)
    if not lista:
        _shared.estado_vazio("Nenhum documento enviado ainda.", "📄")
        return

    _shared.secao(f"Documentos cadastrados ({len(lista)})", "📄")
    for doc in lista:
        rotulo_status = documentos.ROTULOS_STATUS.get(doc["status_processamento"], "Registro sem arquivo (cadastro antigo)")
        titulo = doc["nome_arquivo"] or doc["nome"]
        with st.expander(f"{titulo}  ·  {doc['categoria'] or doc['tipo'] or 'Sem categoria'}"):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Tipo", (doc["extensao"] or "—").upper().lstrip("."))
            c2.metric("Tamanho", _tamanho_legivel(doc["tamanho_bytes"]))
            c3.metric("Enviado em", _shared.formatar_data(doc["enviado_em"] or doc["criado_em"]))
            c4.metric("Texto extraído", f"{doc['caracteres']:,} caracteres".replace(",", ".") if doc["caracteres"] else "Nenhum")
            st.markdown(f"**Status de processamento:** {rotulo_status}")
            if doc["detalhe_processamento"]:
                st.caption(f"Detalhe técnico: {doc['detalhe_processamento']}")
            if doc["descricao"]:
                st.markdown(f"**Descrição:** {doc['descricao']}")
            if doc["referencia"] and doc["referencia"] != doc["caminho_arquivo"]:
                st.markdown(f"**Referência:** {doc['referencia']}")
            if doc["caminho_arquivo"]:
                st.caption(f"Arquivo original preservado em: {_caminho_relativo(doc['caminho_arquivo'])}")
            if doc["caracteres"]:
                with st.expander("Ver texto extraído"):
                    st.text_area("Texto", value=documentos.obter_texto(conexao, doc["id"]) or "", height=260,
                                 key=f"texto_doc_{doc['id']}", label_visibility="collapsed")
            if st.button("🗑 Excluir documento", key=f"excluir_doc_{doc['id']}"):
                documentos.excluir(conexao, doc["id"])
                _shared.limpar_cache()
                st.rerun()

    _shared.secao("Buscar no conteúdo dos documentos", "🔎")
    termo = st.text_input("Palavra ou expressão", key="busca_documentos", placeholder="Ex: territorial, crianças, Guaíra")
    if termo:
        achados = documentos.buscar(conexao, osc_id, termo)
        if not achados:
            st.info(f"Nenhum documento contém “{termo}”.")
        for achado in achados:
            st.markdown(f"**Fonte: documento {achado['documento']}** ({achado['categoria'] or 'sem categoria'}) — {achado['ocorrencias']} ocorrência(s)")
            for trecho in achado["trechos"]:
                st.markdown(f"> …{trecho}…")


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
        _secao_regiao_polos(conexao, osc.carregar_perfil_completo(conexao, perfil["id"])["cidades"])
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
