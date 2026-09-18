"""Rotina diária de enriquecimento de empresas (meta: 30/dia).

O QUE FAZ, em ordem (cada passo é uma função testável):
  1. seleciona a fila: prospects com CNPJ confirmado, NUNCA pesquisados primeiro,
     depois falhas/parciais que já podem ser tentadas de novo;
  2. exclui empresas com relacionamento com o IORM (Linha Cruzada);
  3. ordena por Região IORM (cidade de atuação > região próxima > interesse >
     fora) e por prioridade de prospecção; se a região não tiver 30 elegíveis,
     completa com empresas de fora da região e REGISTRA isso no histórico;
  4. enriquece cada empresa com os provedores disponíveis (ver
     processamento/contact_providers.py): Receita Federal (gratuito) sempre; busca web
     (SerpApi) só enquanto houver ORÇAMENTO de cota — a cota mensal é contada aqui;
  5. grava contatos/evidências/fonte/data (via contact_providers.persistir);
  6. classifica SUCESSO / PARCIAL / FALHA e agenda nova tentativa (falha: 1 dia;
     parcial: 3 dias; no máximo 3 tentativas);
  7. registra a execução (última execução, contagens, "menos elegíveis que a meta").

LIMITES (nunca ultrapassados): meta por dia; SERPAPI_LIMITE_MENSAL (padrão 100) menos
SERPAPI_RESERVA_MANUAL (padrão 20, para o botão "Pesquisar" da ficha); pausa entre
empresas; teto de tempo por execução; para em erro 429 repetido. Uma segunda
execução no mesmo dia só completa o que faltar da meta — nunca dobra."""
from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from typing import Callable

import pandas as pd

from processamento import banco, contact_providers, pesquisa_empresa

META_PADRAO = 30
MAX_TENTATIVAS = 3
DIAS_NOVA_TENTATIVA = {"FALHA": 1, "PARCIAL": 3}
CONSULTAS_WEB_POR_EMPRESA = len(pesquisa_empresa.CONSULTAS_ECONOMICAS)
ORDEM_REGIAO = {"CIDADE_ATUACAO": 0, "REGIAO_PROXIMA": 1, "INTERESSE_ESTRATEGICO": 2, "FORA_DA_REGIAO": 3}

STATUS_SUCESSO, STATUS_PARCIAL, STATUS_FALHA = "SUCESSO", "PARCIAL", "FALHA"


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def criar_tabelas(conexao: sqlite3.Connection) -> None:
    conexao.executescript(
        """
        CREATE TABLE IF NOT EXISTS enriquecimento_execucoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            iniciado_em TEXT NOT NULL, finalizado_em TEXT, origem TEXT NOT NULL DEFAULT 'MANUAL',
            meta INTEGER NOT NULL, meta_restante INTEGER NOT NULL, elegiveis_novas INTEGER NOT NULL DEFAULT 0,
            elegiveis_retentativa INTEGER NOT NULL DEFAULT 0, processadas INTEGER NOT NULL DEFAULT 0,
            sucesso INTEGER NOT NULL DEFAULT 0, parcial INTEGER NOT NULL DEFAULT 0, falha INTEGER NOT NULL DEFAULT 0,
            dentro_da_regiao INTEGER NOT NULL DEFAULT 0, fora_da_regiao INTEGER NOT NULL DEFAULT 0,
            chamadas_serpapi INTEGER NOT NULL DEFAULT 0, chamadas_receita INTEGER NOT NULL DEFAULT 0,
            observacao TEXT, interrompida_por TEXT
        );
        CREATE TABLE IF NOT EXISTS enriquecimento_itens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            execucao_id INTEGER NOT NULL REFERENCES enriquecimento_execucoes(id),
            empresa_id INTEGER NOT NULL, status TEXT NOT NULL, tipo_fila TEXT NOT NULL,
            regiao_iorm TEXT, detalhe TEXT, contatos_novos INTEGER NOT NULL DEFAULT 0,
            evidencias_novas INTEGER NOT NULL DEFAULT 0, presencas_novas INTEGER NOT NULL DEFAULT 0,
            processado_em TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS enriquecimento_estado (
            empresa_id INTEGER PRIMARY KEY, ultimo_status TEXT NOT NULL, tentativas INTEGER NOT NULL DEFAULT 0,
            ultima_tentativa_em TEXT NOT NULL, proxima_tentativa_apos TEXT, ultimo_erro TEXT
        );
        CREATE TABLE IF NOT EXISTS uso_api (
            provedor TEXT NOT NULL, ano_mes TEXT NOT NULL, chamadas INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (provedor, ano_mes)
        );
        """
    )
    conexao.commit()


