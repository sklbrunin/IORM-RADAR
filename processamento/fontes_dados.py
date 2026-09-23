"""Central de Fontes de Dados: a equipe cadastra uma fonte (portal de editais, base de
incentivos, feed de notícias...) e o sistema registra COMO ela pode ser consultada.

Arquitetura (nada aqui inventa capacidade de coleta):

    FONTE cadastrada  →  avaliar_acesso()  →  método de acesso REAL detectado
        FEED (RSS/Atom)  →  FeedAdapter  →  candidatos  →  filtro de relevância  →  editais (banco)
        API_JSON / PAGINA_PUBLICA / MANUAL  →  só registrada (consulta manual ou integração
                                               dedicada futura — sem raspagem frágil)

Só o que tem estrutura pública estável (feed) é coletado automaticamente. Todo item coletado
entra como NÃO CONFIRMADO (feeds não trazem prazo verificável) e guarda a fonte + data.
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Callable
from urllib.parse import urlparse

TIPOS = ["Editais", "Incentivos", "Empresas", "Dados governamentais", "Notícias", "OSC", "Contatos", "Outros"]
FREQUENCIAS = {"MANUAL": None, "DIARIA": 1, "SEMANAL": 7, "MENSAL": 30}
ROTULOS_FREQUENCIA = {"MANUAL": "Somente manual", "DIARIA": "Diária", "SEMANAL": "Semanal", "MENSAL": "Mensal"}

ACESSO_NAO_AVALIADO = "NAO_AVALIADO"
ACESSO_FEED = "FEED"
ACESSO_API_JSON = "API_JSON"
ACESSO_PAGINA = "PAGINA_PUBLICA"
ACESSO_MANUAL = "MANUAL"
ACESSO_INACESSIVEL = "INACESSIVEL"
ROTULOS_ACESSO = {
    ACESSO_NAO_AVALIADO: "Ainda não avaliada",
    ACESSO_FEED: "Feed RSS/Atom — coleta automática disponível",
    ACESSO_API_JSON: "API/JSON — integração dedicada necessária (ainda não implementada)",
    ACESSO_PAGINA: "Página pública (HTML) — só consulta manual; avaliar integração antes de automatizar",
    ACESSO_MANUAL: "Consulta manual",
    ACESSO_INACESSIVEL: "Não acessível agora",
}

LIMITE_BYTES = 2 * 1024 * 1024
# Palavras INTEIRAS (sem acento) que indicam edital/chamada. Propositalmente estreito: termos soltos como
# "seleção" ou "prêmio" trazem notícia de futebol e de Nobel para dentro do Radar.
_PADRAO_OPORTUNIDADE = re.compile(
    r"\b(edital|editais|chamamento|chamada publica|chamada de projetos|chamada para (?:osc|organizacoes)|fomento|"
    r"convocatoria|selecao publica|inscricoes abertas|abre inscricoes|abertura de inscricoes)\b"
)
ORIGEM_FONTE_CADASTRADA = "FONTE_CADASTRADA"

Fetcher = Callable[[str], tuple[int, str, str]]  # url -> (http_status, content_type, texto)


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def criar_tabelas(conexao: sqlite3.Connection) -> None:
    conexao.executescript(
        """
        CREATE TABLE IF NOT EXISTS fontes_dados (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            tipo TEXT NOT NULL,
            url TEXT NOT NULL UNIQUE,
            categoria TEXT,
            descricao TEXT,
            ativo INTEGER NOT NULL DEFAULT 1,
            frequencia TEXT NOT NULL DEFAULT 'MANUAL',
            metodo_acesso TEXT NOT NULL DEFAULT 'NAO_AVALIADO',
            acesso_detalhe TEXT,
            avaliado_em TEXT,
            ultima_consulta TEXT,
            proxima_consulta TEXT,
            ultimo_resultado TEXT,
            observacoes TEXT,
            criado_em TEXT NOT NULL,
            atualizado_em TEXT NOT NULL
        );
        """
    )
    conexao.commit()


def _validar_url(url: str) -> str:
    url = (url or "").strip()
    partes = urlparse(url)
    if partes.scheme not in ("http", "https") or not partes.netloc or " " in url:
        raise ValueError("Informe uma URL completa começando com http:// ou https://.")
    return url


def proxima_consulta(frequencia: str, ultima: datetime | None) -> str | None:
    dias = FREQUENCIAS.get(frequencia)
    if dias is None:
        return None
    base = ultima or _agora()
    return (base + timedelta(days=dias)).isoformat()


def cadastrar(conexao: sqlite3.Connection, dados: dict) -> int:
    nome = (dados.get("nome") or "").strip()
    if not nome:
        raise ValueError("O nome da fonte é obrigatório.")
    tipo = dados.get("tipo") or ""
    if tipo not in TIPOS:
        raise ValueError(f"Tipo inválido: {tipo!r}.")
    url = _validar_url(dados.get("url"))
    frequencia = dados.get("frequencia", "MANUAL")
    if frequencia not in FREQUENCIAS:
        raise ValueError(f"Frequência inválida: {frequencia!r}.")
    if conexao.execute("SELECT 1 FROM fontes_dados WHERE url = ?", (url,)).fetchone():
        raise ValueError("Já existe uma fonte cadastrada com essa URL.")
    agora = _agora().isoformat()
    cursor = conexao.execute(
        """INSERT INTO fontes_dados (nome, tipo, url, categoria, descricao, ativo, frequencia, observacoes,
                                     proxima_consulta, criado_em, atualizado_em)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (nome, tipo, url, (dados.get("categoria") or "").strip() or None, (dados.get("descricao") or "").strip() or None,
         int(bool(dados.get("ativo", True))), frequencia, (dados.get("observacoes") or "").strip() or None,
         proxima_consulta(frequencia, None), agora, agora),
    )
    conexao.commit()
    return cursor.lastrowid


