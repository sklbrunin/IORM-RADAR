"""Transforma um registro bruto da API do SALIC em dados prontos para
gravar no banco (uma empresa + um incentivo).

Se faltar informação essencial (nome da empresa ou URL da fonte), o
registro é descartado — nunca inventamos dado para completar."""
from __future__ import annotations

from datetime import datetime, timezone

from processamento import validadores


def transformar_registro(bruto: dict, fonte_nome: str) -> dict | None:
    nome = (bruto.get("nome") or "").strip()
    url_fonte = validadores.validar_url((bruto.get("_links") or {}).get("self"))

    if not nome or not url_fonte:
        # Sem nome ou sem URL de origem não dá pra rastrear o dado depois,
        # então preferimos descartar a preencher com um valor inventado.
        return None

    cnpj_normalizado = validadores.normalizar_cnpj(bruto.get("cgccpf"))
    cnpj_confirmado = (
        cnpj_normalizado if cnpj_normalizado and validadores.validar_cnpj(cnpj_normalizado) else None
    )

    agora = datetime.now(timezone.utc).isoformat()
    uf = validadores.validar_uf(bruto.get("UF"))

    empresa = {
        "cnpj": cnpj_confirmado,  # None quando o SALIC não trouxe um CNPJ matematicamente válido
        "razao_social": nome,  # nome conforme informado ao SALIC — ainda não confirmado na Receita Federal
        "nome_fantasia": None,  # o SALIC não fornece esse dado
        "cidade": bruto.get("municipio") or None,
        "estado": uf,
        "status": None,  # reservado para uma futura confirmação via Receita Federal/BrasilAPI
    }

    incentivo = {
        "fonte": fonte_nome,
        "tipo_incentivo": "Lei Rouanet (incentivo federal à cultura)",
        "projeto": None,  # este endpoint só traz total agregado, não por projeto (ver README)
        "ano": None,  # mesmo motivo acima
        "valor": validadores.validar_valor(bruto.get("total_doado")),
        "uf": uf,
        "cidade": bruto.get("municipio") or None,
        "url_fonte": url_fonte,
        "coletado_em": agora,
        "nivel_confianca": "Alta (fonte oficial); valor agregado, sem detalhamento por projeto/ano nesta etapa",
    }

    return {"empresa": empresa, "incentivo": incentivo}


def transformar_doacao(bruto: dict, url_doacoes_empresa: str, fonte_nome: str) -> dict | None:
    """Transforma um registro individual de doação (endpoint /doacoes) em
    um incentivo detalhado por projeto/ano.

    Como o SALIC não expõe uma URL própria por doação individual, usamos a
    URL real do endpoint consultado + um fragmento (#pronac=...&recibo=...)
    para conseguir uma fonte única e rastreável por registro, sem inventar
    um endereço que não existe de verdade (ver docs/decisoes.md)."""
    pronac = (bruto.get("PRONAC") or "").strip()
    if not pronac:
        return None  # sem PRONAC não dá pra citar a origem de forma confiável

    data_recibo = bruto.get("data_recibo")
    ano = None
    if data_recibo:
        try:
            ano = validadores.validar_ano(int(str(data_recibo)[:4]))
        except (TypeError, ValueError):
            ano = None

    url_fonte = f"{url_doacoes_empresa}#pronac={pronac}&recibo={data_recibo or 'sem-data'}"

    return {
        "fonte": fonte_nome,
        "tipo_incentivo": "Lei Rouanet (incentivo federal à cultura) - detalhado por projeto",
        "projeto": (bruto.get("nome_projeto") or "").strip() or None,
        "ano": ano,
        "valor": validadores.validar_valor(bruto.get("valor")),
        "url_fonte": url_fonte,
        "nivel_confianca": "Alta (fonte oficial, registro individual de doação)",
    }