# ------------------------------------------------------------------ cota de API
def registrar_uso(conexao: sqlite3.Connection, provedor: str, chamadas: int, quando: datetime | None = None) -> None:
    if chamadas <= 0:
        return
    ano_mes = (quando or _agora()).strftime("%Y-%m")
    conexao.execute(
        """INSERT INTO uso_api (provedor, ano_mes, chamadas) VALUES (?, ?, ?)
           ON CONFLICT(provedor, ano_mes) DO UPDATE SET chamadas = chamadas + excluded.chamadas""",
        (provedor, ano_mes, chamadas),
    )
    conexao.commit()


def uso_mes(conexao: sqlite3.Connection, provedor: str, quando: datetime | None = None) -> int:
    linha = conexao.execute(
        "SELECT chamadas FROM uso_api WHERE provedor = ? AND ano_mes = ?", (provedor, (quando or _agora()).strftime("%Y-%m"))
    ).fetchone()
    return linha[0] if linha else 0


def limites_serpapi() -> tuple[int, int]:
    return int(os.environ.get("SERPAPI_LIMITE_MENSAL", "100")), int(os.environ.get("SERPAPI_RESERVA_MANUAL", "20"))


def orcamento_serpapi(conexao: sqlite3.Connection, quando: datetime | None = None) -> int:
    """Chamadas de busca web que a rotina ainda pode gastar neste mês (já
    descontada a reserva para uso manual)."""
    limite, reserva = limites_serpapi()
    return max(0, limite - reserva - uso_mes(conexao, "SerpApi", quando))


# ------------------------------------------------------------------ seleção da fila
def selecionar_fila(conexao: sqlite3.Connection, df_empresas: pd.DataFrame, meta: int,
                    incluir_fora_da_regiao: bool = True, agora: datetime | None = None) -> dict:
    """Devolve {"fila": [...], "elegiveis_novas": n, "elegiveis_retentativa": n, "motivo_menos_que_meta": str|None}."""
    agora = agora or _agora()
    criar_tabelas(conexao)
    if df_empresas.empty or meta <= 0:
        return {"fila": [], "elegiveis_novas": 0, "elegiveis_retentativa": 0, "motivo_menos_que_meta": "sem empresas"}

    ja_pesquisadas = {l[0] for l in conexao.execute("SELECT DISTINCT empresa_id FROM historico_pesquisa")}
    estados = {l["empresa_id"]: dict(l) for l in conexao.execute("SELECT * FROM enriquecimento_estado")}

    base = df_empresas[df_empresas["eh_prospect"] & df_empresas["cnpj_confirmado"]].copy()  # 1 e 2
    if not incluir_fora_da_regiao:
        base = base[base["regiao_iorm"] != "FORA_DA_REGIAO"]
    base["_ordem_regiao"] = base["regiao_iorm"].map(ORDEM_REGIAO).fillna(3)

    def _pendente_de_retentativa(eid: int) -> bool:
        e = estados.get(eid)
        if not e or e["ultimo_status"] == STATUS_SUCESSO or e["tentativas"] >= MAX_TENTATIVAS:
            return False
        return not e["proxima_tentativa_apos"] or datetime.fromisoformat(e["proxima_tentativa_apos"]) <= agora

    novas = base[~base["id"].isin(ja_pesquisadas) & ~base["id"].isin(estados.keys())]
    retentativas = base[base["id"].isin(estados.keys()) & base["id"].apply(_pendente_de_retentativa)]

    novas = novas.sort_values(["_ordem_regiao", "prioridade_prospeccao", "score", "valor_total"],
                              ascending=[True, False, False, False])
    retentativas = retentativas.assign(
        _ultima=retentativas["id"].map(lambda i: estados[i]["ultima_tentativa_em"])
    ).sort_values(["_ordem_regiao", "_ultima"])

    fila = [{**_linha(r), "tipo_fila": "NOVA"} for _, r in novas.head(meta).iterrows()]
    if len(fila) < meta:
        fila += [{**_linha(r), "tipo_fila": "RETENTATIVA"} for _, r in retentativas.head(meta - len(fila)).iterrows()]

    motivo = None
    if len(fila) < meta:
        motivo = (f"Apenas {len(fila)} empresa(s) elegível(is) para a meta de {meta}"
                  + ("" if incluir_fora_da_regiao else " (restrito à Região IORM)")
                  + f": {len(novas)} nova(s) + {len(retentativas)} para nova tentativa.")
    return {"fila": fila, "elegiveis_novas": len(novas), "elegiveis_retentativa": len(retentativas), "motivo_menos_que_meta": motivo}


