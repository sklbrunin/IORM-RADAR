"""Funções de validação e normalização de dados coletados.

Cada função aqui é "pura": recebe um valor e devolve um valor validado
ou None quando o dado não é confiável. Nada aqui inventa informação —
quando não dá pra confirmar algo, a resposta é None (não um chute).
"""
from __future__ import annotations

import re

UFS_VALIDAS = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
    "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
    "SP", "SE", "TO",
}


def normalizar_cnpj(valor) -> str | None:
    """Remove pontuação/espacos. Devolve None se não sobrarem 14 dígitos
    (ou seja, se o valor nem tem o formato possível de um CNPJ)."""
    if not valor:
        return None
    apenas_digitos = re.sub(r"\D", "", str(valor))
    if len(apenas_digitos) != 14:
        return None
    return apenas_digitos


def validar_cnpj(cnpj: str | None) -> bool:
    """Confere os dois dígitos verificadores do CNPJ (algoritmo oficial,
    módulo 11). Isso confirma que o número é matematicamente possível —
    não confirma que a empresa existe de verdade (isso só a Receita
    Federal confirma, numa etapa futura de enriquecimento)."""
    if not cnpj or not re.fullmatch(r"\d{14}", cnpj):
        return False
    if cnpj == cnpj[0] * 14:  # sequências tipo 00000000000000 não são válidas
        return False

    pesos = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]

    def calcular_digito(base: str) -> int:
        soma = sum(int(digito) * peso for digito, peso in zip(base, pesos[-len(base):]))
        resto = soma % 11
        return 0 if resto < 2 else 11 - resto

    digito1 = calcular_digito(cnpj[:12])
    digito2 = calcular_digito(cnpj[:12] + str(digito1))
    return cnpj[-2:] == f"{digito1}{digito2}"


def validar_uf(uf) -> str | None:
    if not uf:
        return None
    uf_maiuscula = str(uf).strip().upper()
    return uf_maiuscula if uf_maiuscula in UFS_VALIDAS else None


def validar_ano(ano, ano_minimo: int = 1990, ano_maximo: int = 2100) -> int | None:
    try:
        ano_int = int(ano)
    except (TypeError, ValueError):
        return None
    return ano_int if ano_minimo <= ano_int <= ano_maximo else None


def validar_valor(valor) -> float | None:
    try:
        valor_float = float(valor)
    except (TypeError, ValueError):
        return None
    return valor_float if valor_float >= 0 else None


def validar_url(url) -> str | None:
    if not url:
        return None
    url = str(url).strip()
    return url if url.startswith("http://") or url.startswith("https://") else None
