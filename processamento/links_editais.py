"""Verificação de links de editais — separa "página do edital" de "link de
inscrição" e nunca aceita portal genérico como se fosse nenhum dos dois.

Regras (ver docs/decisoes.md):
  - Uma URL só é "página específica do edital" se responder (HTTP < 400),
    não parecer portal/lista genérica e o título do edital aparecer na
    página. Sem isso, o status diz exatamente o que aconteceu.
  - "Link de inscrição" só existe se (a) a própria URL indica inscrição
    (ex: /inscricao, formulário externo) ou (b) a página do edital tem um
    link cujo texto é "Inscreva-se/Inscrições" apontando para outro
    endereço específico. Nunca inventado, nunca o portal da instituição.
  - Sem isso: "Link direto de inscrição não localizado".
A verificação é heurística — por isso cada resultado guarda o motivo e a
data, e a tela deixa claro quando é só "provável"."""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Callable
from urllib.parse import urljoin, urlparse

import requests

USER_AGENT = "IORMRadar/1.0 (verificacao de links de editais; contato institucional do IORM)"
LIMITE_BYTES = 400_000

STATUS_ESPECIFICA = "PAGINA_ESPECIFICA_CONFIRMADA"
STATUS_SEM_CORRESPONDENCIA = "RESPONDE_SEM_CORRESPONDENCIA"
STATUS_GENERICO = "PORTAL_GENERICO"
STATUS_NAO_RESPONDE = "NAO_RESPONDE"
STATUS_NAO_VERIFICADO = "NAO_VERIFICADO"

ROTULOS_STATUS = {
    STATUS_ESPECIFICA: "Página específica do edital confirmada",
    STATUS_SEM_CORRESPONDENCIA: "Link responde, mas o título do edital não foi encontrado na página",
    STATUS_GENERICO: "Parece portal/lista genérica — não é a página do edital",
    STATUS_NAO_RESPONDE: "Link não responde",
    STATUS_NAO_VERIFICADO: "Link ainda não verificado",
}

_SEGMENTOS_GENERICOS = {
    "editais", "edital", "chamadas", "chamada", "oportunidades", "noticias", "novidades", "home", "index",
    "inicio", "portal", "servicos", "programas", "projetos", "transparencia", "concursos", "licitacoes",
    "inscricao", "inscricoes", "inscreva-se",  # "/inscricoes" sozinho não diz de qual edital é
}
_HOSTS_FORMULARIO = ("forms.gle", "docs.google.com/forms", "forms.office.com", "typeform.com", "airtable.com/shr")
_PADRAO_TEXTO_INSCRICAO = re.compile(r"inscre(va|ver)[- ]?se|inscri(c|ç)(a|ã)o|inscri(c|ç)(o|õ)es|candidate-se", re.I)
_FRASES_ENCERRADO = re.compile(
    r"inscri(c|ç)(o|õ)es\s+(est(a|ã)o\s+)?encerradas|edital\s+encerrado|prazo\s+(de\s+inscri(c|ç)(a|ã)o\s+)?encerrado",
    re.I,
)


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")


def eh_portal_generico(url: str | None) -> tuple[bool, str]:
    """Heurística sem rede: raiz do domínio ou caminho curto só com palavras
    genéricas (ex: /editais, /noticias) e sem identificador. Devolve (bool, motivo)."""
    if not url:
        return True, "sem URL"
    partes = urlparse(url.strip())
    if partes.scheme not in ("http", "https") or not partes.netloc:
        return True, "URL inválida"
    segmentos = [s for s in partes.path.split("/") if s]
    if not segmentos:
        return True, "endereço da raiz do site (página inicial)"
    if len(segmentos) == 1 and _sem_acento(segmentos[0]).rsplit(".", 1)[0] in _SEGMENTOS_GENERICOS and not partes.query:
        return True, f"lista genérica “/{segmentos[0]}” sem identificar um edital"
    return False, "endereço com caminho específico"


def classificar_url_inscricao(url: str | None) -> bool:
    """True se a própria URL indica inscrição (formulário externo ou caminho com 'inscri')."""
    if not url:
        return False
    baixa = url.lower()
    if any(h in baixa for h in _HOSTS_FORMULARIO):
        return True
    return bool(re.search(r"inscri|inscreva|candidat", urlparse(baixa).path)) and not eh_portal_generico(url)[0]


class _ExtratorLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self._href: str | None = None
        self._texto: list[str] = []
        self.links: list[tuple[str, str]] = []
        self.titulo = ""
        self._em_titulo = False
        self.texto_pagina: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._texto = []
        elif tag == "title":
            self._em_titulo = True

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join(self._texto).strip()))
            self._href = None
        elif tag == "title":
            self._em_titulo = False

    def handle_data(self, data):
        if self._em_titulo:
            self.titulo += data
        if self._href is not None:
            self._texto.append(data.strip())
        self.texto_pagina.append(data)


