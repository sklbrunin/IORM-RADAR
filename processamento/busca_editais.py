"""Busca automática de editais/oportunidades — usa o mesmo SearchProvider
já validado para contatos (processamento/busca_providers.py), agora
apontado para fontes de financiamento em vez de canais de empresa.

Princípios (iguais aos do resto do sistema):
  - Nunca inventa um edital: cada candidato vem literalmente de um
    resultado de busca real (título/URL/trecho), nunca de texto gerado.
  - Nunca afirma "aberto" sem confirmação: todo candidato nasce com
    situacao_inscricao NAO_CONFIRMADO (ver editais.classificar_situacao_inscricao)
    a menos que uma data real tenha sido encontrada no próprio texto do
    resultado.
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
            data_encontrada = _extrair_data(texto)
            situacao = editais.classificar_situacao_inscricao(None, data_encontrada)

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
                    "data_encerramento": data_encontrada,
                    "territorio": ", ".join(perfil_osc.get("cidades", [])[:4]) or None,
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
