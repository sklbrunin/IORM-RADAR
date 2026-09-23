"""Busca automática de editais/oportunidades — usa o mesmo SearchProvider
já validado para contatos (processamento/busca_providers.py), agora
apontado para fontes de financiamento em vez de canais de empresa.

Princípios (iguais aos do resto do sistema):
  - Nunca inventa um edital: cada candidato vem literalmente de um
    resultado de busca real (título/URL/trecho), nunca de texto gerado.
  - Nunca afirma "aberto" sem confirmação: todo candidato nasce NAO_CONFIRMADO.
    Se o trecho traz um prazo explícito ("inscrições até dd/mm/aaaa"), ele vira uma
    SUGESTÃO (com o trecho literal) para a equipe confirmar.
  - Prioriza fontes públicas/oficiais: as consultas usam `site:` para
    focar em governo (.gov.br) e nos dois catálogos de editais para OSCs
    já pesquisados nesta base (Mapa das OSC/IPEA e Prosas — ver
    docs/decisoes.md item 7.4).
  - Não salva nada sozinho: devolve uma lista de CANDIDATOS (dicts) para
    a tela mostrar com a nota de aderência já calculada; só vira um
    registro em `editais` quando alguém decide "Importar" — evita poluir
    a base com resultados de busca genéricos e de baixa relevância."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from processamento import busca_providers, editais, links_editais

_TERMOS_OPORTUNIDADE = '("edital" OR "chamada pública" OR "chamada de projetos" OR "seleção pública")'

# Cada consulta é restrita (site:) a uma fonte real já mapeada neste projeto
# como relevante para descoberta de editais (ver docs/decisoes.md, item 7.4)
# — evita devolver resultado genérico de blog/notícia sem relação real com
# uma oportunidade de financiamento.
_FONTES_BUSCA = [
    "site:gov.br",
    "site:mapaosc.ipea.gov.br",
    "site:prosas.com.br",
]

_REGEX_DATA_BR = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_REGEX_DATA_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


def _extrair_data(texto: str) -> str | None:
    """Só reconhece datas já escritas literalmente no texto (dd/mm/aaaa ou
    aaaa-mm-dd) — nunca infere uma data a partir de texto vago como
    "próximo mês"."""
    m = _REGEX_DATA_ISO.search(texto)
    if m:
        return m.group(0)
    m = _REGEX_DATA_BR.search(texto)
    if m:
        dia, mes, ano = m.groups()
        try:
            return datetime(int(ano), int(mes), int(dia)).date().isoformat()
        except ValueError:
            return None
    return None


def montar_consultas(perfil_osc: dict, max_consultas: int = 6) -> list[str]:
    """Monta consultas combinando território e temas da OSC (Cérebro da
    OSC) com cada fonte confiável — nunca inventa termo de busca fora do
    que já está cadastrado."""
    temas = perfil_osc.get("temas") or []
    cidades = perfil_osc.get("cidades") or []
    estados = perfil_osc.get("estados") or []

    localizacao = estados[0] if estados else (cidades[0] if cidades else "")
    termos_tema = " OR ".join(f'"{t}"' for t in temas[:4]) if temas else ""
    bloco_tema = f"({termos_tema})" if termos_tema else ""

    consultas = []
    for fonte in _FONTES_BUSCA:
        partes = [_TERMOS_OPORTUNIDADE, bloco_tema, localizacao, fonte]
        consultas.append(" ".join(p for p in partes if p))
    return consultas[:max_consultas]


def buscar_editais(perfil_osc: dict, provider: busca_providers.SearchProvider | None = None,
                    num_resultados_por_consulta: int = 5) -> dict:
    """Executa a busca real e devolve candidatos (nunca salva sozinho).

    Retorno: {"status": "OK"|"SEM_PROVIDER", "provider": nome, "candidatos": [...],
    "erros": [...]}. Cada candidato já vem com dados suficientes para
    `editais.calcular_aderencia()` ser chamado por quem exibe a tela."""
    provider = provider or busca_providers.obter_provider_ativo()
    if isinstance(provider, busca_providers.FilaManualProvider):
        return {"status": "SEM_PROVIDER", "provider": provider.nome, "candidatos": [], "erros": []}

    agora = datetime.now(timezone.utc).isoformat()
    consultas = montar_consultas(perfil_osc)
    candidatos = []
    urls_vistas: set[str] = set()
    erros: list[str] = []

    for consulta in consultas:
        resultados = provider.buscar(consulta, num_resultados=num_resultados_por_consulta)
        if provider.ultimo_erro:
            erros.append(provider.ultimo_erro)
            continue
        for resultado in resultados:
            url = (resultado.url or "").strip()
            if not url or url in urls_vistas:
                continue
            urls_vistas.add(url)

            texto = f"{resultado.titulo}. {resultado.trecho or ''}"
            # Data solta no trecho NÃO é prazo (pode ser data de publicação). Só uma data que vem logo
            # depois de "inscrições até"/"prazo"/"encerra" é guardada — como SUGESTÃO com o trecho
            # literal; o edital só vira "aberto" quando a equipe confirma (editais.confirmar_prazo).
            prazo = links_editais.extrair_prazo(texto)
            situacao = "NAO_CONFIRMADO"

            generico, motivo_generico = links_editais.eh_portal_generico(url)
            candidatos.append(
                {
                    "titulo": resultado.titulo,
                    "descricao": resultado.trecho or None,
                    "texto_resumo": resultado.trecho or None,
                    "url": url,
                    # Só vira link de inscrição se a própria URL indica inscrição — nunca o mesmo link
                    # do edital "por padrão" e nunca um portal genérico.
                    "url_inscricao": url if links_editais.classificar_url_inscricao(url) else None,
                    "link_generico_provavel": generico,
                    "link_generico_motivo": motivo_generico if generico else None,
                    "fonte": f"Busca automática ({provider.nome}) — {url.split('/')[2] if '://' in url else url}",
                    "data_encerramento": None,
                    "prazo_sugerido": prazo[0] if prazo else None,
                    "prazo_sugerido_trecho": prazo[1] if prazo else None,
                    # A busca não sabe o território do edital: deixar vazio ("Não identificado na fonte"). Copiar as
                    # cidades da OSC aqui fabricaria uma compatibilidade territorial que ninguém verificou.
                    "territorio": None,
                    "publico": None,
                    "requisitos": None,
                    "valor_texto": None,
                    "valor_numerico": None,
                    "tipo": "OUTRO",
                    "status": "ENCONTRADO",
                    "situacao_inscricao": situacao,
                    "origem_descoberta": "AUTOMATICA",
                    "coletado_em": agora,
                }
            )

    # Páginas específicas primeiro; portais genéricos (provável lista/página inicial) por último.
    candidatos.sort(key=lambda c: c["link_generico_provavel"])
    return {"status": "OK", "provider": provider.nome, "candidatos": candidatos, "erros": erros}


# =====================================================================================================
# v8 — PIPELINE PERSISTENTE: busca → normaliza → valida → deduplica → PERSISTE → situação → exibição
#
# Antes desta versão os resultados ficavam só em st.session_state: trocar de aba perdia a lista e cada clique
# gastava 3 chamadas da SerpApi (3 consultas × 5 resultados = no máximo 15 resultados, sem paginação).
# Agora: (1) cada chamada real à API é gravada em `busca_editais_cache` e reaproveitada por CACHE_DIAS dias;
# (2) cada resultado que parece edital vira registro em `editais`; (3) só a ação "Atualizar busca" (forcar=True)
# refaz chamadas; (4) há consultas por município e por fonte, com paginação, sob um teto configurável.
# =====================================================================================================
import hashlib
import inspect
import json
import os
import unicodedata
from datetime import timedelta
from urllib.parse import urlparse

CACHE_DIAS = int(os.environ.get("BUSCA_EDITAIS_CACHE_DIAS", "7"))
MAX_CONSULTAS_PADRAO = int(os.environ.get("BUSCA_EDITAIS_MAX_CONSULTAS", "12"))
RESULTADOS_POR_PAGINA = 10  # o Google entrega no máximo 10 por página; mais que isso exige paginar (start)
MAX_VERIFICACOES_PADRAO = 25  # páginas de edital abertas (HTTP, sem custo de API) por atualização

_PADRAO_EDITAL = re.compile(
    r"\b(edital|editais|chamamento|chamada publica|chamada de projetos|chamada aberta|fomento|"
    r"selecao publica|credenciamento|premiacao|premio|inscricoes abertas|abre inscricoes)\b"
)


def _sem_acento(texto) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", str(texto or "").lower()) if unicodedata.category(c) != "Mn")


def canonicalizar_url(url: str | None) -> str:
    """Forma comparável de uma URL: sem esquema, sem "www.", sem barra final, sem fragmento e sem parâmetros
    de rastreio (utm_*, fbclid…). Serve só para deduplicar; a URL original é a que fica gravada."""
    if not url:
        return ""
    partes = urlparse(url.strip())
    host = partes.netloc.lower().removeprefix("www.")
    consulta = "&".join(
        f"{k}={v}" for k, v in sorted(_pares_de_consulta(partes.query)) if not k.lower().startswith(("utm_", "fbclid", "gclid"))
    )
    caminho = partes.path.rstrip("/")
    return f"{host}{caminho}" + (f"?{consulta}" if consulta else "")


def _pares_de_consulta(consulta: str):
    from urllib.parse import parse_qsl

    return parse_qsl(consulta, keep_blank_values=True)


def detectar_municipios(texto: str, municipios: list[str]) -> list[str]:
    """Municípios (da lista da OSC) citados no texto. Ignora acento/caixa/hífens e reconhece a variante do
    endereço em que a letra acentuada foi simplesmente omitida (ex.: "miguel-polis" para Miguelópolis)."""
    alvo = re.sub(r"[^a-z0-9]", "", _sem_acento(texto))
    alvo_omitindo = re.sub(r"[^a-z0-9]", "", "".join(c for c in str(texto or "").lower() if ord(c) < 128))
    achados = []
    for municipio in municipios:
        variante_sem_acento = re.sub(r"[^a-z0-9]", "", _sem_acento(municipio))
        variante_omitindo = re.sub(r"[^a-z0-9]", "", "".join(c for c in municipio.lower() if ord(c) < 128))
        if len(variante_sem_acento) >= 4 and (variante_sem_acento in alvo or variante_omitindo in alvo_omitindo):
            achados.append(municipio)
    return achados


def _dominio_da_fonte(url: str) -> tuple[str, str] | None:
    """(rótulo, filtro site:) de uma fonte cadastrada. Prosas → site:prosas.com.br/editais."""
    host = urlparse(url).netloc.lower().removeprefix("www.")
    if not host:
        return None
    if host.endswith("prosas.com.br"):
        return ("prosas.com.br", "site:prosas.com.br/editais")
    return (host, f"site:{host}")


def montar_plano_de_busca(perfil_osc: dict, fontes_extra: list[dict] | None = None, ano: int | None = None,
                          max_consultas: int = MAX_CONSULTAS_PADRAO) -> list[dict]:
    """Consultas em ordem de prioridade, todas derivadas do que já está no Cérebro da OSC (municípios, temas,
    estado) e das fontes cadastradas — nada fixo por município. Cada item: {consulta, fonte, municipio, prioridade}.
      0  município × Prosas (site:prosas.com.br/editais <município> <ano>) — o que fez falta no caso de Miguelópolis
      1  município × gov.br (prefeituras/secretarias)
      2  consulta geral por fonte (temas + estado)
      3  fontes cadastradas pela equipe (além das já cobertas)"""
    ano = ano or editais.hoje_brasil().year
    municipios = [c for c in (perfil_osc.get("cidades") or []) if c]
    estados = perfil_osc.get("estados") or []
    temas = perfil_osc.get("temas") or []
    localizacao = estados[0] if estados else ""
    bloco_tema = "(" + " OR ".join(f'"{t}"' for t in temas[:4]) + ")" if temas else ""

    plano: list[dict] = []
    for municipio in municipios:
        plano.append({"consulta": f"site:prosas.com.br/editais {municipio} {ano}", "fonte": "prosas.com.br",
                      "municipio": municipio, "prioridade": 0})
    for municipio in municipios:
        plano.append({"consulta": f'{_TERMOS_OPORTUNIDADE} "{municipio}" {ano} site:gov.br', "fonte": "gov.br",
                      "municipio": municipio, "prioridade": 1})
    for filtro, rotulo in (("site:prosas.com.br/editais", "prosas.com.br"), ("site:gov.br", "gov.br"),
                           ("site:mapaosc.ipea.gov.br", "mapaosc.ipea.gov.br")):
        partes = [_TERMOS_OPORTUNIDADE, bloco_tema, localizacao, str(ano), filtro]
        plano.append({"consulta": " ".join(p for p in partes if p), "fonte": rotulo, "municipio": None, "prioridade": 2})
    cobertos = {"prosas.com.br", "gov.br", "mapaosc.ipea.gov.br"}
    for fonte in fontes_extra or []:
        item = _dominio_da_fonte(fonte.get("url") or "")
        if item is None or item[0] in cobertos:
            continue
        cobertos.add(item[0])
        partes = [_TERMOS_OPORTUNIDADE, bloco_tema, localizacao, str(ano), item[1]]
        plano.append({"consulta": " ".join(p for p in partes if p), "fonte": item[0], "municipio": None, "prioridade": 3})

    plano.sort(key=lambda p: p["prioridade"])  # estável: mantém a ordem dos municípios dentro de cada prioridade
    return plano[:max_consultas]


def _chamar_provider(provider, consulta: str, num: int, inicio: int, recencia: str | None):
    """Chama `provider.buscar` passando só os parâmetros que ele suporta (provedores antigos/falsos não têm
    `inicio`/`recencia`)."""
    parametros = inspect.signature(provider.buscar).parameters
    kwargs = {"num_resultados": num}
    if "inicio" in parametros and inicio:
        kwargs["inicio"] = inicio
    if "recencia" in parametros and recencia:
        kwargs["recencia"] = recencia
    return provider.buscar(consulta, **kwargs)


def _chave_cache(provider_nome: str, consulta: str, inicio: int, num: int, recencia: str | None) -> str:
    bruto = json.dumps([provider_nome, consulta, inicio, num, recencia], ensure_ascii=False)
    return hashlib.sha1(bruto.encode("utf-8")).hexdigest()


def _ler_cache(conexao, chave: str, agora: datetime) -> dict | None:
    linha = conexao.execute("SELECT * FROM busca_editais_cache WHERE chave = ?", (chave,)).fetchone()
    if linha is None or datetime.fromisoformat(linha["expira_em"]) <= agora:
        return None
    return {"resultados": json.loads(linha["resultados_json"]), "executada_em": linha["executada_em"]}


def _gravar_cache(conexao, chave: str, provider_nome: str, item: dict, inicio: int, num: int, recencia: str | None,
                  resultados: list, agora: datetime, dias: int) -> None:
    conexao.execute(
        """INSERT INTO busca_editais_cache (chave, provider, consulta, fonte_alvo, municipio, inicio, parametros,
                                            executada_em, expira_em, n_resultados, resultados_json, chamadas_api)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
           ON CONFLICT(chave) DO UPDATE SET executada_em = excluded.executada_em, expira_em = excluded.expira_em,
                n_resultados = excluded.n_resultados, resultados_json = excluded.resultados_json,
                chamadas_api = busca_editais_cache.chamadas_api + 1""",
        (chave, provider_nome, item["consulta"], item.get("fonte"), item.get("municipio"), inicio,
         json.dumps({"num": num, "recencia": recencia}), agora.isoformat(), (agora + timedelta(days=dias)).isoformat(),
         len(resultados), json.dumps(resultados, ensure_ascii=False)),
    )
    conexao.commit()


def _titulo_limpo(titulo: str) -> str:
    titulo = re.sub(r"^\s*Prosas\s*\|\s*Edital\s*-\s*", "", titulo or "", flags=re.I)
    titulo = re.sub(r"\s*[-|–]\s*Prosas\s*$", "", titulo, flags=re.I)
    return " ".join(titulo.split())


# Editais que não são oportunidade de financiamento para uma OSC (concursos, licitações, seleção de alunos…).
_PADRAO_OUTRO_TIPO = re.compile(
    r"\b(concurso publico|concurso|processo seletivo|licitacao|pregao|vestibular|residencia|monitoria|bolsa de estudo|"
    r"matricula|aprovados|convocacao|retificacao|dispensa de licitacao|tomada de precos|cadastro de reserva|"
    r"professor|docente|efetivo|enade|prouni|estagio|estagiario|mestrado|doutorado|graduacao|ensino superior)\b"
)
_UFS = ("ac|al|am|ap|ba|ce|df|es|go|ma|mg|ms|mt|pa|pb|pe|pi|pr|rj|rn|ro|rr|rs|sc|se|sp|to")
_PADRAO_HOST_UF = re.compile(rf"(?:^|\.)({_UFS})\.gov\.br$")


# Universidades e institutos federais/estaduais (seleção de alunos e servidores, não financiamento para OSC).
_PADRAO_HOST_UNIVERSIDADE = re.compile(r"(?:^|\.)(?:uf[a-z]{1,6}|if[a-z]{2,6}|uema|uerj|ueg|uepg|uel|uem|unesp|unicamp|usp)\.br$")


def uf_do_dominio(host: str) -> str | None:
    """UF de um domínio estadual/municipal (`guaira.pr.gov.br` → PR). Domínio federal/.edu/.org → None."""
    m = _PADRAO_HOST_UF.search((host or "").lower())
    return m.group(1).upper() if m else None


def avaliar_resultado(resultado: dict, estados: list[str] | None = None) -> tuple[bool, str]:
    """Um resultado de busca vira registro de edital? Devolve (aceito, motivo). Recusa: portal/lista genérica,
    perfil de outra OSC (Mapa das OSC), domínio de OUTRO estado (ex.: Guaíra/PR), edital que não é oportunidade
    para OSC (concurso, licitação, seleção de alunos) e o que não tem cara de edital/chamada."""
    url = resultado.get("url") or ""
    partes = urlparse(url)
    caminho = partes.path.lower()
    if not url.startswith(("http://", "https://")):
        return False, "url_invalida"
    host = partes.netloc.lower().removeprefix("www.")
    if host.endswith(".edu.br") or _PADRAO_HOST_UNIVERSIDADE.search(host):
        return False, "outro_tipo_de_edital"  # universidades/institutos federais: seleção de alunos/servidores
    if host.endswith("prosas.com.br") and caminho.rstrip("/") in ("/editais", "") or re.match(r"^\s*(portal|listagem|central|lista)\b", _sem_acento(resultado.get("titulo") or "")):
        return False, "portal_generico"
    uf = uf_do_dominio(partes.netloc)
    ufs_osc = {e.strip().upper() for e in (estados or []) if e and len(e.strip()) == 2}
    if uf and ufs_osc and uf not in ufs_osc:
        return False, "outra_uf"
    if _PADRAO_OUTRO_TIPO.search(_sem_acento(f"{resultado.get('titulo') or ''} {caminho}")):
        return False, "outro_tipo_de_edital"
    if "/detalhar/" in caminho and "mapaosc" in partes.netloc.lower():
        return False, "perfil_de_osc"
    generico, _ = links_editais.eh_portal_generico(url)
    if generico:
        return False, "portal_generico"
    eh_pagina_prosas = partes.netloc.lower().endswith("prosas.com.br") and re.match(r"^/editais/\d+", caminho)
    texto = _sem_acento(f"{resultado.get('titulo') or ''} {caminho}")
    if eh_pagina_prosas or _PADRAO_EDITAL.search(texto):
        return True, "ok"
    return False, "nao_parece_edital"


def persistir_candidatos(conexao, resultados: list[dict], perfil_osc: dict, agora: datetime | None = None) -> dict:
    """Grava em `editais` cada resultado aceito (origem AUTOMATICA, NÃO CONFIRMADO até prova em contrário).
    Deduplica pela URL canônica contra o banco INTEIRO e dentro do próprio lote. Devolve contadores + ids novos."""
    agora = agora or datetime.now(timezone.utc)
    existentes = {editais_url: eid for eid, editais_url in
                  ((l["id"], canonicalizar_url(l["url"])) for l in conexao.execute("SELECT id, url FROM editais WHERE url IS NOT NULL"))}
    municipios = [c for c in (perfil_osc.get("cidades") or []) if c]
    resumo = {"novos": 0, "ja_existentes": 0, "descartados": {}, "ids_novos": [], "por_municipio": {}, "por_fonte": {}}
    for r in resultados:
        aceito, motivo = avaliar_resultado(r, perfil_osc.get("estados"))
        if not aceito:
            resumo["descartados"][motivo] = resumo["descartados"].get(motivo, 0) + 1
            continue
        chave = canonicalizar_url(r["url"])
        if chave in existentes:
            resumo["ja_existentes"] += 1
            continue
        titulo = _titulo_limpo(r.get("titulo"))
        trecho = r.get("trecho") or None
        base_texto = f"{titulo} {urlparse(r['url']).path}"
        detectados = detectar_municipios(base_texto, municipios) or detectar_municipios(trecho or "", municipios)
        prazo = links_editais.extrair_prazo(f"{titulo}. {trecho or ''}")
        host = urlparse(r["url"]).netloc.lower().removeprefix("www.")
        estado = (perfil_osc.get("estados") or [""])[0]
        edital_id = editais.criar_edital(conexao, {
            "titulo": titulo or r["url"], "descricao": trecho, "texto_resumo": trecho, "url": r["url"],
            "url_inscricao": r["url"] if links_editais.classificar_url_inscricao(r["url"]) else None,
            "fonte": f"Busca automática ({r.get('provider') or 'SerpApi'}) — {host}",
            "territorio": (", ".join(detectados) + (f" ({estado})" if estado else "")) if detectados else None,
            "tipo": "EDITAL" if "edital" in _sem_acento(titulo) else "OUTRO", "status": "ENCONTRADO",
            "situacao_inscricao": "NAO_CONFIRMADO", "origem_descoberta": "AUTOMATICA", "coletado_em": agora.isoformat(),
            "prazo_sugerido": prazo[0] if prazo else None, "prazo_sugerido_trecho": prazo[1] if prazo else None,
        })
        conexao.execute("UPDATE editais SET municipios_detectados = ?, consulta_origem = ? WHERE id = ?",
                        (", ".join(detectados) or None, r.get("consulta"), edital_id))
        conexao.commit()
        existentes[chave] = edital_id
        resumo["novos"] += 1
        resumo["ids_novos"].append(edital_id)
        resumo["por_fonte"][host] = resumo["por_fonte"].get(host, 0) + 1
        for m in detectados:
            resumo["por_municipio"][m] = resumo["por_municipio"].get(m, 0) + 1
    return resumo


def _orcamento_restante(conexao, provider_nome: str) -> int | None:
    """Chamadas ainda permitidas neste mês (limite mensal − uso). None = sem teto (provedor não medido).
    A reserva manual NÃO é descontada: esta é uma ação manual da equipe (a rotina automática é quem respeita a reserva)."""
    if provider_nome != "SerpApi":
        return None
    from processamento import fila_enriquecimento

    limite, _ = fila_enriquecimento.limites_serpapi()
    return max(0, limite - fila_enriquecimento.uso_mes(conexao, "SerpApi"))


def _registrar_chamada(conexao, provider_nome: str, n: int = 1) -> None:
    if provider_nome != "SerpApi":
        return
    from processamento import fila_enriquecimento

    fila_enriquecimento.registrar_uso(conexao, "SerpApi", n)


def executar_busca(conexao, perfil_osc: dict, provider, *, forcar: bool = False, max_consultas: int | None = None,
                   paginas: int = 1, recencia: str | None = "y", fontes_extra: list[dict] | None = None,
                   verificar: bool = True, max_verificacoes: int = MAX_VERIFICACOES_PADRAO, buscador=None,
                   agora: datetime | None = None, cache_dias: int | None = None) -> dict:
    """Busca de editais com cache persistente e persistência dos resultados. Não depende da tela.

    forcar=False: consulta já feita e ainda válida no cache NÃO chama a API (usa o que está salvo).
    forcar=True ("Atualizar busca"): refaz as chamadas (respeitando o limite mensal).
    Devolve o relatório (também gravado em `busca_editais_execucoes`)."""
    agora = agora or datetime.now(timezone.utc)
    dias = CACHE_DIAS if cache_dias is None else cache_dias
    plano = montar_plano_de_busca(perfil_osc, fontes_extra, max_consultas=max_consultas or MAX_CONSULTAS_PADRAO)
    relatorio = {
        "provider": provider.nome, "forcada": forcar, "consultas_planejadas": len(plano), "paginas_por_consulta": paginas,
        "chamadas_api": 0, "consultas_do_cache": 0, "resultados_brutos": 0, "resultados_unicos": 0, "erros": [],
        "orcamento_esgotado": False, "por_consulta": [], "novos": 0, "ja_existentes": 0, "descartados": {},
        "por_municipio": {}, "por_fonte": {}, "novos_por_situacao": {}, "verificados": 0, "iniciada_em": agora.isoformat(),
    }
    if not provider.disponivel() or provider.nome.startswith("Fila manual"):
        relatorio["erros"].append("Nenhum provedor de busca configurado (SERPAPI_API_KEY ausente).")
        return _fechar_execucao(conexao, relatorio, forcar, agora)

    coletados: list[dict] = []
    for item in plano:
        for pagina in range(paginas):
            inicio = pagina * RESULTADOS_POR_PAGINA
            chave = _chave_cache(provider.nome, item["consulta"], inicio, RESULTADOS_POR_PAGINA, recencia)
            em_cache = None if forcar else _ler_cache(conexao, chave, agora)
            if em_cache is not None:
                resultados = em_cache["resultados"]
                relatorio["consultas_do_cache"] += 1
                origem = "cache"
            else:
                restante = _orcamento_restante(conexao, provider.nome)
                if restante is not None and restante <= 0:
                    relatorio["orcamento_esgotado"] = True
                    relatorio["erros"].append("Limite mensal de chamadas da SerpApi atingido: busca interrompida.")
                    break
                brutos = _chamar_provider(provider, item["consulta"], RESULTADOS_POR_PAGINA, inicio, recencia)
                _registrar_chamada(conexao, provider.nome)
                relatorio["chamadas_api"] += 1
                if provider.ultimo_erro:
                    relatorio["erros"].append(provider.ultimo_erro)
                    break  # erro do provedor: não insiste (não queima cota) e não grava cache de erro
                resultados = [{"titulo": r.titulo, "url": r.url, "trecho": r.trecho} for r in brutos]
                _gravar_cache(conexao, chave, provider.nome, item, inicio, RESULTADOS_POR_PAGINA, recencia, resultados, agora, dias)
                origem = "api"
            relatorio["resultados_brutos"] += len(resultados)
            relatorio["por_consulta"].append({"consulta": item["consulta"], "pagina": pagina + 1, "origem": origem,
                                              "resultados": len(resultados), "municipio": item.get("municipio")})
            coletados += [{**r, "consulta": item["consulta"], "provider": provider.nome} for r in resultados]
            if len(resultados) < RESULTADOS_POR_PAGINA:
                break  # última página desta consulta
        if relatorio["orcamento_esgotado"] or relatorio["erros"] and any("SerpApi" in e for e in relatorio["erros"]):
            break

    unicos = {}
    for r in coletados:
        unicos.setdefault(canonicalizar_url(r["url"]), r)
    relatorio["resultados_unicos"] = len(unicos)

    persistidos = persistir_candidatos(conexao, list(unicos.values()), perfil_osc, agora)
    for chave in ("novos", "ja_existentes", "descartados", "por_municipio", "por_fonte"):
        relatorio[chave] = persistidos[chave]

    if verificar:
        for edital_id in persistidos["ids_novos"][:max_verificacoes]:
            try:
                editais.verificar_e_registrar(conexao, edital_id, buscador)
                relatorio["verificados"] += 1
            except Exception as exc:  # uma página fora do ar não derruba a atualização
                relatorio["erros"].append(f"Verificação do edital {edital_id}: {type(exc).__name__}")
    for edital_id in persistidos["ids_novos"]:
        linha = conexao.execute("SELECT * FROM editais WHERE id = ?", (edital_id,)).fetchone()
        situacao = editais.situacao_efetiva(linha)[0]
        relatorio["novos_por_situacao"][situacao] = relatorio["novos_por_situacao"].get(situacao, 0) + 1
    return _fechar_execucao(conexao, relatorio, forcar, agora)


def _fechar_execucao(conexao, relatorio: dict, forcada: bool, agora: datetime) -> dict:
    conexao.execute("INSERT INTO busca_editais_execucoes (iniciada_em, forcada, relatorio_json) VALUES (?, ?, ?)",
                    (agora.isoformat(), int(forcada), json.dumps(relatorio, ensure_ascii=False)))
    conexao.commit()
    return relatorio


def ultima_execucao(conexao) -> dict | None:
    linha = conexao.execute("SELECT * FROM busca_editais_execucoes ORDER BY id DESC LIMIT 1").fetchone()
    return json.loads(linha["relatorio_json"]) if linha else None


def situacao_do_cache(conexao, agora: datetime | None = None) -> dict:
    """Quantas consultas têm resultado válido salvo e desde quando — a tela usa para dizer que vai reutilizar."""
    agora = agora or datetime.now(timezone.utc)
    linha = conexao.execute(
        "SELECT COUNT(*) AS n, MAX(executada_em) AS ultima FROM busca_editais_cache WHERE expira_em > ?", (agora.isoformat(),)
    ).fetchone()
    return {"consultas_validas": linha["n"], "ultima_chamada": linha["ultima"]}


def cadastrar_por_url(conexao, url: str, perfil_osc: dict | None = None, buscador=None) -> dict:
    """Cadastra um edital a partir do LINK (ex.: o que a equipe recebeu por e-mail/WhatsApp). Abre a página como
    uma pessoa abriria (uma requisição), lê título e dados estruturados, salva e verifica. Não depende de o
    buscador ter indexado a página — foi o que faltou no caso do edital de Miguelópolis, publicado no dia.
    Devolve {id, novo, titulo, situacao, motivo}. Levanta ValueError com mensagem clara se não der."""
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")) or " " in url:
        raise ValueError("Informe o endereço completo do edital, começando com http:// ou https://.")
    perfil_osc = perfil_osc or {}
    chave = canonicalizar_url(url)
    for linha in conexao.execute("SELECT id, url FROM editais WHERE url IS NOT NULL"):
        if canonicalizar_url(linha["url"]) == chave:
            editais.verificar_e_registrar(conexao, linha["id"], buscador)  # já existe: só atualiza a verificação
            atual = conexao.execute("SELECT * FROM editais WHERE id = ?", (linha["id"],)).fetchone()
            situacao, motivo = editais.situacao_efetiva(atual)
            return {"id": linha["id"], "novo": False, "titulo": atual["titulo"], "situacao": situacao, "motivo": motivo}
    buscador = buscador or links_editais._buscar_pagina
    try:
        status, url_final, pagina = buscador(url)
    except Exception as exc:
        raise ValueError(f"Não foi possível abrir a página ({type(exc).__name__}).") from exc
    if status >= 400:
        raise ValueError(f"A página respondeu HTTP {status}: confira o endereço.")
    dados = links_editais.extrair_dados_estruturados(pagina, url_final or url) or {}
    titulo = _titulo_limpo(dados.get("nome") or links_editais.titulo_da_pagina(pagina) or "")
    if not titulo:
        raise ValueError("A página não tem título legível: cadastre o edital manualmente.")
    municipios = [c for c in (perfil_osc.get("cidades") or []) if c]
    detectados = detectar_municipios(f"{titulo} {urlparse(url).path}", municipios)
    estado = (perfil_osc.get("estados") or [""])[0]
    edital_id = editais.criar_edital(conexao, {
        "titulo": titulo, "url": url, "fonte": "Cadastro por link (informado pela equipe)", "tipo": "EDITAL" if "edital" in _sem_acento(titulo) else "OUTRO",
        "territorio": (", ".join(detectados) + (f" ({estado})" if estado else "")) if detectados else None,
        "situacao_inscricao": "NAO_CONFIRMADO", "origem_descoberta": "MANUAL",
    })
    conexao.execute("UPDATE editais SET municipios_detectados = ? WHERE id = ?", (", ".join(detectados) or None, edital_id))
    conexao.commit()
    editais.verificar_e_registrar(conexao, edital_id, buscador)
    atual = conexao.execute("SELECT * FROM editais WHERE id = ?", (edital_id,)).fetchone()
    situacao, motivo = editais.situacao_efetiva(atual)
    return {"id": edital_id, "novo": True, "titulo": titulo, "situacao": situacao, "motivo": motivo}
