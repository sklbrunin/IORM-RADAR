"""Formatação de valores para exibição (padrão brasileiro).

Função central usada por toda a dashboard — nenhuma tela deve formatar
moeda/CNPJ com a própria conta. Isso só afeta como o dado é MOSTRADO;
o valor numérico gravado no banco nunca é alterado por este módulo."""
from __future__ import annotations


def formatar_moeda_br(valor) -> str:
    """Formata um número como moeda brasileira: R$ 16.905.389,94

    Aceita None/NaN (mostra "Não disponível" em vez de quebrar)."""
    if valor is None:
        return "Não disponível"
    try:
        valor_float = float(valor)
    except (TypeError, ValueError):
        return "Não disponível"
    if valor_float != valor_float:  # NaN
        return "Não disponível"

    texto = f"{valor_float:,.2f}"  # ex: 16,905,389.94 (formato en-US do Python)
    texto = texto.replace(",", "_").replace(".", ",").replace("_", ".")
    return f"R$ {texto}"


def formatar_numero_br(valor) -> str:
    """Formata um número inteiro com separador de milhar brasileiro: 8.211"""
    if valor is None:
        return "Não disponível"
    try:
        valor_int = int(valor)
    except (TypeError, ValueError):
        return "Não disponível"
    return f"{valor_int:,}".replace(",", ".")


def formatar_percentual(valor, casas: int = 1) -> str:
    """Formata um número (0-100) como percentual brasileiro: 10,5%"""
    if valor is None:
        return "Não disponível"
    try:
        valor_float = float(valor)
    except (TypeError, ValueError):
        return "Não disponível"
    texto = f"{valor_float:.{casas}f}".replace(".", ",")
    return f"{texto}%"


def formatar_data_br(data_iso) -> str:
    """Formata uma data (ISO ou já um date/datetime) como dd/mm/aaaa."""
    if not data_iso:
        return "Não disponível"
    texto = str(data_iso)[:10]
    partes = texto.split("-")
    if len(partes) != 3:
        return "Não disponível"
    ano, mes, dia = partes
    if not (ano.isdigit() and mes.isdigit() and dia.isdigit()):
        return "Não disponível"
    return f"{dia}/{mes}/{ano}"


def formatar_cnpj(cnpj) -> str:
    """Formata um CNPJ de 14 dígitos: 11.444.777/0001-61"""
    if not cnpj:
        return "Não disponível"
    cnpj = str(cnpj)
    if len(cnpj) != 14 or not cnpj.isdigit():
        return "Não disponível"
    return f"{cnpj[0:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:14]}"

def formatar_nota(nota, casas: int = 1) -> str:
    """Nota 0–10 no padrão brasileiro: 8,7/10. Sem nota calculável mostra o motivo, não um zero."""
    if nota is None:
        return "Não calculável"
    try:
        valor = float(nota)
    except (TypeError, ValueError):
        return "Não calculável"
    if valor != valor:
        return "Não calculável"
    return f"{valor:.{casas}f}".replace(".", ",") + "/10"


def resumir_texto(texto, limite: int = 260) -> str:
    """Trecho para cartões: corta na última palavra inteira antes do limite e AVISA que é um trecho
    (o texto completo fica na ficha). Textos curtos voltam inteiros."""
    texto = " ".join(str(texto or "").split())
    if len(texto) <= limite:
        return texto
    corte = texto[:limite].rsplit(" ", 1)[0].rstrip(",;:—-")
    return f"{corte} (trecho — texto completo na ficha)"
