"""Radar de Editais: estrutura de dados + motor de aderência.

IMPORTANTE (ver docs/decisoes.md): não existe, neste ambiente, uma busca
automática ligada a fontes de editais — isso exigiria integrações que
ainda não foram construídas/autorizadas. As funções deste módulo
processam editais que já foram cadastrados (manualmente ou por um
agente de pesquisa, como o módulo de enriquecimento), nunca buscam
sozinhas na internet.

O motor de aderência é 100% baseado em regras (sem machine learning) e
sempre explica os critérios usados, para nunca virar uma "nota
misteriosa".
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from datetime import date, datetime, timezone

STATUS_VALIDOS = [
    "ENCONTRADO",
    "EM_ANALISE",
    "ADERENTE",
    "NAO_ADERENTE",
    "INTERESSANTE",
    "EM_PREPARACAO",
    "INSCRITO",
    "APROVADO",
    "REPROVADO",
    "ENCERRADO",
]

TIPOS_OPORTUNIDADE = [
    "EDITAL",
    "CHAMADA_PUBLICA",
    "PREMIO",
    "FINANCIAMENTO",
    "FUNDO",
    "PATROCINIO",
    "CHAMADA_INSTITUTO_FUNDACAO",
    "OUTRO",
]

# Situação de inscrição — DIFERENTE do campo `status` (que é o acompanhamento
# interno do IORM sobre o edital, tipo "em análise"/"inscrito"). Este campo
# responde só "a inscrição está aberta?", e por padrão nunca afirma "aberto"
# sem confirmação: só vira ABERTO/ENCERRADO/PROXIMO quando uma data real foi
# informada; sem isso, fica NAO_CONFIRMADO (nunca inventa).
SITUACOES_INSCRICAO = ["ABERTO", "ENCERRADO", "PROXIMO", "NAO_CONFIRMADO"]


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _remover_acentos(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def _normalizar(texto: str | None) -> str:
    return _remover_acentos((texto or "").lower())


def criar_tabelas(conexao: sqlite3.Connection) -> None:
    conexao.executescript(
        """
        CREATE TABLE IF NOT EXISTS editais (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT NOT NULL,
            organizacao_promotora TEXT,
            descricao TEXT,
            url TEXT,
            fonte TEXT NOT NULL,
            data_publicacao TEXT,
            data_encerramento TEXT,
            valor_texto TEXT,
            valor_numerico REAL,
            territorio TEXT,
            publico TEXT,
            requisitos TEXT,
            tipo TEXT NOT NULL DEFAULT 'OUTRO',
            status TEXT NOT NULL DEFAULT 'ENCONTRADO',
            texto_resumo TEXT,
            situacao_inscricao TEXT NOT NULL DEFAULT 'NAO_CONFIRMADO',
            origem_descoberta TEXT NOT NULL DEFAULT 'MANUAL',
            coletado_em TEXT NOT NULL,
            criado_em TEXT NOT NULL,
            atualizado_em TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS editais_aderencia (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            edital_id INTEGER NOT NULL REFERENCES editais(id),
            osc_id INTEGER NOT NULL,
            nota_area REAL,
            nota_territorio REAL,
            nota_publico REAL,
            nota_elegibilidade REAL,
            nota_valor REAL,
            nota_prazo REAL,
            nota_final REAL,
            motivos TEXT,
            pontos_atencao TEXT,
            calculado_em TEXT NOT NULL
        );
        """
    )
    conexao.commit()
    migrar_colunas_novas(conexao)  # bancos novos e antigos terminam com o mesmo conjunto de colunas


_COLUNAS_MIGRACAO = {
    "situacao_inscricao": "TEXT NOT NULL DEFAULT 'NAO_CONFIRMADO'",
    "origem_descoberta": "TEXT NOT NULL DEFAULT 'MANUAL'",
    "url_inscricao": "TEXT",
    "area_tematica": "TEXT",
    "data_abertura": "TEXT",
    "link_status": "TEXT NOT NULL DEFAULT 'NAO_VERIFICADO'",
    "link_http_status": "INTEGER",
    "link_url_final": "TEXT",
    "link_correspondencia": "REAL",
    "link_motivo": "TEXT",
    "link_verificado_em": "TEXT",
    "inscricao_verificada": "INTEGER NOT NULL DEFAULT 0",
    "inscricao_origem": "TEXT",
    "inscricao_motivo": "TEXT",
}


def migrar_colunas_novas(conexao: sqlite3.Connection) -> None:
    """Migração idempotente para bancos criados antes de cada recurso
    existir — adiciona colunas sem apagar nada."""
    colunas = {linha["name"] for linha in conexao.execute("PRAGMA table_info(editais)")}
    for coluna, definicao in _COLUNAS_MIGRACAO.items():
        if coluna not in colunas:
            conexao.execute(f"ALTER TABLE editais ADD COLUMN {coluna} {definicao}")
    conexao.commit()


def registrar_verificacao(conexao: sqlite3.Connection, edital_id: int, verificacao: dict,
                          inscricao: dict | None = None) -> None:
    """Grava o resultado de links_editais.verificar_link (+ verificar_inscricao).
    O link de inscrição só é guardado quando foi ENCONTRADO na página do
    edital (ou já vinha cadastrado como tal); nunca é copiado do link do
    edital. Se a página traz sinal claro de inscrições encerradas, a
    situação passa a ENCERRADO (evidência literal na página oficial)."""
    campos = {
        "link_status": verificacao["status"], "link_http_status": verificacao.get("http_status"),
        "link_url_final": verificacao.get("url_final"), "link_correspondencia": verificacao.get("correspondencia"),
        "link_motivo": verificacao.get("motivo"), "link_verificado_em": verificacao.get("verificado_em") or _agora(),
    }
    encontrada = verificacao.get("url_inscricao_encontrada")
    if encontrada:
        campos["url_inscricao"] = encontrada
        campos["inscricao_origem"] = "EXTRAIDO_DA_PAGINA_DO_EDITAL"
    if inscricao is not None:
        campos["inscricao_verificada"] = int(inscricao["ok"])
        campos["inscricao_motivo"] = inscricao["motivo"]
    if verificacao.get("indicio_encerrado"):
        campos["situacao_inscricao"] = "ENCERRADO"
    campos["atualizado_em"] = _agora()
    atribuicoes = ", ".join(f"{k} = ?" for k in campos)
    conexao.execute(f"UPDATE editais SET {atribuicoes} WHERE id = ?", (*campos.values(), edital_id))
    conexao.commit()


def verificar_e_registrar(conexao: sqlite3.Connection, edital_id: int, buscador=None) -> dict:
    """Verifica a página do edital e o link de inscrição (se houver) e grava."""
    from processamento import links_editais

    linha = conexao.execute("SELECT titulo, url, url_inscricao FROM editais WHERE id = ?", (edital_id,)).fetchone()
    verificacao = links_editais.verificar_link(linha["url"], linha["titulo"], buscador)
    url_inscricao = verificacao.get("url_inscricao_encontrada") or linha["url_inscricao"]
    inscricao = links_editais.verificar_inscricao(url_inscricao, buscador) if url_inscricao else None
    registrar_verificacao(conexao, edital_id, verificacao, inscricao)
    return {"verificacao": verificacao, "inscricao": inscricao}


def classificar_situacao_inscricao(data_publicacao: str | None, data_encerramento: str | None,
                                     hoje: date | None = None) -> str:
    """Nunca afirma "aberto" sem uma data real que confirme isso — sem
    data de encerramento, a situação fica sempre NAO_CONFIRMADO."""
    hoje = hoje or datetime.now(timezone.utc).date()
    if not data_encerramento:
        return "NAO_CONFIRMADO"
    try:
        encerramento = datetime.fromisoformat(str(data_encerramento)[:10]).date()
    except ValueError:
        return "NAO_CONFIRMADO"
    if encerramento < hoje:
        return "ENCERRADO"
    if data_publicacao:
        try:
            publicacao = datetime.fromisoformat(str(data_publicacao)[:10]).date()
            if publicacao > hoje:
                return "PROXIMO"
        except ValueError:
            pass
    return "ABERTO"


def criar_edital(conexao: sqlite3.Connection, dados: dict) -> int:
    agora = _agora()
    situacao = dados.get("situacao_inscricao") or classificar_situacao_inscricao(
        dados.get("data_publicacao"), dados.get("data_encerramento")
    )
    valores = {
        "titulo": dados["titulo"],
        "organizacao_promotora": dados.get("organizacao_promotora"),
        "descricao": dados.get("descricao"),
        "url": dados.get("url"),
        "url_inscricao": dados.get("url_inscricao"),
        "fonte": dados.get("fonte", "Cadastro manual"),
        "data_publicacao": dados.get("data_publicacao"),
        "data_abertura": dados.get("data_abertura"),
        "data_encerramento": dados.get("data_encerramento"),
        "valor_texto": dados.get("valor_texto"),
        "valor_numerico": dados.get("valor_numerico"),
        "territorio": dados.get("territorio"),
        "publico": dados.get("publico"),
        "area_tematica": dados.get("area_tematica"),
        "requisitos": dados.get("requisitos"),
        "tipo": dados.get("tipo", "OUTRO"),
        "status": dados.get("status", "ENCONTRADO"),
        "texto_resumo": dados.get("texto_resumo"),
        "situacao_inscricao": situacao,
        "origem_descoberta": dados.get("origem_descoberta", "MANUAL"),
        "coletado_em": dados.get("coletado_em", agora),
        "criado_em": agora,
        "atualizado_em": agora,
    }
    colunas = ", ".join(valores)
    marcadores = ", ".join("?" for _ in valores)
    cursor = conexao.execute(f"INSERT INTO editais ({colunas}) VALUES ({marcadores})", tuple(valores.values()))
    conexao.commit()
    return cursor.lastrowid

def atualizar_status(conexao: sqlite3.Connection, edital_id: int, status: str) -> None:
    if status not in STATUS_VALIDOS:
        raise ValueError(f"Status inválido: {status!r}")
    conexao.execute(
        "UPDATE editais SET status = ?, atualizado_em = ? WHERE id = ?", (status, _agora(), edital_id)
    )
    conexao.commit()


def listar_editais(conexao: sqlite3.Connection) -> list[sqlite3.Row]:
    return conexao.execute("SELECT * FROM editais ORDER BY criado_em DESC").fetchall()


# ------------------------------------------------------------------
# Motor de aderência — cada critério devolve (nota 0-10 ou None, motivo)
# ------------------------------------------------------------------

PESOS_CRITERIOS = {
    "area": 0.25,
    "territorio": 0.20,
    "publico": 0.15,
    "elegibilidade": 0.15,
    "valor": 0.10,
    "prazo": 0.15,
}

_TERMOS_ELEGIBILIDADE_POSITIVOS = [
    "osc", "organizacao da sociedade civil", "organizacao sem fins lucrativos",
    "terceiro setor", "associacao sem fins lucrativos", "instituicao sem fins lucrativos",
]
_TERMOS_ELEGIBILIDADE_NEGATIVOS = [
    "somente empresas", "apenas empresas privadas", "pessoa fisica apenas",
    "exclusivo para empresas",
]


def _avaliar_area(edital: dict, temas_osc: list[str], palavras_chave_osc: list[str]) -> tuple[float | None, str]:
    texto = _normalizar(" ".join(filter(None, [edital.get("titulo"), edital.get("descricao"), edital.get("texto_resumo")])))
    if not texto:
        return None, "Edital sem descrição suficiente para avaliar área de atuação."
    termos = [_normalizar(t) for t in (temas_osc + palavras_chave_osc) if t]
    if not termos:
        return None, "OSC ainda não tem temas/palavras-chave cadastrados no Cérebro da OSC."
    encontrados = sorted({t for t in termos if t in texto})
    if not encontrados:
        return 0.0, "Nenhum tema/palavra-chave da OSC apareceu no texto do edital."
    nota = min(10.0, 4.0 + 2.0 * len(encontrados))
    return nota, f"Temas/palavras-chave encontrados no edital: {', '.join(encontrados)}."


def _avaliar_territorio(edital: dict, cidades_osc: list[str], estados_osc: list[str]) -> tuple[float | None, str]:
    territorio = _normalizar(edital.get("territorio"))
    if not territorio:
        return None, "Edital não informa o território elegível."
    if "nacional" in territorio or "todo o brasil" in territorio or "brasil" in territorio:
        return 10.0, "Edital é de abrangência nacional — cobre o território de atuação da OSC."
    cidades_match = [c for c in cidades_osc if _normalizar(c) in territorio]
    if cidades_match:
        return 10.0, f"Território do edital inclui cidade(s) de atuação da OSC: {', '.join(cidades_match)}."
    estados_match = [e for e in estados_osc if _normalizar(e) in territorio]
    if estados_match:
        return 7.0, f"Território do edital inclui o(s) estado(s) de atuação da OSC: {', '.join(estados_match)}."
    return 0.0, "Território do edital não parece incluir nenhuma cidade/estado cadastrado da OSC."


def _avaliar_publico(edital: dict, programas_osc: list[dict]) -> tuple[float | None, str]:
    publico_edital = _normalizar(edital.get("publico"))
    if not publico_edital:
        return None, "Edital não descreve o público elegível."
    publicos_osc = _normalizar(" ".join(filter(None, [p.get("publico") for p in programas_osc])))
    if not publicos_osc:
        return None, "Nenhum programa da OSC tem público cadastrado para comparar."
    palavras_edital = set(re.findall(r"[a-z]{4,}", publico_edital))
    palavras_osc = set(re.findall(r"[a-z]{4,}", publicos_osc))
    interseccao = palavras_edital & palavras_osc
    if not interseccao:
        return 2.0, "Público do edital não bateu com nenhum público já atendido em programas da OSC."
    proporcao = len(interseccao) / max(1, len(palavras_edital))
    nota = round(min(10.0, 4.0 + proporcao * 6.0), 1)
    return nota, f"Termos em comum com o público dos programas da OSC: {', '.join(sorted(interseccao))}."


def _avaliar_elegibilidade(edital: dict) -> tuple[float | None, str]:
    requisitos = _normalizar(edital.get("requisitos"))
    if not requisitos:
        return None, "Edital não tem requisitos de elegibilidade cadastrados."
    if any(termo in requisitos for termo in _TERMOS_ELEGIBILIDADE_NEGATIVOS):
        return 0.0, "Os requisitos parecem excluir OSCs (linguagem voltada só a empresas)."
    if any(termo in requisitos for termo in _TERMOS_ELEGIBILIDADE_POSITIVOS):
        return 8.0, "Os requisitos mencionam explicitamente OSC/organização sem fins lucrativos."
    return 5.0, "Requisitos cadastrados, mas sem menção clara a OSC — vale checar manualmente."


def _avaliar_valor(edital: dict) -> tuple[float | None, str]:
    if edital.get("valor_numerico"):
        return 10.0, "Valor do edital está informado com um número, facilitando a decisão."
    if edital.get("valor_texto"):
        return 5.0, "Edital informa o valor só em texto livre (sem número exato)."
    return None, "Edital não informa valor."


def _avaliar_prazo(edital: dict, hoje: date | None = None) -> tuple[float | None, str]:
    hoje = hoje or datetime.now(timezone.utc).date()
    data_texto = edital.get("data_encerramento")
    if not data_texto:
        return None, "Edital não informa data de encerramento."
    try:
        data_encerramento = datetime.fromisoformat(str(data_texto)[:10]).date()
    except ValueError:
        return None, "Data de encerramento em formato não reconhecido."
    dias_restantes = (data_encerramento - hoje).days
    if dias_restantes < 0:
        return 0.0, f"Prazo encerrado há {abs(dias_restantes)} dia(s)."
    if dias_restantes < 5:
        return 1.0, f"Só restam {dias_restantes} dia(s) — prazo muito apertado."
    if dias_restantes < 15:
        return 4.0, f"Restam {dias_restantes} dias — prazo apertado."
    if dias_restantes < 30:
        return 7.0, f"Restam {dias_restantes} dias — prazo razoável."
    return 10.0, f"Restam {dias_restantes} dias — prazo confortável."


def calcular_aderencia(edital: dict, perfil_osc: dict, hoje: date | None = None) -> dict:
    """Devolve nota por critério (0-10 ou None quando faltam dados),
    nota final (0-10, recalculada só com os critérios disponíveis),
    e as frases de "por que recomendamos" / "pontos de atenção"."""
    nota_area, motivo_area = _avaliar_area(edital, perfil_osc.get("temas", []), perfil_osc.get("palavras_chave", []))
    nota_territorio, motivo_territorio = _avaliar_territorio(
        edital, perfil_osc.get("cidades", []), perfil_osc.get("estados", [])
    )
    nota_publico, motivo_publico = _avaliar_publico(edital, perfil_osc.get("programas", []))
    nota_elegibilidade, motivo_elegibilidade = _avaliar_elegibilidade(edital)
    nota_valor, motivo_valor = _avaliar_valor(edital)
    nota_prazo, motivo_prazo = _avaliar_prazo(edital, hoje)

    criterios = {
        "area": (nota_area, motivo_area),
        "territorio": (nota_territorio, motivo_territorio),
        "publico": (nota_publico, motivo_publico),
        "elegibilidade": (nota_elegibilidade, motivo_elegibilidade),
        "valor": (nota_valor, motivo_valor),
        "prazo": (nota_prazo, motivo_prazo),
    }

    disponiveis = {chave: nota for chave, (nota, _) in criterios.items() if nota is not None}
    if disponiveis:
        peso_total = sum(PESOS_CRITERIOS[chave] for chave in disponiveis)
        nota_final = round(
            sum(PESOS_CRITERIOS[chave] * nota for chave, nota in disponiveis.items()) / peso_total, 1
        )
    else:
        nota_final = None

    motivos = [motivo for chave, (nota, motivo) in criterios.items() if nota is not None and nota >= 7]
    pontos_atencao = [
        motivo for chave, (nota, motivo) in criterios.items() if nota is not None and nota < 5
    ]
    faltando = [motivo for chave, (nota, motivo) in criterios.items() if nota is None]

    return {
        "nota_area": nota_area,
        "nota_territorio": nota_territorio,
        "nota_publico": nota_publico,
        "nota_elegibilidade": nota_elegibilidade,
        "nota_valor": nota_valor,
        "nota_prazo": nota_prazo,
        "nota_final": nota_final,
        "motivos_recomendacao": motivos,
        "pontos_atencao": pontos_atencao + faltando,
    }


def salvar_aderencia(conexao: sqlite3.Connection, edital_id: int, osc_id: int, resultado: dict) -> int:
    cursor = conexao.execute(
        """INSERT INTO editais_aderencia
           (edital_id, osc_id, nota_area, nota_territorio, nota_publico, nota_elegibilidade,
            nota_valor, nota_prazo, nota_final, motivos, pontos_atencao, calculado_em)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            edital_id,
            osc_id,
            resultado["nota_area"],
            resultado["nota_territorio"],
            resultado["nota_publico"],
            resultado["nota_elegibilidade"],
            resultado["nota_valor"],
            resultado["nota_prazo"],
            resultado["nota_final"],
            " | ".join(resultado["motivos_recomendacao"]),
            " | ".join(resultado["pontos_atencao"]),
            _agora(),
        ),
    )
    conexao.commit()
    return cursor.lastrowid