_EDITAVEIS = {"nome", "tipo", "url", "categoria", "descricao", "frequencia", "observacoes"}


def atualizar(conexao: sqlite3.Connection, fonte_id: int, campos: dict) -> None:
    campos = {k: v for k, v in campos.items() if k in _EDITAVEIS}
    if not campos:
        return
    if "nome" in campos and not (campos["nome"] or "").strip():
        raise ValueError("O nome da fonte é obrigatório.")
    if "tipo" in campos and campos["tipo"] not in TIPOS:
        raise ValueError(f"Tipo inválido: {campos['tipo']!r}.")
    if "frequencia" in campos and campos["frequencia"] not in FREQUENCIAS:
        raise ValueError(f"Frequência inválida: {campos['frequencia']!r}.")
    if "url" in campos:
        campos["url"] = _validar_url(campos["url"])
        outra = conexao.execute("SELECT id FROM fontes_dados WHERE url = ? AND id != ?", (campos["url"], fonte_id)).fetchone()
        if outra:
            raise ValueError("Já existe outra fonte cadastrada com essa URL.")
        campos["metodo_acesso"] = ACESSO_NAO_AVALIADO  # URL mudou: a avaliação anterior não vale mais
        campos["acesso_detalhe"] = None
    if "frequencia" in campos:
        atual = conexao.execute("SELECT ultima_consulta FROM fontes_dados WHERE id = ?", (fonte_id,)).fetchone()
        ultima = datetime.fromisoformat(atual["ultima_consulta"]) if atual and atual["ultima_consulta"] else None
        campos["proxima_consulta"] = proxima_consulta(campos["frequencia"], ultima)
    campos["atualizado_em"] = _agora().isoformat()
    atribuicoes = ", ".join(f"{k} = ?" for k in campos)
    conexao.execute(f"UPDATE fontes_dados SET {atribuicoes} WHERE id = ?", (*campos.values(), fonte_id))
    conexao.commit()


def definir_ativo(conexao: sqlite3.Connection, fonte_id: int, ativo: bool) -> None:
    conexao.execute("UPDATE fontes_dados SET ativo = ?, atualizado_em = ? WHERE id = ?",
                    (int(ativo), _agora().isoformat(), fonte_id))
    conexao.commit()


def listar(conexao: sqlite3.Connection, somente_ativas: bool = False) -> list[sqlite3.Row]:
    filtro = "WHERE ativo = 1" if somente_ativas else ""
    return conexao.execute(f"SELECT * FROM fontes_dados {filtro} ORDER BY ativo DESC, tipo, nome").fetchall()


def obter(conexao: sqlite3.Connection, fonte_id: int) -> sqlite3.Row | None:
    return conexao.execute("SELECT * FROM fontes_dados WHERE id = ?", (fonte_id,)).fetchone()


def devidas(conexao: sqlite3.Connection, agora: datetime | None = None) -> list[sqlite3.Row]:
    """Fontes ativas, com frequência automática, cuja próxima consulta já venceu."""
    agora = agora or _agora()
    return [
        f for f in listar(conexao, somente_ativas=True)
        if f["frequencia"] != "MANUAL" and (not f["proxima_consulta"] or datetime.fromisoformat(f["proxima_consulta"]) <= agora)
    ]


