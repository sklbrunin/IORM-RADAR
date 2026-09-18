"""Orquestra uma pesquisa de enriquecimento para uma empresa usando o
SearchProvider ativo (processamento/busca_providers.py).

Quando não há provider real disponível (fallback FilaManualProvider),
este módulo não inventa nada — devolve status "SEM_PROVIDER" e quem
chamou decide enfileirar para pesquisa manual (comportamento que já
existia antes desta arquitetura).

Resultados de busca automática são gravados com nível de confiança
MEDIO (presença digital/contato) ou BAIXO (evidências e pessoas/cargos)
— nunca ALTO, porque ninguém revisou manualmente ainda. Isso é
intencional: o operador humano decide se confirma.

As consultas são pensadas para o que um captador realmente precisa saber
("com quem eu falo, e como?"), não só "achar links": canais de contato
institucional, redes sociais oficiais, ESG/responsabilidade social,
relação fiscal/tributária com incentivos, e pessoas em cargos
publicamente identificáveis (marketing, comunicação, relações
institucionais, sustentabilidade). Nenhum dado é inventado: e-mail e
telefone só são gravados quando aparecem literalmente no texto que a
busca devolveu; pessoa+cargo só quando o próprio resultado (ex: título
de uma página do LinkedIn) já traz essa associação publicamente."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from processamento import banco, busca_providers, enriquecimento

_DOMINIOS_REDE = {
    "linkedin.com": "linkedin",
    "instagram.com": "instagram",
    "facebook.com": "facebook",
    "youtube.com": "youtube",
}

# Cada consulta é (sufixo da busca, tipo de achado, categoria de evidência
# quando aplicável). Tipo "presenca" grava em presenca_digital, "evidencia"
# grava em evidencias com a categoria indicada, "pessoa" tenta extrair
# nome+cargo só de perfis pessoais do LinkedIn (nunca vira presença da
# empresa). Todo grupo "OR" fica entre parênteses de propósito — sem
# isso, o Google espalha o "OR" pela consulta inteira e devolve lixo
# (ex: sites de prefeitura de uma cidade homônima em outro estado).
_CONSULTAS_POR_CATEGORIA: list[tuple[str, str, str | None]] = [
    ('(site oficial OR "fale conosco" OR contato)', "presenca", None),
    ('(site:linkedin.com/company OR site:instagram.com)', "presenca", None),
    ('(ESG OR sustentabilidade OR "responsabilidade social" OR "investimento social privado")', "evidencia", "ESG"),
    ('(instituto OR fundação OR fundacao)', "evidencia", "INSTITUTO"),
    ('("incentivo fiscal" OR "renúncia fiscal")', "evidencia", "FISCAL"),
    ('("Lei Rouanet" OR "patrocínio cultural")', "evidencia", "PATROCINIO"),
    (
        'site:linkedin.com/in/ (diretor OR gerente OR coordenador OR analista) '
        '(marketing OR comunicação OR "relações institucionais" OR sustentabilidade OR ESG)',
        "pessoa", None,
    ),
    (
        'site:linkedin.com/in/ (gerente OR coordenador OR analista OR diretor OR contador) '
        '(fiscal OR tributário OR contabilidade OR controladoria OR jurídico OR "recursos humanos")',
        "pessoa", None,
    ),
]

# Modo econômico (rotina diária): as 3 consultas de maior retorno para "quem procurar e como" —
# site/contato, redes oficiais e pessoas de comunicação/ESG. Economiza cota da SerpApi.
CONSULTAS_ECONOMICAS = [_CONSULTAS_POR_CATEGORIA[0], _CONSULTAS_POR_CATEGORIA[1], _CONSULTAS_POR_CATEGORIA[6]]

_TERMOS_RELEVANTES = [
    "esg", "sustentabilidade", "responsabilidade social", "instituto", "fundação", "fundacao",
    "investimento social", "patrocínio", "patrocinio", "incentivo fiscal", "renúncia fiscal",
    "renuncia fiscal", "lei rouanet", "marketing", "comunicação", "comunicacao",
    "relações institucionais", "relacoes institucionais",
]

_REGEX_EMAIL = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
# Telefone brasileiro com DDD, com ou sem separadores (ex: (17) 3331-2000 / 17 99999-0000).
_REGEX_TELEFONE = re.compile(r"\(?\b[1-9]{2}\)?[\s.-]?9?\d{4}[\s.-]?\d{4}\b")


def classificar_url(url: str) -> str:
    url_lower = url.lower()
    for dominio, tipo in _DOMINIOS_REDE.items():
        if dominio in url_lower:
            return tipo
    return "site"


def _extrair_contatos_do_texto(texto: str) -> dict[str, list[str]]:
    """Extrai e-mails/telefones que aparecem literalmente no texto (título
    + trecho) de um resultado de busca. Nunca infere — só reconhece
    padrões já presentes no texto devolvido pela API."""
    emails = sorted(set(m.lower() for m in _REGEX_EMAIL.findall(texto)))
    telefones = sorted(set(enriquecimento.normalizar_telefone(m) for m in _REGEX_TELEFONE.findall(texto) if m))
    return {"emails": [e for e in emails if enriquecimento.normalizar_email(e)], "telefones": [t for t in telefones if t]}


_PALAVRAS_SOCIETARIAS = {
    "ltda", "ltda.", "s.a.", "sa", "s/a", "eireli", "me", "epp", "comercio", "comércio",
    "industria", "indústria", "agricola", "agrícola", "servicos", "serviços", "transportes",
    "e", "de", "do", "da", "dos", "das", "em",
}


def _texto_menciona_empresa(nome: str, texto: str) -> bool:
    """A busca por palavras-chave genéricas (ESG, Lei Rouanet etc.) às
    vezes traz conteúdo que fala do ASSUNTO mas não da empresa em si
    (ex: um manual genérico sobre patrocínio cultural). Antes de gravar
    como evidência sobre a empresa, exige que pelo menos uma palavra
    própria do nome dela apareça no texto — sem isso, o resultado é
    descartado (não vira evidência "inventada" por associação)."""
    texto_lower = texto.lower()
    palavras = [p.strip(".,") for p in nome.lower().split()]
    significativas = [p for p in palavras if len(p) >= 4 and p not in _PALAVRAS_SOCIETARIAS]
    if not significativas:
        return True  # nome curto/genérico demais pra filtrar com segurança — não bloqueia
    return any(p in texto_lower for p in significativas)


def _extrair_pessoa_cargo_linkedin(titulo: str, url: str) -> tuple[str, str] | None:
    """Perfis do LinkedIn indexados normalmente têm título no formato
    "Nome - Cargo - Empresa | LinkedIn". Só extrai quando esse padrão
    literalmente aparece no título devolvido pela busca — nunca associa
    nome a cargo por conta própria."""
    if "linkedin.com/in/" not in url.lower():
        return None
    partes = [p.strip() for p in re.split(r"[-–|]", titulo) if p.strip()]
    if len(partes) < 2:
        return None
    nome, cargo = partes[0], partes[1]
    if cargo.lower() == "linkedin" or not nome or not cargo:
        return None
    return nome, cargo


def pesquisar_empresa(conexao, empresa_id: int, nome: str, cidade: str | None = None,
                       estado: str | None = None,
                       provider: busca_providers.SearchProvider | None = None,
                       consultas: list | None = None, registrar_historico: bool = True) -> dict:
    """Executa a pesquisa (se houver provider real) e grava os
    resultados. Devolve um resumo — nunca lança exceção para a UI. Se
    alguma consulta falhar (chave inválida, limite, timeout), o motivo
    fica em "erros" no retorno, para a UI mostrar uma mensagem amigável
    em vez de um "0 resultados" ambíguo."""
    provider = provider or busca_providers.obter_provider_ativo()

    if isinstance(provider, busca_providers.FilaManualProvider):
        return {
            "status": "SEM_PROVIDER", "provider": provider.nome,
            "presenca_digital": 0, "evidencias": 0, "contatos": 0, "erros": [],
        }

    agora = datetime.now(timezone.utc).isoformat()
    if cidade and estado:
        localizacao = f' "{cidade}/{estado}"'  # entre aspas: evita confundir com cidades homônimas em outro estado
    elif cidade:
        localizacao = f" {cidade}"
    else:
        localizacao = ""

    presenca_gravada = 0
    evidencias_gravadas = 0
    contatos_gravados = 0
    fontes_usadas: set[str] = set()
    erros: list[str] = []

    consultas_executadas = 0
    for sufixo_consulta, tipo_busca, categoria in (consultas or _CONSULTAS_POR_CATEGORIA):
        consulta = f'"{nome}"{localizacao} {sufixo_consulta}'
        resultados = provider.buscar(consulta, num_resultados=5)
        consultas_executadas += 1
        if provider.ultimo_erro:
            erros.append(provider.ultimo_erro)
            continue

        for resultado in resultados:
            url = enriquecimento.normalizar_url(resultado.url)
            if not url:
                continue
            texto = f"{resultado.titulo}. {resultado.trecho or ''}".strip()
            fonte = f"Busca automática ({provider.nome}) — consulta: {consulta}"
            fontes_usadas.add(provider.nome)

            # E-mail/telefone citados literalmente no resultado viram contato institucional,
            # independente da categoria da consulta que os encontrou.
            achados = _extrair_contatos_do_texto(texto)
            for email in achados["emails"]:
                _, criado = banco.inserir_ou_atualizar_contato(
                    conexao,
                    {
                        "empresa_id": empresa_id, "nome": None, "cargo": None, "departamento": enriquecimento.area_do_email(email),
                        "tipo_contato": "EMAIL_CONTATO", "valor": email, "prioridade": None,
                        "fonte": fonte, "url_fonte": url, "coletado_em": agora, "nivel_confianca": "MEDIO",
                    },
                )
                contatos_gravados += 1 if criado else 0
            for telefone in achados["telefones"]:
                _, criado = banco.inserir_ou_atualizar_contato(
                    conexao,
                    {
                        "empresa_id": empresa_id, "nome": None, "cargo": None, "departamento": None,
                        "tipo_contato": "TELEFONE_INSTITUCIONAL", "valor": telefone, "prioridade": None,
                        "fonte": fonte, "url_fonte": url, "coletado_em": agora, "nivel_confianca": "BAIXO",
                    },
                )
                contatos_gravados += 1 if criado else 0

            if tipo_busca == "presenca":
                # Defesa extra: perfil PESSOAL do LinkedIn (/in/) nunca é canal da
                # empresa, mesmo que a consulta de presença tenha retornado um por
                # engano — isso só pode virar contato via o fluxo "pessoa" abaixo,
                # e só quando o próprio título já mostrar nome+cargo.
                if "linkedin.com/in/" in url.lower():
                    continue
                # Domínio de governo (.gov.br) nunca é o canal oficial de uma empresa privada —
                # aparece às vezes por causa de nomes de cidade homônimos em outro estado.
                if ".gov.br" in url.lower():
                    continue
                banco.inserir_ou_atualizar_presenca_digital(
                    conexao,
                    {
                        "empresa_id": empresa_id, "tipo": classificar_url(url), "url": url,
                        "fonte": fonte, "coletado_em": agora, "nivel_confianca": "MEDIO",
                    },
                )
                presenca_gravada += 1

            elif tipo_busca == "pessoa":
                achado_pessoa = _extrair_pessoa_cargo_linkedin(resultado.titulo, url)
                if achado_pessoa:
                    nome_pessoa, cargo = achado_pessoa
                    prioridade = enriquecimento.classificar_prioridade(cargo)
                    _, criado = banco.inserir_ou_atualizar_contato(
                        conexao,
                        {
                            "empresa_id": empresa_id, "nome": enriquecimento.normalizar_nome_pessoa(nome_pessoa),
                            "cargo": cargo, "departamento": enriquecimento.classificar_area(cargo), "tipo_contato": "PESSOA_CARGO", "valor": url,
                            "prioridade": prioridade, "fonte": fonte, "url_fonte": url,
                            "coletado_em": agora, "nivel_confianca": "BAIXO",
                        },
                    )
                    contatos_gravados += 1 if criado else 0

            else:  # evidencia
                if not any(termo in texto.lower() for termo in _TERMOS_RELEVANTES):
                    continue
                if not _texto_menciona_empresa(nome, texto):
                    continue
                banco.inserir_ou_atualizar_evidencia(
                    conexao,
                    {
                        "empresa_id": empresa_id, "categoria": categoria or "OUTRO", "descricao": texto[:400],
                        "url": url, "fonte": fonte, "coletado_em": agora, "nivel_confianca": "BAIXO",
                    },
                )
                evidencias_gravadas += 1

    total_achados = presenca_gravada + evidencias_gravadas + contatos_gravados
    if total_achados:
        status = "SUCESSO"
    elif erros:
        status = "FALHA"
    else:
        status = "PARCIAL"
    if registrar_historico:
        banco.registrar_pesquisa(
            conexao,
            {
                "empresa_id": empresa_id,
                "executado_em": agora,
                "quantidade_fontes": len(fontes_usadas),
                "quantidade_contatos": contatos_gravados,
                "quantidade_redes": presenca_gravada,
                "quantidade_evidencias": evidencias_gravadas,
                "status": status,
                "observacoes": (
                    f"Pesquisa automática via {provider.nome}. Resultados gravados com confiança "
                    "MEDIO/BAIXO — recomenda-se revisão humana antes de usar em abordagem."
                    + (f" Falhas: {'; '.join(erros)}" if erros else "")
                ),
            },
        )
    conexao.commit()

    return {
        "status": "OK",
        "provider": provider.nome,
        "presenca_digital": presenca_gravada,
        "evidencias": evidencias_gravadas,
        "contatos": contatos_gravados,
        "erros": erros,
        "consultas_executadas": consultas_executadas,
    }
