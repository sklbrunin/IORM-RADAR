"""Importa achados de pesquisa de enriquecimento (presença digital,
contatos institucionais, evidências) para o banco.

IMPORTANTE: este script NÃO acessa a internet. Ele só valida, normaliza
e grava achados que já foram pesquisados anteriormente (por um agente/
pessoa usando ferramentas de busca fora deste código) e estão descritos
num arquivo JSON. Isso existe porque este ambiente não tem uma API de
busca configurada que um script Python possa chamar sozinho — ver
docs/decisoes.md para a explicação completa.

Formato esperado do arquivo JSON de entrada: uma lista de objetos, um por
empresa pesquisada:

[
  {
    "empresa_id": 7676,
    "razao_social": "Aguetoni Transportes Ltda.",   (só para conferência humana)
    "status_pesquisa": "SUCESSO" | "PARCIAL" | "FALHA",
    "observacoes": "texto livre, opcional",
    "presenca_digital": [
      {"tipo": "site", "url": "...", "fonte": "...", "nivel_confianca": "ALTO"}
    ],
    "contatos": [
      {"nome": null, "cargo": null, "departamento": null, "tipo_contato": "EMAIL_INSTITUCIONAL",
       "valor": "contato@empresa.com.br", "fonte": "...", "url_fonte": "...", "nivel_confianca": "ALTO"}
    ],
    "evidencias": [
      {"categoria": "SUSTENTABILIDADE", "descricao": "...", "url": "...", "fonte": "...", "nivel_confianca": "ALTO"}
    ]
  }
]

Como rodar:
    python coleta/importar_enriquecimento.py dados/pesquisa_enriquecimento/lote1.json
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ_PROJETO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ_PROJETO))

from processamento import banco, enriquecimento  # noqa: E402

CAMINHO_DB = RAIZ_PROJETO / "dados" / "iorm_radar.db"
PASTA_BACKUPS = RAIZ_PROJETO / "dados" / "backups"

TIPOS_CONTATO_CANAL = {
    "EMAIL_INSTITUCIONAL",
    "EMAIL_COMERCIAL",
    "EMAIL_CONTATO",
    "TELEFONE_INSTITUCIONAL",
    "TELEFONE_COMERCIAL",
    "WHATSAPP_INSTITUCIONAL",
    "FORMULARIO_CONTATO",
}
TIPO_CONTATO_PESSOA = "PESSOA_CARGO"
TIPOS_CONTATO_VALIDOS = TIPOS_CONTATO_CANAL | {TIPO_CONTATO_PESSOA}

TIPOS_EMAIL = {"EMAIL_INSTITUCIONAL", "EMAIL_COMERCIAL", "EMAIL_CONTATO"}
TIPOS_TELEFONE = {"TELEFONE_INSTITUCIONAL", "TELEFONE_COMERCIAL", "WHATSAPP_INSTITUCIONAL"}


def fazer_backup() -> Path:
    PASTA_BACKUPS.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    destino = PASTA_BACKUPS / f"iorm_radar_{timestamp}.db"
    shutil.copy2(CAMINHO_DB, destino)
    return destino


# Tipos que agentes de pesquisa às vezes usam mas que não fazem parte do
# vocabulário fixo (ver processamento/enriquecimento.py) — mapeados para
# o mais próximo em vez de descartar a informação inteira.
_MAPA_TIPO_PRESENCA_DIGITAL = {
    "diretorio_empresarial": "outro",
    "diretorio_associacao": "outro",
    "site_nao_confirmado": "site",
}


def _validar_presenca_digital(bruto: dict, empresa_id: int, agora: str) -> dict | None:
    tipo_bruto = (bruto.get("tipo") or "").strip().lower()
    tipo_bruto = _MAPA_TIPO_PRESENCA_DIGITAL.get(tipo_bruto, tipo_bruto)
    try:
        tipo = enriquecimento.validar_tipo_presenca_digital(tipo_bruto)
    except ValueError:
        tipo = "outro"  # tipo desconhecido do agente, mas o dado em si pode ser real
    url = enriquecimento.normalizar_url(bruto.get("url"))
    if not url:
        return None
    nivel = enriquecimento.validar_nivel_confianca(bruto.get("nivel_confianca", "NAO_CONFIRMADO"))
    return {
        "empresa_id": empresa_id,
        "tipo": tipo,
        "url": url,
        "fonte": bruto.get("fonte") or "não informado",
        "coletado_em": agora,
        "nivel_confianca": nivel,
    }


def _validar_contato(bruto: dict, empresa_id: int, agora: str) -> dict | None:
    tipo_contato = (bruto.get("tipo_contato") or "").strip().upper()
    if tipo_contato not in TIPOS_CONTATO_VALIDOS:
        return None

    valor_bruto = bruto.get("valor")
    if tipo_contato in TIPOS_EMAIL:
        valor = enriquecimento.normalizar_email(valor_bruto)
    elif tipo_contato in TIPOS_TELEFONE:
        valor = enriquecimento.normalizar_telefone(valor_bruto)
    elif tipo_contato == "FORMULARIO_CONTATO":
        valor = enriquecimento.normalizar_url(valor_bruto)
    else:  # PESSOA_CARGO -> valor é uma URL pública de referência (ex: LinkedIn) quando existir
        valor = enriquecimento.normalizar_url(valor_bruto)
        if not valor and valor_bruto:
            valor = str(valor_bruto).strip() or None
        if not valor:
            # Sem URL/valor específico, mas com nome público e cargo — ainda vale registrar o
            # contato profissional (ex: "Fulano, Gerente de Sustentabilidade, citado no site X").
            # Usa o nome como parte da chave de deduplicação para não colidir com outras pessoas.
            nome_normalizado = enriquecimento.normalizar_nome_pessoa(bruto.get("nome"))
            if nome_normalizado:
                valor = f"referencia-publica:{nome_normalizado.lower()}"

    if not valor:
        return None

    nivel = enriquecimento.validar_nivel_confianca(bruto.get("nivel_confianca", "NAO_CONFIRMADO"))
    cargo = bruto.get("cargo")
    prioridade = enriquecimento.classificar_prioridade(cargo or bruto.get("departamento"))

    return {
        "empresa_id": empresa_id,
        "nome": enriquecimento.normalizar_nome_pessoa(bruto.get("nome")),
        "cargo": cargo,
        "departamento": bruto.get("departamento"),
        "tipo_contato": tipo_contato,
        "valor": valor,
        "prioridade": prioridade,
        "fonte": bruto.get("fonte") or "não informado",
        "url_fonte": enriquecimento.normalizar_url(bruto.get("url_fonte")),
        "coletado_em": agora,
        "nivel_confianca": nivel,
    }


def _validar_evidencia(bruto: dict, empresa_id: int, agora: str) -> dict | None:
    try:
        categoria = enriquecimento.validar_categoria_evidencia(bruto.get("categoria", ""))
    except ValueError:
        categoria = "OUTRO"
    descricao = (bruto.get("descricao") or "").strip()
    if not descricao:
        return None
    nivel = enriquecimento.validar_nivel_confianca(bruto.get("nivel_confianca", "NAO_CONFIRMADO"))
    return {
        "empresa_id": empresa_id,
        "categoria": categoria,
        "descricao": descricao,
        "url": enriquecimento.normalizar_url(bruto.get("url")),
        "fonte": bruto.get("fonte") or "não informado",
        "coletado_em": agora,
        "nivel_confianca": nivel,
    }


def importar_empresa(conexao, item: dict) -> dict:
    empresa_id = item["empresa_id"]
    agora = datetime.now(timezone.utc).isoformat()

    linha_empresa = conexao.execute("SELECT id FROM empresas WHERE id = ?", (empresa_id,)).fetchone()
    if not linha_empresa:
        return {"empresa_id": empresa_id, "status": "FALHA", "erro": "empresa_id não existe no banco"}

    fontes_unicas = set()
    contagens = {"presenca_digital": 0, "contatos": 0, "evidencias": 0}
    itens_com_erro = 0

    for bruto in item.get("presenca_digital", []):
        try:
            dados = _validar_presenca_digital(bruto, empresa_id, agora)
        except Exception:
            itens_com_erro += 1
            continue
        if dados:
            banco.inserir_ou_atualizar_presenca_digital(conexao, dados)
            contagens["presenca_digital"] += 1
            fontes_unicas.add(dados["fonte"])

    for bruto in item.get("contatos", []):
        try:
            dados = _validar_contato(bruto, empresa_id, agora)
        except Exception:
            itens_com_erro += 1
            continue
        if dados:
            banco.inserir_ou_atualizar_contato(conexao, dados)
            contagens["contatos"] += 1
            fontes_unicas.add(dados["fonte"])

    for bruto in item.get("evidencias", []):
        try:
            dados = _validar_evidencia(bruto, empresa_id, agora)
        except Exception:
            itens_com_erro += 1
            continue
        if dados:
            banco.inserir_ou_atualizar_evidencia(conexao, dados)
            contagens["evidencias"] += 1
            fontes_unicas.add(dados["fonte"])

    status = item.get("status_pesquisa", "PARCIAL")
    if status not in ("SUCESSO", "PARCIAL", "FALHA"):
        status = "PARCIAL"

    observacoes = item.get("observacoes")
    if itens_com_erro:
        aviso = f"{itens_com_erro} item(ns) descartado(s) por formato inesperado durante a importação."
        observacoes = f"{observacoes} | {aviso}" if observacoes else aviso

    banco.registrar_pesquisa(
        conexao,
        {
            "empresa_id": empresa_id,
            "executado_em": agora,
            "quantidade_fontes": len(fontes_unicas),
            "quantidade_contatos": contagens["contatos"],
            "quantidade_redes": contagens["presenca_digital"],
            "quantidade_evidencias": contagens["evidencias"],
            "status": status,
            "observacoes": observacoes,
        },
    )

    return {"empresa_id": empresa_id, "status": status, "itens_com_erro": itens_com_erro, **contagens}


def importar_lote(conexao, lote: list[dict]) -> list[dict]:
    resultados = []
    for item in lote:
        resultado = importar_empresa(conexao, item)
        resultados.append(resultado)
        conexao.commit()
    return resultados


def main():
    parser = argparse.ArgumentParser(description="Importa achados de pesquisa de enriquecimento para o banco.")
    parser.add_argument("arquivo_json", help="Caminho do arquivo JSON com os achados (ver docstring deste arquivo).")
    args = parser.parse_args()

    caminho_backup = fazer_backup()
    print(f"Backup criado em: {caminho_backup}")

    lote = json.loads(Path(args.arquivo_json).read_text(encoding="utf-8"))
    print(f"Importando {len(lote)} empresa(s) de {args.arquivo_json}...\n")

    conexao = banco.conectar(CAMINHO_DB)
    banco.criar_tabelas_enriquecimento(conexao)
    resultados = importar_lote(conexao, lote)
    conexao.close()

    sucesso = sum(1 for r in resultados if r["status"] == "SUCESSO")
    parcial = sum(1 for r in resultados if r["status"] == "PARCIAL")
    falha = sum(1 for r in resultados if r["status"] == "FALHA")

    print(f"Concluído: {sucesso} sucesso, {parcial} parcial, {falha} falha.")
    for r in resultados:
        print(" -", r)


if __name__ == "__main__":
    main()