# --------------------------------------------------------------------------- acesso à fonte
def buscar_http(url: str) -> tuple[int, str, str]:
    import requests

    resposta = requests.get(url, headers={"User-Agent": "Mozilla/5.0 IORM-Radar/1.0 (fonte cadastrada pela equipe)"},
                            timeout=25, stream=True)
    partes, lidos = [], 0
    for bloco in resposta.iter_content(65536):  # laço: um único read pode devolver só parte do corpo
        partes.append(bloco)
        lidos += len(bloco)
        if lidos > LIMITE_BYTES:
            break
    resposta.close()
    conteudo = b"".join(partes)
    texto = conteudo[:LIMITE_BYTES].decode(resposta.encoding or "utf-8", errors="replace")
    return resposta.status_code, resposta.headers.get("content-type", ""), texto


def _e_feed(texto: str) -> bool:
    inicio = texto.lstrip()[:600].lower()
    return ("<rss" in inicio or "<feed" in inicio or "<rdf:rdf" in inicio) and "<html" not in inicio


def avaliar_acesso(url: str, fetcher: Fetcher | None = None) -> dict:
    """Descobre COMO a fonte pode ser consultada, olhando a resposta real. Nunca assume."""
    fetcher = fetcher or buscar_http
    try:
        status, tipo_conteudo, texto = fetcher(url)
    except Exception as exc:
        return {"metodo_acesso": ACESSO_INACESSIVEL, "http_status": None, "detalhe": f"{type(exc).__name__}: {str(exc)[:160]}"}
    return _classificar_resposta(status, tipo_conteudo, texto)


def _classificar_resposta(status: int, tipo_conteudo: str, texto: str) -> dict:
    if status >= 400:
        return {"metodo_acesso": ACESSO_INACESSIVEL, "http_status": status, "detalhe": f"A fonte respondeu HTTP {status}."}
    conteudo = (tipo_conteudo or "").lower()
    if _e_feed(texto):
        return {"metodo_acesso": ACESSO_FEED, "http_status": status, "detalhe": "Resposta é um feed RSS/Atom."}
    if "json" in conteudo or texto.lstrip().startswith(("{", "[")):
        return {"metodo_acesso": ACESSO_API_JSON, "http_status": status, "detalhe": "Resposta em JSON (estrutura própria da fonte)."}
    return {"metodo_acesso": ACESSO_PAGINA, "http_status": status,
            "detalhe": "Resposta em HTML: sem estrutura padronizada para coleta automática segura."}


def registrar_avaliacao(conexao: sqlite3.Connection, fonte_id: int, avaliacao: dict) -> None:
    conexao.execute(
        "UPDATE fontes_dados SET metodo_acesso = ?, acesso_detalhe = ?, avaliado_em = ?, atualizado_em = ? WHERE id = ?",
        (avaliacao["metodo_acesso"], avaliacao.get("detalhe"), _agora().isoformat(), _agora().isoformat(), fonte_id),
    )
    conexao.commit()