def extrair_link_inscricao(html: str, url_base: str) -> str | None:
    """Procura na página do edital um link cujo TEXTO seja de inscrição e
    cujo destino seja um endereço específico (não a própria página, nem
    âncora, nem portal genérico). Devolve a URL absoluta ou None."""
    extrator = _ExtratorLinks()
    try:
        extrator.feed(html)
    except Exception:
        return None
    for href, texto in extrator.links:
        if not href or href.startswith(("#", "mailto:", "javascript:", "tel:")):
            continue
        absoluto = urljoin(url_base, href)
        if not (_PADRAO_TEXTO_INSCRICAO.search(texto) or classificar_url_inscricao(absoluto)):
            continue
        if absoluto.rstrip("/") == url_base.rstrip("/") or eh_portal_generico(absoluto)[0]:
            continue
        return absoluto
    return None


def _palavras_significativas(titulo: str) -> list[str]:
    ignorar = {"edital", "chamada", "publica", "publico", "para", "com", "dos", "das", "de", "do", "da", "em",
               "no", "na", "por", "ao", "aos", "seu", "sua", "que", "uma", "num"}
    return [p for p in re.findall(r"[a-z0-9]{3,}", _sem_acento(titulo)) if p not in ignorar]


def correspondencia_titulo(titulo: str, titulo_pagina: str, texto_pagina: str) -> float:
    """Fração (0–1) das palavras significativas do título do edital que
    aparecem no título/texto da página. Sem palavras significativas -> 0."""
    palavras = _palavras_significativas(titulo)
    if not palavras:
        return 0.0
    alvo = _sem_acento(f"{titulo_pagina} {texto_pagina}")
    return sum(1 for p in palavras if p in alvo) / len(palavras)


def _buscar_pagina(url: str) -> tuple[int, str, str]:
    resposta = requests.get(url, timeout=15, headers={"User-Agent": USER_AGENT}, allow_redirects=True, stream=True)
    conteudo = next(resposta.iter_content(LIMITE_BYTES), b"")
    codificacao = resposta.encoding or resposta.apparent_encoding or "utf-8"
    try:
        html = conteudo.decode(codificacao, errors="replace")
    except LookupError:
        html = conteudo.decode("utf-8", errors="replace")
    return resposta.status_code, resposta.url, html


def verificar_link(url: str | None, titulo: str,
                   buscador: Callable[[str], tuple[int, str, str]] | None = None) -> dict:
    """Verifica UMA página de edital. `buscador(url) -> (status, url_final, html)`
    é injetável para teste. Nunca lança exceção: falha vira STATUS_NAO_RESPONDE."""
    buscador = buscador or _buscar_pagina
    resultado = {
        "status": STATUS_NAO_VERIFICADO, "http_status": None, "url_final": None, "correspondencia": None,
        "motivo": "", "url_inscricao_encontrada": None, "indicio_encerrado": False, "verificado_em": _agora(),
    }
    if not url:
        resultado["status"], resultado["motivo"] = STATUS_NAO_RESPONDE, "Edital sem URL cadastrada."
        return resultado
    try:
        status_http, url_final, html = buscador(url)
    except Exception as exc:
        resultado["status"], resultado["motivo"] = STATUS_NAO_RESPONDE, f"Falha ao acessar: {type(exc).__name__}"
        return resultado

    resultado["http_status"], resultado["url_final"] = status_http, url_final
    if status_http >= 400:
        resultado["status"], resultado["motivo"] = STATUS_NAO_RESPONDE, f"O servidor respondeu HTTP {status_http}."
        return resultado

    generico, motivo_generico = eh_portal_generico(url_final or url)
    extrator = _ExtratorLinks()
    try:
        extrator.feed(html)
    except Exception:
        pass
    texto = " ".join(extrator.texto_pagina)
    resultado["correspondencia"] = round(correspondencia_titulo(titulo, extrator.titulo, texto), 2)
    resultado["indicio_encerrado"] = bool(_FRASES_ENCERRADO.search(texto))
    resultado["url_inscricao_encontrada"] = extrair_link_inscricao(html, url_final or url)

    if generico:
        resultado["status"], resultado["motivo"] = STATUS_GENERICO, motivo_generico
    elif resultado["correspondencia"] >= 0.5:
        resultado["status"] = STATUS_ESPECIFICA
        resultado["motivo"] = (
            f"Responde (HTTP {status_http}) e {int(resultado['correspondencia'] * 100)}% das palavras do título aparecem na página."
        )
    else:
        resultado["status"] = STATUS_SEM_CORRESPONDENCIA
        resultado["motivo"] = (
            f"Responde (HTTP {status_http}), mas só {int(resultado['correspondencia'] * 100)}% das palavras do título aparecem na página."
        )
    return resultado


def verificar_inscricao(url_inscricao: str | None,
                         buscador: Callable[[str], tuple[int, str, str]] | None = None) -> dict:
    """Confirma só que o link de inscrição responde e não é portal genérico."""
    buscador = buscador or _buscar_pagina
    if not url_inscricao:
        return {"ok": False, "motivo": "Link direto de inscrição não localizado"}
    if eh_portal_generico(url_inscricao)[0]:
        return {"ok": False, "motivo": "O endereço de inscrição parece um portal genérico"}
    try:
        status_http, _, _ = buscador(url_inscricao)
    except Exception as exc:
        return {"ok": False, "motivo": f"Não respondeu: {type(exc).__name__}"}
    if status_http >= 400:
        return {"ok": False, "motivo": f"O servidor respondeu HTTP {status_http}"}
    return {"ok": True, "motivo": f"Responde (HTTP {status_http})"}
