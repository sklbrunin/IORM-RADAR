"""Projetos do IORM × edital (v9).

Para cada edital, diz QUAIS programas/projetos do IORM (Cérebro da OSC: `osc_programas`, áreas, palavras-chave,
territórios) combinam tematicamente com ele, com nível, evidências literais e justificativa. 100% determinístico
(sem modelo generativo): mesmas entradas, mesma saída, e cada conclusão é rastreável até um trecho do edital ou
um campo do Cérebro da OSC.

Duas perguntas SEPARADAS — nunca misturadas:
  * ADEQUAÇÃO TEMÁTICA (por projeto): o assunto do edital combina com o projeto? -> ALTA / MÉDIA / BAIXA / NÃO IDENTIFICADA.
  * ELEGIBILIDADE DA OSC (por edital): quem pode se inscrever? O sistema só extrai o que o texto diz e SEMPRE conclui
    "precisa ser conferida no edital" — nunca "pode participar".

Dados esparsos são tratados com honestidade: programa cadastrado só com o nome recebe "dados insuficientes" em vez de
uma conclusão inventada. Nada aqui é específico de um edital ou de um projeto: o resultado nasce dos dados do
Cérebro da OSC e do texto do edital.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone

VERSAO_ANALISE = "1"

NIVEL_ALTA, NIVEL_MEDIA, NIVEL_BAIXA, NIVEL_NAO_IDENTIFICADA = "ALTA", "MEDIA", "BAIXA", "NAO_IDENTIFICADA"
ROTULOS_NIVEL = {NIVEL_ALTA: "Alta", NIVEL_MEDIA: "Média", NIVEL_BAIXA: "Baixa", NIVEL_NAO_IDENTIFICADA: "Não identificada"}
NIVEIS_RELACIONADOS = (NIVEL_ALTA, NIVEL_MEDIA)
_ORDEM = {NIVEL_ALTA: 3, NIVEL_MEDIA: 2, NIVEL_BAIXA: 1, NIVEL_NAO_IDENTIFICADA: 0}

ELEG_RESTRICAO = "RESTRICAO_IDENTIFICADA"
ELEG_MENCIONA_PJ = "MENCIONA_PESSOA_JURIDICA"
ELEG_NAO_IDENTIFICADA = "NAO_IDENTIFICADA"
AVISO_ELEGIBILIDADE = "Elegibilidade precisa ser conferida no edital."

# Vocabulário temático (radicais, sem acento). É deliberadamente pequeno e legível: cada linha é uma "linguagem/tema"
# e a lista de radicais que a evidenciam no texto. Ampliar aqui é mudar a regra, e a regra aparece em "Ver como foi calculado".
TEMAS_ESPECIFICOS: dict[str, list[str]] = {
    "dança": [r"danc\w*", r"coreograf\w*", r"\bbale\b", r"ballet"],
    "música": [r"music\w*", r"\bcoral\b", r"orquestr\w*", r"instrumento\w*", r"\bbanda\b"],
    "teatro": [r"teatr\w*", r"artes cenicas", r"\bcenic\w*", r"dramaturg\w*"],
    "literatura": [r"literatur\w*", r"\bleitura\b", r"\blivros?\b", r"bibliotec\w*", r"poesia", r"escritor\w*"],
    "cinema": [r"cinema\w*", r"audiovisua\w*", r"\bfilmes?\b", r"curta[- ]metragem", r"cineclube\w*"],
    "geração de renda": [r"geracao de renda", r"\bempreendedorismo\b", r"economia solidaria", r"artesanat\w*", r"\brenda\b"],
    "qualificação profissional": [r"qualificacao", r"capacitacao profission\w*", r"profissionaliz\w*", r"formacao profission\w*",
                                  r"\bsenac\b", r"empregabilidade"],
    "educação": [r"educacao", r"educacional", r"\bescolas?\b", r"\bensino\b", r"aprendizagem", r"alfabetiza\w*"],
}
FAMILIA_ARTES = {"dança", "música", "teatro", "literatura", "cinema"}
TERMOS_CULTURA_GERAL = [r"\bcultur\w*", r"\bartes?\b", r"artistic\w*", r"\bartistas?\b"]
_PALAVRAS_VAZIAS = {"para", "com", "das", "dos", "uma", "que", "por", "como", "mais", "ate", "nas", "nos", "seus", "suas"}


def _remover_acentos(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def _norm(texto) -> str:
    return _remover_acentos(str(texto or "").lower())


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _achados(texto_normalizado: str, padroes: list[str]) -> list[str]:
    """Trechos literais do texto que casam com os radicais."""
    encontrados: list[str] = []
    for padrao in padroes:
        for m in re.finditer(padrao, texto_normalizado):
            trecho = m.group(0).strip()
            if trecho and trecho not in encontrados:
                encontrados.append(trecho)
    return encontrados


def temas_do_texto(texto) -> dict[str, list[str]]:
    """{tema: [trechos que o evidenciam]} — só os temas específicos que aparecem no texto."""
    normal = _norm(texto)
    achados = {tema: _achados(normal, padroes) for tema, padroes in TEMAS_ESPECIFICOS.items()}
    return {tema: trechos for tema, trechos in achados.items() if trechos}


def contagem_de_temas(texto) -> dict[str, int]:
    """{tema: nº de ocorrências} — quantas vezes cada tema específico aparece."""
    normal = _norm(texto)
    return {tema: sum(len(re.findall(p, normal)) for p in padroes) for tema, padroes in TEMAS_ESPECIFICOS.items()
            if any(re.search(p, normal) for p in padroes)}


# Um edital que declara muitas linguagens (ex.: 15 áreas do Prosas) aceita quase qualquer projeto cultural: casar com UMA
# delas é evidência fraca. Acima deste número de temas declarados, um único tema em comum só chega a "Média".
LIMITE_EDITAL_MULTIAREA = 3
# Um tema citado só no corpo do texto (não no título/áreas) precisa aparecer pelo menos tantas vezes para pesar como declarado.
OCORRENCIAS_TEMA_RECORRENTE = 3


def cultura_geral(texto) -> list[str]:
    return _achados(_norm(texto), TERMOS_CULTURA_GERAL)


# ------------------------------------------------------------------ território e público
def avaliar_territorio(territorio_edital, perfil: dict) -> dict:
    """{estado: NACIONAL|COMPATIVEL|INCOMPATIVEL|DESCONHECIDO, detalhe}. Compara com TODOS os territórios do IORM
    (cidades, estados e região dos polos), não só com a cidade do programa."""
    texto = _norm(territorio_edital)
    if not texto.strip():
        return {"estado": "DESCONHECIDO", "detalhe": "O edital não informa o território elegível."}
    if re.search(r"nacional|todo o brasil|todo o pais|todo territorio", texto):
        return {"estado": "NACIONAL", "detalhe": "Abrangência nacional — inclui o território do IORM."}
    valores = [str(t.get("valor") or "") for t in perfil.get("territorios", [])]
    coincidencias = []
    for valor in valores:
        v = _norm(valor).strip()
        if v and re.search(rf"(?<!\w){re.escape(v)}(?!\w)", texto):
            coincidencias.append(valor)
    if coincidencias:
        return {"estado": "COMPATIVEL", "detalhe": f"O território do edital inclui: {', '.join(sorted(set(coincidencias)))} (território do IORM)."}
    return {"estado": "INCOMPATIVEL", "detalhe": f"O território do edital (“{territorio_edital}”) não inclui nenhum território cadastrado do IORM."}


def _palavras(texto) -> set[str]:
    return {p for p in re.findall(r"[a-z]{4,}", _norm(texto)) if p not in _PALAVRAS_VAZIAS}


def avaliar_publico(publico_edital, programa: dict) -> dict:
    publico_programa = " ".join(filter(None, [programa.get("publico"), programa.get("faixa_etaria")]))
    if not str(publico_edital or "").strip():
        return {"estado": "DESCONHECIDO", "detalhe": "O edital não descreve o público."}
    if not publico_programa.strip():
        return {"estado": "DESCONHECIDO", "detalhe": "O projeto não tem público cadastrado no Cérebro da OSC."}
    comuns = sorted(_palavras(publico_edital) & _palavras(publico_programa))
    if comuns:
        return {"estado": "COINCIDE", "detalhe": f"Termos em comum entre o público do edital e o do projeto: {', '.join(comuns)}."}
    return {"estado": "DIFERENTE", "detalhe": "O público descrito no edital não tem termos em comum com o do projeto."}


# ------------------------------------------------------------------ elegibilidade (por edital, separada do tema)
def avaliar_elegibilidade(edital: dict) -> dict:
    """Só extrai o que o texto diz. Nunca conclui "pode participar"."""
    requisitos = str(edital.get("requisitos") or "").strip()
    texto = _norm(requisitos)
    if not texto:
        return {"status": ELEG_NAO_IDENTIFICADA, "resumo": "Os requisitos de quem pode se inscrever não foram identificados na fonte.",
                "trecho": None, "alertas": [], "aviso": AVISO_ELEGIBILIDADE}
    fisica = bool(re.search(r"pessoas? fisicas?", texto))
    juridica = bool(re.search(r"pessoas? juridicas?|sem fins lucrativos|\bosc\b|organizacao da sociedade civil|associacao|instituic", texto))
    alertas = []
    if re.search(r"residente|residencia|domicili", texto):
        alertas.append("Exige residência/domicílio — conferir o local e o tempo exigidos.")
    if re.search(r"cnae|atividade economica", texto):
        alertas.append("Menciona CNAE/atividade econômica — conferir se o cadastro do IORM se enquadra.")
    if re.search(r"\bmei\b|microempreendedor", texto):
        alertas.append("Menciona MEI/empresário individual — verificar se o IORM (associação) é contemplado.")
    if fisica and not juridica:
        status = ELEG_RESTRICAO
        resumo = "O texto cita apenas pessoas físicas como proponentes; o IORM é pessoa jurídica (associação privada), então a participação da OSC é duvidosa."
    elif juridica:
        status = ELEG_MENCIONA_PJ
        resumo = "O texto menciona pessoas jurídicas/entidades como proponentes; a conferência das demais exigências continua necessária."
    else:
        status = ELEG_NAO_IDENTIFICADA
        resumo = "Há texto de requisitos, mas sem indicar claramente o tipo de proponente aceito."
    return {"status": status, "resumo": resumo, "trecho": requisitos[:600], "alertas": alertas, "aviso": AVISO_ELEGIBILIDADE}


# ------------------------------------------------------------------ o cálculo por projeto
def _texto_edital(edital: dict) -> str:
    return " ".join(str(edital.get(c) or "") for c in ("titulo", "descricao", "area_tematica", "texto_resumo"))


def _texto_programa(programa: dict, incluir_nome: bool = True) -> str:
    campos = ("nome", "tema", "objetivos", "descricao") if incluir_nome else ("tema", "objetivos", "descricao")
    return " ".join(str(programa.get(c) or "") for c in campos)


def _rebaixar(nivel: str) -> str:
    return {NIVEL_ALTA: NIVEL_MEDIA, NIVEL_MEDIA: NIVEL_BAIXA}.get(nivel, nivel)


def avaliar_programa(edital: dict, programa: dict, perfil: dict, territorio: dict | None = None) -> dict:
    """Nível temático do projeto para o edital + evidências + justificativa + o detalhamento do cálculo."""
    territorio = territorio or avaliar_territorio(edital.get("territorio"), perfil)
    cultura_edital = cultura_geral(_texto_edital(edital))
    temas_prog = temas_do_texto(_texto_programa(programa))
    cultura_prog_nome = cultura_geral(programa.get("nome"))
    publico = avaliar_publico(edital.get("publico"), programa)

    # Temas do edital em dois pesos: os DECLARADOS (título e áreas temáticas) e os RECORRENTES no corpo do texto pesam;
    # uma citação isolada no corpo ("...artistas, músicos, dançarinos...") só vira evidência fraca.
    declarados = temas_do_texto(" ".join(str(edital.get(c) or "") for c in ("titulo", "area_tematica")))
    corpo = contagem_de_temas(" ".join(str(edital.get(c) or "") for c in ("descricao", "texto_resumo")))
    recorrentes = {t: n for t, n in corpo.items() if n >= OCORRENCIAS_TEMA_RECORRENTE and t not in declarados}
    fortes = set(declarados) | set(recorrentes)
    citados = set(corpo) - fortes
    multiarea = len(fortes) > LIMITE_EDITAL_MULTIAREA
    temas_edital = fortes | citados

    criterios: list[dict] = []
    evidencias: list[str] = []
    comuns_fortes = sorted(fortes & set(temas_prog))
    comuns_citados = sorted(citados & set(temas_prog))
    comuns = comuns_fortes + comuns_citados
    edital_cultural = bool(cultura_edital) or bool(temas_edital & FAMILIA_ARTES)
    programa_artes = bool(set(temas_prog) & FAMILIA_ARTES) or bool(cultura_prog_nome)
    generalista = bool(cultura_prog_nome)  # o NOME do projeto é de arte/cultura em geral (ex.: "Artes e Cultura")

    edital_vazio = not _texto_edital(edital).strip()
    programa_vazio = not temas_prog and not cultura_geral(_texto_programa(programa))
    dados_insuficientes = edital_vazio or programa_vazio

    # 1) área/tema
    if edital_vazio:
        criterios.append({"criterio": "Área / tema", "resultado": "Sem dados", "detalhe": "O edital não tem título/descrição suficientes."})
    elif programa_vazio:
        criterios.append({"criterio": "Área / tema", "resultado": "Sem dados",
                          "detalhe": f"O projeto “{programa.get('nome')}” tem poucos dados no Cérebro da OSC (tema/descrição/objetivos vazios). "
                                     "Complete o cadastro para melhorar a análise."})
    elif comuns:
        for tema in comuns_fortes:
            onde = (f"declarado no título/áreas do edital (“{declarados[tema][0]}”)" if tema in declarados
                    else f"recorrente no texto do edital ({recorrentes[tema]} ocorrências)")
            evidencias.append(f"Tema “{tema}”: {onde} e presente no projeto (“{temas_prog[tema][0]}”).")
        for tema in comuns_citados:
            evidencias.append(f"Tema “{tema}” citado só de passagem no corpo do edital ({corpo[tema]}×), sem estar entre as áreas declaradas.")
        if multiarea and comuns_fortes:
            evidencias.append(f"O edital declara {len(fortes)} linguagens/áreas (edital multiárea): casar com uma delas é evidência mais fraca.")
        criterios.append({"criterio": "Área / tema", "resultado": "Coincide" if comuns_fortes else "Só citado no texto",
                          "detalhe": "; ".join(evidencias)})
    elif generalista and edital_cultural:
        trecho = (cultura_edital or ["cultura"])[0]
        evidencias.append(f"Projeto generalista de arte e cultura (“{cultura_prog_nome[0]}” no nome) e o edital é da área cultural (“{trecho}”).")
        criterios.append({"criterio": "Área / tema", "resultado": "Parcial", "detalhe": evidencias[-1]})
    elif programa_artes and edital_cultural:
        evidencias.append("Mesma grande área (arte/cultura), mas a linguagem do projeto "
                          f"({', '.join(sorted(set(temas_prog) & FAMILIA_ARTES)) or 'arte'}) não é citada no edital.")
        criterios.append({"criterio": "Área / tema", "resultado": "Só a grande área", "detalhe": evidencias[-1]})
    else:
        criterios.append({"criterio": "Área / tema", "resultado": "Não coincide",
                          "detalhe": "Nenhum tema do projeto aparece no texto do edital."})

    # 2) território
    rotulo_terr = {"NACIONAL": "Compatível", "COMPATIVEL": "Compatível", "INCOMPATIVEL": "Incompatível", "DESCONHECIDO": "Não identificado"}
    detalhe_terr = territorio["detalhe"]
    if territorio["estado"] in ("NACIONAL", "COMPATIVEL") and programa.get("cidade"):
        cidade = str(programa["cidade"])
        if _norm(cidade) not in _norm(edital.get("territorio")) and territorio["estado"] == "COMPATIVEL":
            detalhe_terr += f" (O projeto está cadastrado em {cidade}; o território do edital também é território do IORM.)"
    criterios.append({"criterio": "Território", "resultado": rotulo_terr[territorio["estado"]], "detalhe": detalhe_terr})

    # 3) público
    rotulo_pub = {"COINCIDE": "Coincide", "DIFERENTE": "Diferente", "DESCONHECIDO": "Não identificado"}
    criterios.append({"criterio": "Público", "resultado": rotulo_pub[publico["estado"]], "detalhe": publico["detalhe"]})

    # nível temático
    secundarias = []
    if territorio["estado"] in ("NACIONAL", "COMPATIVEL"):
        secundarias.append("território compatível")
    if publico["estado"] == "COINCIDE":
        secundarias.append("público coincide")
    if comuns_fortes and edital_cultural and programa_artes:
        secundarias.append("mesma grande área cultural")

    if dados_insuficientes:
        nivel = NIVEL_NAO_IDENTIFICADA
    elif comuns_fortes:
        # edital multiárea: território e "grande área" não distinguem projetos; só 2+ temas em comum ou público coincidente
        independente = publico["estado"] == "COINCIDE" if multiarea else bool(secundarias)
        nivel = NIVEL_ALTA if (len(comuns_fortes) >= 2 or independente) else NIVEL_MEDIA
    elif comuns_citados:
        nivel = NIVEL_BAIXA
    elif generalista and edital_cultural:
        nivel = NIVEL_MEDIA
    elif programa_artes and edital_cultural:
        nivel = NIVEL_BAIXA
    else:
        nivel = NIVEL_NAO_IDENTIFICADA

    rebaixado = False
    if territorio["estado"] == "INCOMPATIVEL" and nivel not in (NIVEL_NAO_IDENTIFICADA, NIVEL_BAIXA):
        nivel, rebaixado = _rebaixar(nivel), True
        evidencias.append("Território incompatível: o nível foi reduzido em um degrau.")

    justificativa = _justificar(programa, nivel, comuns_fortes or comuns_citados, secundarias, rebaixado, dados_insuficientes,
                                edital_vazio, multiarea, bool(comuns_fortes))
    criterios.append({"criterio": "Elegibilidade", "resultado": "Fora deste nível",
                      "detalhe": "A elegibilidade da OSC não entra no nível temático; veja o bloco “Elegibilidade da OSC”. " + AVISO_ELEGIBILIDADE})
    return {"programa_id": programa.get("id"), "nome": programa.get("nome"), "nivel": nivel, "evidencias": evidencias,
            "justificativa": justificativa, "criterios": criterios, "dados_insuficientes": dados_insuficientes}


def _justificar(programa, nivel, comuns, secundarias, rebaixado, insuficiente, edital_vazio, multiarea=False, forte=True) -> str:
    nome = programa.get("nome")
    if edital_vazio:
        return "O edital não traz texto suficiente para comparar com os projetos do IORM."
    if insuficiente:
        return f"Não há dados suficientes sobre o projeto “{nome}” no Cérebro da OSC para compará-lo com este edital."
    if nivel == NIVEL_ALTA:
        base = f"O edital trata de {', '.join(comuns)}, tema central do projeto “{nome}”, e há {', '.join(secundarias)}."
    elif nivel == NIVEL_MEDIA and comuns and multiarea:
        base = (f"O edital aceita várias linguagens e {', '.join(comuns)} é uma delas — tema do projeto “{nome}”. "
                "Combina, mas o edital não é focado nesse tema.")
    elif nivel == NIVEL_MEDIA and comuns:
        base = f"O edital trata de {', '.join(comuns)}, tema do projeto “{nome}”, mas sem outra evidência de apoio (território/público)."
    elif nivel == NIVEL_MEDIA:
        base = f"“{nome}” é um projeto geral de arte e cultura e o edital é da área cultural."
    elif nivel == NIVEL_BAIXA and comuns and not forte:
        base = f"{', '.join(comuns)} (tema do projeto “{nome}”) aparece só de passagem no texto do edital, sem ser uma das áreas declaradas."
    elif nivel == NIVEL_BAIXA:
        base = f"Só a grande área (arte/cultura) coincide com “{nome}”; a linguagem do projeto não aparece no edital."
    else:
        base = f"Nenhuma evidência ligando o edital ao projeto “{nome}”."
    return base + (" Nível reduzido por incompatibilidade de território." if rebaixado else "")


def analisar(edital: dict, perfil: dict) -> dict:
    """Análise completa (sem gravar): projetos ordenados do mais para o menos adequado + elegibilidade."""
    territorio = avaliar_territorio(edital.get("territorio"), perfil)
    projetos = [avaliar_programa(edital, p, perfil, territorio) for p in perfil.get("programas", [])
                if str(p.get("status") or "ATIVO").upper() != "INATIVO"]
    projetos.sort(key=lambda p: (-_ORDEM[p["nivel"]], str(p["nome"])))
    return {"projetos": projetos, "elegibilidade": avaliar_elegibilidade(edital), "territorio": territorio}


# ------------------------------------------------------------------ persistência
def criar_tabelas(conexao: sqlite3.Connection) -> None:
    conexao.executescript(
        """
        CREATE TABLE IF NOT EXISTS editais_projetos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            edital_id INTEGER NOT NULL,
            programa_id INTEGER NOT NULL,
            programa_nome TEXT NOT NULL,
            nivel TEXT NOT NULL,
            evidencias_json TEXT,
            justificativa TEXT,
            criterios_json TEXT,
            dados_insuficientes INTEGER NOT NULL DEFAULT 0,
            versao TEXT NOT NULL,
            base_hash TEXT NOT NULL,
            calculado_em TEXT NOT NULL,
            UNIQUE (edital_id, programa_id)
        );
        CREATE TABLE IF NOT EXISTS editais_analise (
            edital_id INTEGER PRIMARY KEY,
            elegibilidade_status TEXT,
            elegibilidade_json TEXT,
            territorio_estado TEXT,
            versao TEXT NOT NULL,
            base_hash TEXT NOT NULL,
            calculado_em TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_editais_projetos_edital ON editais_projetos (edital_id);
        """
    )
    conexao.commit()


def _hash_base(edital: dict, perfil: dict) -> str:
    """Muda quando muda o edital, o Cérebro da OSC (programas, áreas, palavras-chave, territórios) ou a versão da regra."""
    partes = {
        "v": VERSAO_ANALISE,
        "edital": [str(edital.get(c) or "") for c in ("titulo", "descricao", "area_tematica", "texto_resumo", "territorio", "publico", "requisitos")],
        "programas": [[str(p.get(c) or "") for c in ("id", "nome", "descricao", "publico", "faixa_etaria", "tema", "cidade", "estado", "objetivos", "status")]
                      for p in sorted(perfil.get("programas", []), key=lambda p: p.get("id") or 0)],
        "temas": sorted(perfil.get("temas", [])), "palavras": sorted(perfil.get("palavras_chave", [])),
        "territorios": sorted(str(t.get("valor")) for t in perfil.get("territorios", [])),
    }
    return hashlib.sha1(json.dumps(partes, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def analisar_e_salvar(conexao: sqlite3.Connection, edital: dict, perfil: dict, forcar: bool = False) -> bool:
    """Grava a análise do edital. Devolve True se recalculou, False se o que já estava salvo continua válido
    (mesmo hash). Sem duplicatas: UNIQUE(edital_id, programa_id) + upsert. Projetos que saíram do Cérebro da OSC
    saem da análise (é dado derivado, sempre recalculável)."""
    criar_tabelas(conexao)
    hash_atual = _hash_base(edital, perfil)
    existente = conexao.execute("SELECT base_hash FROM editais_analise WHERE edital_id = ?", (edital["id"],)).fetchone()
    if existente and existente[0] == hash_atual and not forcar:
        return False
    resultado = analisar(edital, perfil)
    agora = _agora()
    ids_atuais = []
    for p in resultado["projetos"]:
        ids_atuais.append(p["programa_id"])
        conexao.execute(
            """INSERT INTO editais_projetos (edital_id, programa_id, programa_nome, nivel, evidencias_json, justificativa,
                   criterios_json, dados_insuficientes, versao, base_hash, calculado_em)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (edital_id, programa_id) DO UPDATE SET programa_nome = excluded.programa_nome, nivel = excluded.nivel,
                   evidencias_json = excluded.evidencias_json, justificativa = excluded.justificativa,
                   criterios_json = excluded.criterios_json, dados_insuficientes = excluded.dados_insuficientes,
                   versao = excluded.versao, base_hash = excluded.base_hash, calculado_em = excluded.calculado_em""",
            (edital["id"], p["programa_id"], p["nome"], p["nivel"], json.dumps(p["evidencias"], ensure_ascii=False), p["justificativa"],
             json.dumps(p["criterios"], ensure_ascii=False), int(p["dados_insuficientes"]), VERSAO_ANALISE, hash_atual, agora),
        )
    if ids_atuais:
        marcadores = ", ".join("?" for _ in ids_atuais)
        conexao.execute(f"DELETE FROM editais_projetos WHERE edital_id = ? AND programa_id NOT IN ({marcadores})", (edital["id"], *ids_atuais))
    else:
        conexao.execute("DELETE FROM editais_projetos WHERE edital_id = ?", (edital["id"],))
    conexao.execute(
        """INSERT INTO editais_analise (edital_id, elegibilidade_status, elegibilidade_json, territorio_estado, versao, base_hash, calculado_em)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT (edital_id) DO UPDATE SET elegibilidade_status = excluded.elegibilidade_status,
               elegibilidade_json = excluded.elegibilidade_json, territorio_estado = excluded.territorio_estado,
               versao = excluded.versao, base_hash = excluded.base_hash, calculado_em = excluded.calculado_em""",
        (edital["id"], resultado["elegibilidade"]["status"], json.dumps(resultado["elegibilidade"], ensure_ascii=False),
         resultado["territorio"]["estado"], VERSAO_ANALISE, hash_atual, agora),
    )
    conexao.commit()
    return True


def garantir_analise(conexao: sqlite3.Connection, edital, perfil: dict) -> dict:
    """Recalcula se estiver desatualizada (edital ou Cérebro da OSC mudaram) e devolve o que está salvo."""
    dados = dict(edital)
    analisar_e_salvar(conexao, dados, perfil)
    return carregar_analise(conexao, dados["id"])


def reanalisar_todos(conexao: sqlite3.Connection, perfil: dict, forcar: bool = False) -> int:
    """Recalcula todos os editais (só os que mudaram, salvo `forcar`). Devolve quantos foram recalculados."""
    criar_tabelas(conexao)
    cursor = conexao.execute("SELECT * FROM editais")
    colunas = [c[0] for c in cursor.description]
    total = 0
    for linha in cursor.fetchall():
        if analisar_e_salvar(conexao, dict(zip(colunas, tuple(linha))), perfil, forcar):
            total += 1
    return total


def carregar_analise(conexao: sqlite3.Connection, edital_id: int) -> dict:
    criar_tabelas(conexao)
    projetos = []
    for r in conexao.execute(
        """SELECT programa_id, programa_nome, nivel, evidencias_json, justificativa, criterios_json, dados_insuficientes,
                  versao, calculado_em FROM editais_projetos WHERE edital_id = ?""", (edital_id,)
    ).fetchall():
        projetos.append({"programa_id": r[0], "nome": r[1], "nivel": r[2], "evidencias": json.loads(r[3] or "[]"),
                         "justificativa": r[4], "criterios": json.loads(r[5] or "[]"), "dados_insuficientes": bool(r[6]),
                         "versao": r[7], "calculado_em": r[8]})
    projetos.sort(key=lambda p: (-_ORDEM[p["nivel"]], str(p["nome"])))
    linha = conexao.execute(
        "SELECT elegibilidade_json, territorio_estado, versao, calculado_em FROM editais_analise WHERE edital_id = ?", (edital_id,)
    ).fetchone()
    return {
        "projetos": projetos,
        "relacionados": [p for p in projetos if p["nivel"] in NIVEIS_RELACIONADOS],
        "outros": [p for p in projetos if p["nivel"] not in NIVEIS_RELACIONADOS],
        "elegibilidade": json.loads(linha[0]) if linha and linha[0] else None,
        "territorio_estado": linha[1] if linha else None,
        "versao": linha[2] if linha else None,
        "calculado_em": linha[3] if linha else None,
    }