# --------------------------------------------------------------------------- adaptador de feed
def _texto_limpo(texto: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", texto or "")).strip()


def _sem_namespace(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _data_iso(texto: str | None) -> str | None:
    if not texto:
        return None
    texto = texto.strip()
    try:
        return datetime.fromisoformat(texto.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime

        return parsedate_to_datetime(texto).date().isoformat()
    except (TypeError, ValueError):
        return None


def interpretar_feed(texto: str) -> list[dict]:
    """RSS 2.0 e Atom → lista de {titulo, url, descricao, data_publicacao}. XML com DOCTYPE/ENTITY é
    recusado (proteção contra XML malicioso)."""
    if "<!entity" in texto.lower():
        raise ValueError("Feed recusado: contém definição de entidades XML.")
    raiz = ET.fromstring(texto.strip().encode("utf-8"))
    itens = []
    for elemento in raiz.iter():
        if _sem_namespace(elemento.tag) not in ("item", "entry"):
            continue
        campos: dict[str, str] = {}
        for filho in elemento:
            nome = _sem_namespace(filho.tag)
            if nome == "link":
                campos.setdefault("link", filho.get("href") or (filho.text or "").strip())
            elif nome in ("title", "description", "summary", "content", "pubDate", "published", "updated"):
                campos.setdefault(nome, filho.text or "")
        titulo = _texto_limpo(campos.get("title"))
        url = (campos.get("link") or "").strip()
        if titulo and url.startswith(("http://", "https://")):
            itens.append({
                "titulo": titulo, "url": url,
                "descricao": _texto_limpo(campos.get("description") or campos.get("summary") or campos.get("content"))[:1500] or None,
                "data_publicacao": _data_iso(campos.get("pubDate") or campos.get("published") or campos.get("updated")),
            })
    return itens


def parece_oportunidade(item: dict) -> bool:
    texto = unicodedata.normalize("NFD", f"{item['titulo']} {item.get('descricao') or ''}".lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return bool(_PADRAO_OPORTUNIDADE.search(texto))


def coletar_fonte(conexao: sqlite3.Connection, fonte_id: int, fetcher: Fetcher | None = None) -> dict:
    """Consulta UMA fonte cadastrada. Só fontes de Editais com feed geram registros; as demais
    apenas registram a consulta e dizem por que nada foi coletado."""
    from processamento import editais

    fonte = obter(conexao, fonte_id)
    if fonte is None:
        raise ValueError(f"Fonte {fonte_id} não existe.")
    fetcher = fetcher or buscar_http
    resumo = {"fonte": fonte["nome"], "encontrados": 0, "relevantes": 0, "novos": 0, "ja_existentes": 0, "mensagem": ""}

    texto = ""
    try:
        status, tipo_conteudo, texto = fetcher(fonte["url"])
        avaliacao = _classificar_resposta(status, tipo_conteudo, texto)
    except Exception as exc:
        avaliacao = {"metodo_acesso": ACESSO_INACESSIVEL, "http_status": None, "detalhe": f"{type(exc).__name__}: {str(exc)[:160]}"}
    registrar_avaliacao(conexao, fonte_id, avaliacao)
    metodo = avaliacao["metodo_acesso"]

    if metodo != ACESSO_FEED:
        resumo["mensagem"] = f"Não coletada automaticamente: {ROTULOS_ACESSO[metodo]}. {avaliacao.get('detalhe') or ''}".strip()
    elif fonte["tipo"] != "Editais":
        resumo["mensagem"] = "Feed acessível, mas só fontes do tipo Editais alimentam o Radar de Editais por enquanto."
    else:
        try:
            itens = interpretar_feed(texto)
        except (ET.ParseError, ValueError) as exc:
            itens = []
            resumo["mensagem"] = f"Feed ilegível: {exc}"
        resumo["encontrados"] = len(itens)
        relevantes = [i for i in itens if parece_oportunidade(i)]
        resumo["relevantes"] = len(relevantes)
        existentes = {l["url"] for l in conexao.execute("SELECT url FROM editais WHERE url IS NOT NULL")}
        for item in relevantes:
            if item["url"] in existentes:
                resumo["ja_existentes"] += 1
                continue
            editais.criar_edital(conexao, {
                "titulo": item["titulo"], "url": item["url"], "descricao": item["descricao"],
                "data_publicacao": item["data_publicacao"], "fonte": f"Fonte cadastrada: {fonte['nome']} ({fonte['url']})",
                "origem_descoberta": ORIGEM_FONTE_CADASTRADA, "situacao_inscricao": "NAO_CONFIRMADO",
            })
            existentes.add(item["url"])
            resumo["novos"] += 1
        if not resumo["mensagem"]:  # (já preenchida = feed ilegível)
            resumo["mensagem"] = (
                f"{resumo['encontrados']} item(ns) no feed, {resumo['relevantes']} com cara de edital/chamada, "
                f"{resumo['novos']} novo(s) cadastrado(s) como NÃO CONFIRMADO (o feed não traz prazo verificável)."
            )

    agora = _agora()
    conexao.execute(
        "UPDATE fontes_dados SET ultima_consulta = ?, proxima_consulta = ?, ultimo_resultado = ?, atualizado_em = ? WHERE id = ?",
        (agora.isoformat(), proxima_consulta(fonte["frequencia"], agora), resumo["mensagem"], agora.isoformat(), fonte_id),
    )
    conexao.commit()
    return resumo


def coletar_devidas(conexao: sqlite3.Connection, fetcher: Fetcher | None = None) -> list[dict]:
    """Roda todas as fontes ativas cuja consulta está vencida (usado pela linha de comando)."""
    resultados = []
    for fonte in devidas(conexao):
        try:
            resultados.append(coletar_fonte(conexao, fonte["id"], fetcher))
        except Exception as exc:  # uma fonte ruim não derruba as outras
            resultados.append({"fonte": fonte["nome"], "mensagem": f"Erro: {type(exc).__name__}: {str(exc)[:160]}"})
    return resultados