def _linha(r: pd.Series) -> dict:
    return {"id": int(r["id"]), "razao_social": r["razao_social"], "cnpj": r["cnpj"], "cidade": r["cidade"],
            "estado": r["estado"], "regiao_iorm": r["regiao_iorm"]}


def processadas_hoje(conexao: sqlite3.Connection, agora: datetime | None = None) -> int:
    criar_tabelas(conexao)
    dia = (agora or _agora()).strftime("%Y-%m-%d")
    return conexao.execute(
        "SELECT COUNT(DISTINCT empresa_id) FROM enriquecimento_itens WHERE substr(processado_em, 1, 10) = ?", (dia,)
    ).fetchone()[0]


# ------------------------------------------------------------------ processar uma empresa
def processar_empresa(conexao: sqlite3.Connection, empresa: dict, providers: list[contact_providers.ContactProvider],
                      orcamento_web: int, agora: datetime | None = None) -> dict:
    """Roda os provedores, persiste e classifica. Nunca lança exceção."""
    agora = agora or _agora()
    detalhes: list[str] = []
    ok, erros_total = 0, 0
    contagem = {"contatos": 0, "evidencias": 0, "presenca_digital": 0, "cadastro": 0}
    chamadas: dict[str, int] = {}
    esperado = 0  # provedores que DEVERIAM rodar para chamar de SUCESSO
    for provider in providers:
        e_web = isinstance(provider, contact_providers.WebSearchContactProvider)
        if not provider.disponivel():
            detalhes.append(f"{provider.nome}: indisponível ({provider.credencial_env} não configurada)")
            if e_web or provider.custo != contact_providers.CUSTO_PAGO:
                esperado += 1
            continue
        esperado += 1
        if e_web and orcamento_web - chamadas.get("SerpApi", 0) < CONSULTAS_WEB_POR_EMPRESA:
            detalhes.append(f"{provider.nome}: pulada (cota mensal de busca web esgotada)")
            continue
        try:
            resultado = provider.enriquecer(
                empresa, **({"consultas": pesquisa_empresa.CONSULTAS_ECONOMICAS} if e_web else {}))
        except Exception as exc:  # defesa final: uma empresa problemática não derruba a execução
            detalhes.append(f"{provider.nome}: erro inesperado ({type(exc).__name__})")
            erros_total += 1
            continue
        chave_uso = "SerpApi" if e_web else "BrasilAPI"
        chamadas[chave_uso] = chamadas.get(chave_uso, 0) + resultado.chamadas_api
        if resultado.ignorado_motivo:
            detalhes.append(f"{provider.nome}: ignorado ({resultado.ignorado_motivo})")
            continue
        if resultado.erros:
            erros_total += 1
            detalhes.extend(resultado.erros)
            if not (resultado.contagens_diretas or resultado.contatos):
                continue
        if resultado.persistido_diretamente:
            for k, v in resultado.contagens_diretas.items():
                contagem[k] = contagem.get(k, 0) + v
        else:
            for k, v in contact_providers.persistir(conexao, empresa["id"], resultado).items():
                contagem[k] = contagem.get(k, 0) + v
        if not resultado.erros:
            ok += 1
            detalhes.append(f"{provider.nome}: ok")

    if ok == 0:
        status = STATUS_FALHA
    elif ok >= esperado and erros_total == 0:
        status = STATUS_SUCESSO
    else:
        status = STATUS_PARCIAL

    for provedor, n in chamadas.items():
        registrar_uso(conexao, provedor, n, agora)
    _atualizar_estado(conexao, empresa["id"], status, "; ".join(detalhes), agora)
    banco.registrar_pesquisa(conexao, {
        "empresa_id": empresa["id"], "executado_em": agora.isoformat(), "quantidade_fontes": ok,
        "quantidade_contatos": contagem["contatos"], "quantidade_redes": contagem["presenca_digital"],
        "quantidade_evidencias": contagem["evidencias"], "status": status,
        "observacoes": "Rotina diária de enriquecimento. " + "; ".join(detalhes),
    })
    conexao.commit()
    return {"status": status, "detalhe": "; ".join(detalhes), "contagem": contagem, "chamadas": chamadas}


