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


def criar_edital(conexao: sqlite3.Connection, dados: dict) -> int:
    agora = _agora()
    cursor = conexao.execute(
        """INSERT INTO editais
           (titulo, organizacao_promotora, descricao, url, fonte, data_publicacao, data_encerramento,
            valor_texto, valor_numerico, territorio, publico, requisitos, tipo, status, texto_resumo,
            coletado_em, criado_em, atualizado_em)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            dados["titulo"],
            dados.get("organizacao_promotora"),
            dados.get("descricao"),
            dados.get("url"),
            dados.get("fonte", "Cadastro manual"),
            dados.get("data_publicacao"),
            dados.get("data_encerramento"),
            dados.get("valor_texto"),
            dados.get("valor_numerico"),
            dados.get("territorio"),
            dados.get("publico"),
            dados.get("requisitos"),
            dados.get("tipo", "OUTRO"),
            dados.get("status", "ENCONTRADO"),
            dados.get("texto_resumo"),
            dados.get("coletado_em", agora),
            agora,
            agora,
        ),
    )
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