def _atualizar_estado(conexao, empresa_id: int, status: str, erro: str, agora: datetime) -> None:
    anterior = conexao.execute("SELECT tentativas FROM enriquecimento_estado WHERE empresa_id = ?", (empresa_id,)).fetchone()
    tentativas = (anterior[0] if anterior else 0) + 1
    proxima = None
    if status != STATUS_SUCESSO and tentativas < MAX_TENTATIVAS:
        proxima = (agora + timedelta(days=DIAS_NOVA_TENTATIVA[status])).isoformat()
    conexao.execute(
        """INSERT INTO enriquecimento_estado (empresa_id, ultimo_status, tentativas, ultima_tentativa_em, proxima_tentativa_apos, ultimo_erro)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(empresa_id) DO UPDATE SET ultimo_status = excluded.ultimo_status, tentativas = excluded.tentativas,
             ultima_tentativa_em = excluded.ultima_tentativa_em, proxima_tentativa_apos = excluded.proxima_tentativa_apos,
             ultimo_erro = excluded.ultimo_erro""",
        (empresa_id, status, tentativas, agora.isoformat(), proxima, erro[:500] or None),
    )


# ------------------------------------------------------------------ execução completa
def executar(conexao: sqlite3.Connection, df_empresas: pd.DataFrame,
             providers: list[contact_providers.ContactProvider], meta: int = META_PADRAO,
             origem: str = "MANUAL", incluir_fora_da_regiao: bool = True, pausa_entre_empresas: float = 1.0,
             max_segundos: int = 1800, agora: Callable[[], datetime] | None = None,
             dormir: Callable[[float], None] = time.sleep) -> dict:
    relogio = agora or _agora
    criar_tabelas(conexao)
    inicio = relogio()
    ja_feitas = processadas_hoje(conexao, inicio)
    meta_restante = max(0, meta - ja_feitas)
    selecao = selecionar_fila(conexao, df_empresas, meta_restante, incluir_fora_da_regiao, inicio)
    cursor = conexao.execute(
        """INSERT INTO enriquecimento_execucoes (iniciado_em, origem, meta, meta_restante, elegiveis_novas, elegiveis_retentativa)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (inicio.isoformat(), origem, meta, meta_restante, selecao["elegiveis_novas"], selecao["elegiveis_retentativa"]),
    )
    execucao_id = cursor.lastrowid
    conexao.commit()

    orcamento = orcamento_serpapi(conexao, inicio)
    contadores = {"sucesso": 0, "parcial": 0, "falha": 0, "dentro": 0, "fora": 0, "serpapi": 0, "receita": 0}
    interrompida = None
    seguidos_429 = 0
    for empresa in selecao["fila"]:
        if (relogio() - inicio).total_seconds() > max_segundos:
            interrompida = f"teto de tempo de {max_segundos}s atingido"
            break
        res = processar_empresa(conexao, empresa, providers, orcamento - contadores["serpapi"], relogio())
        contadores[res["status"].lower()] += 1
        contadores["serpapi"] += res["chamadas"].get("SerpApi", 0)
        contadores["receita"] += res["chamadas"].get("BrasilAPI", 0)
        contadores["dentro" if empresa["regiao_iorm"] != "FORA_DA_REGIAO" else "fora"] += 1
        conexao.execute(
            """INSERT INTO enriquecimento_itens (execucao_id, empresa_id, status, tipo_fila, regiao_iorm, detalhe,
               contatos_novos, evidencias_novas, presencas_novas, processado_em) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (execucao_id, empresa["id"], res["status"], empresa["tipo_fila"], empresa["regiao_iorm"], res["detalhe"][:600],
             res["contagem"]["contatos"], res["contagem"]["evidencias"], res["contagem"]["presenca_digital"], relogio().isoformat()),
        )
        conexao.commit()
        seguidos_429 = seguidos_429 + 1 if "limite de requisições" in res["detalhe"] else 0
        if seguidos_429 >= 3:
            interrompida = "limite de requisições da BrasilAPI atingido 3 vezes seguidas"
            break
        dormir(pausa_entre_empresas)

    processadas = contadores["sucesso"] + contadores["parcial"] + contadores["falha"]
    observacao = selecao["motivo_menos_que_meta"] if not interrompida else f"Interrompida: {interrompida}."
    if meta_restante == 0:
        observacao = f"Meta do dia ({meta}) já atingida em execuções anteriores — nada a fazer."
    conexao.execute(
        """UPDATE enriquecimento_execucoes SET finalizado_em = ?, processadas = ?, sucesso = ?, parcial = ?, falha = ?,
           dentro_da_regiao = ?, fora_da_regiao = ?, chamadas_serpapi = ?, chamadas_receita = ?, observacao = ?,
           interrompida_por = ? WHERE id = ?""",
        (relogio().isoformat(), processadas, contadores["sucesso"], contadores["parcial"], contadores["falha"],
         contadores["dentro"], contadores["fora"], contadores["serpapi"], contadores["receita"], observacao, interrompida, execucao_id),
    )
    conexao.commit()
    return {"execucao_id": execucao_id, "processadas": processadas, "sucesso": contadores["sucesso"],
            "parcial": contadores["parcial"], "falha": contadores["falha"], "observacao": observacao,
            "elegiveis_novas": selecao["elegiveis_novas"], "elegiveis_retentativa": selecao["elegiveis_retentativa"],
            "chamadas_serpapi": contadores["serpapi"], "interrompida_por": interrompida,
            "dentro_da_regiao": contadores["dentro"], "fora_da_regiao": contadores["fora"]}


# ------------------------------------------------------------------ leitura para a página administrativa
def resumo_admin(conexao: sqlite3.Connection, df_empresas: pd.DataFrame, meta: int = META_PADRAO,
                 agora: datetime | None = None) -> dict:
    criar_tabelas(conexao)
    agora = agora or _agora()
    ultima = conexao.execute("SELECT * FROM enriquecimento_execucoes ORDER BY id DESC LIMIT 1").fetchone()
    dia = agora.strftime("%Y-%m-%d")
    hoje = conexao.execute(
        "SELECT status, COUNT(*) n FROM enriquecimento_itens WHERE substr(processado_em, 1, 10) = ? GROUP BY status", (dia,)
    ).fetchall()
    por_status = {l["status"]: l["n"] for l in hoje}
    total_acumulado = conexao.execute("SELECT COUNT(DISTINCT empresa_id) FROM enriquecimento_itens").fetchone()[0]
    acumulado = {l["status"]: l["n"] for l in conexao.execute(
        "SELECT ultimo_status status, COUNT(*) n FROM enriquecimento_estado GROUP BY ultimo_status")}
    prox = selecionar_fila(conexao, df_empresas, 10, True, agora)
    limite, reserva = limites_serpapi()
    return {
        "ultima_execucao": dict(ultima) if ultima else None,
        "hoje": {"processadas": sum(por_status.values()), "sucesso": por_status.get(STATUS_SUCESSO, 0),
                 "parcial": por_status.get(STATUS_PARCIAL, 0), "falha": por_status.get(STATUS_FALHA, 0)},
        "meta_dia": meta, "total_acumulado": total_acumulado, "acumulado_por_status": acumulado,
        "proximas_da_fila": prox["fila"], "elegiveis_novas": prox["elegiveis_novas"],
        "elegiveis_retentativa": prox["elegiveis_retentativa"],
        "serpapi": {"limite_mensal": limite, "reserva_manual": reserva, "usadas_no_mes": uso_mes(conexao, "SerpApi", agora),
                    "orcamento_da_rotina": orcamento_serpapi(conexao, agora)},
        "brasilapi_usadas_no_mes": uso_mes(conexao, "BrasilAPI", agora),
    }


def itens_de_hoje(conexao: sqlite3.Connection, agora: datetime | None = None) -> list[dict]:
    criar_tabelas(conexao)
    dia = (agora or _agora()).strftime("%Y-%m-%d")
    return [dict(l) for l in conexao.execute(
        """SELECT i.*, e.razao_social, e.cidade FROM enriquecimento_itens i JOIN empresas e ON e.id = i.empresa_id
           WHERE substr(i.processado_em, 1, 10) = ? ORDER BY i.id DESC""", (dia,))]
