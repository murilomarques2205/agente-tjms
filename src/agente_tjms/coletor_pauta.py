"""Coletor de pauta — sessões e processos dos órgãos monitorados.

Para cada órgão em ORGAOS_MONITORADOS:
  1. GET /sessao-agendada (público) → todas as sessões agendadas.
  2. Filtra dtPauta na janela [agora - dias_atras, agora] em UTC.
  3. Para cada sessão, baixa processos paginados via /processos-em-pauta.
  4. Upsert em sessao + processo_pautado (idempotente).
  5. Loga métricas em execucao.

Tolerâncias propositais: o shape exato de processos-em-pauta e os nomes
de campos individuais ainda não foram observados (endpoint protegido).
Helpers `_extrair_lista` e `_get_field` aceitam variações conhecidas.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

from dateutil.parser import isoparse

from .client import PAGINACAO_TAMANHO, TJMSClient
from .config import ORGAOS_MONITORADOS
from .db import (
    get_conn,
    log_execucao_fim,
    log_execucao_inicio,
    upsert_processo_pautado,
    upsert_sessao,
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="coletor_pauta",
        description="Coleta sessões e processos pautados dos órgãos monitorados.",
    )
    p.add_argument(
        "--dias-atras", type=int, default=7,
        help="Janela em dias contando para trás a partir de agora (default: 7).",
    )
    p.add_argument(
        "--orgao", type=int, default=None,
        help="cdOrgaoJulgador único a coletar (default: todos os monitorados).",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Não grava em DB; apenas lista o que seria coletado.",
    )
    p.add_argument(
        "--com-processos",
        action="store_true",
        help=(
            "Tentar coletar processos por sessão (endpoint protegido por CAS). "
            "Desabilitado por padrão até implementarmos autenticação."
        ),
    )
    return p.parse_args(argv)


def _extrair_lista(payload: Any) -> list[dict[str, Any]]:
    """Extrai a lista de processos do payload paginado, tolerando shapes diferentes."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("lista", "processos", "items"):
            if isinstance(payload.get(key), list):
                return payload[key]
    raise ValueError(f"shape inesperado em processos-em-pauta: {type(payload).__name__}")


def _get_field(d: dict[str, Any], *candidates: str) -> Any:
    for k in candidates:
        if k in d:
            return d[k]
    return None


def _coletar_orgao(
    client: TJMSClient,
    conn: sqlite3.Connection,
    *,
    cd_foro: int,
    cd_orgao_julgador: int,
    inicio_utc: datetime,
    fim_utc: datetime,
    dry_run: bool,
    com_processos: bool = False,
) -> dict[str, int]:
    """Coleta sessões+processos de um órgão. Retorna {'sessoes': int, 'processos': int}."""
    sessoes_brutas, _ = client.get_sessoes_agendadas(
        cd_foro=cd_foro, cd_orgao_julgador=cd_orgao_julgador
    )
    sessoes_filtradas = [
        s for s in sessoes_brutas
        if inicio_utc <= isoparse(s["dtPauta"]) <= fim_utc
    ]
    n_sessoes = len(sessoes_filtradas)
    n_processos = 0

    for s in sessoes_filtradas:
        sessao_id: int | None = None
        if not dry_run:
            sessao_id = upsert_sessao(
                conn,
                nu_sessao=s["nuSessao"],
                nu_seq_sessao=s["nuSeqSessao"],
                cd_orgao_julgador=cd_orgao_julgador,
                dt_pauta_utc=s["dtPauta"],
            )

        if not com_processos:
            continue  # escopo B: só metadados de sessão (endpoint de processos requer CAS)

        pagina = 0
        while True:
            payload, _ = client.get_processos_em_pauta(
                cd_orgao_julgador=cd_orgao_julgador,
                nu_sessao=s["nuSessao"],
                nu_seq_sessao=s["nuSeqSessao"],
                pagina=pagina,
            )
            lista = _extrair_lista(payload)
            if not lista:
                break

            for p in lista:
                n_processos += 1
                if dry_run:
                    continue
                assert sessao_id is not None  # garantido: dry_run guarda o upsert acima
                upsert_processo_pautado(
                    conn,
                    sessao_id=sessao_id,
                    codigo_processo=str(_get_field(p, "codigoProcesso", "cdProcesso")),
                    numero_unificado=_get_field(
                        p, "numeroProcessoUnificado", "numeroUnificado", "numero"
                    ),
                    classe=_get_field(p, "classe", "nmClasse", "deClasse"),
                    relator=_get_field(p, "relator", "nmRelator", "desRelator"),
                    partes_json=json.dumps(
                        _get_field(p, "partes", "partesProcesso") or [],
                        ensure_ascii=False,
                    ),
                    ordem_pauta=_get_field(p, "ordemPauta", "ordem", "nuOrdem"),
                    raw_json=json.dumps(p, ensure_ascii=False),
                )

            if len(lista) < PAGINACAO_TAMANHO:
                break
            pagina += 1

    return {"sessoes": n_sessoes, "processos": n_processos}


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    fim_utc = datetime.now(tz=timezone.utc)
    inicio_utc = fim_utc - timedelta(days=args.dias_atras)

    if args.orgao is not None:
        orgaos = [o for o in ORGAOS_MONITORADOS if o["cdOrgaoJulgador"] == args.orgao]
        if not orgaos:
            print(
                f"ERRO: --orgao {args.orgao} não está em ORGAOS_MONITORADOS",
                file=sys.stderr,
            )
            return 2
    else:
        orgaos = list(ORGAOS_MONITORADOS)

    print(f"janela UTC: {inicio_utc.isoformat()} → {fim_utc.isoformat()}")
    print(f"órgãos:     {len(orgaos)}{' (dry-run)' if args.dry_run else ''}")
    print()

    conn = get_conn()
    execucao_id = None if args.dry_run else log_execucao_inicio(conn, "coletor_pauta")

    metricas_por_orgao: dict[int, dict[str, Any]] = {}
    erros: list[str] = []

    try:
        with TJMSClient() as client:
            for o in orgaos:
                cd_oj = o["cdOrgaoJulgador"]
                nome = o["nmOrgaoJulgador"]
                try:
                    if args.dry_run:
                        m = _coletar_orgao(
                            client, conn,
                            cd_foro=o["cdForo"], cd_orgao_julgador=cd_oj,
                            inicio_utc=inicio_utc, fim_utc=fim_utc,
                            dry_run=True,
                            com_processos=args.com_processos,
                        )
                    else:
                        with conn:  # transação por órgão
                            m = _coletar_orgao(
                                client, conn,
                                cd_foro=o["cdForo"], cd_orgao_julgador=cd_oj,
                                inicio_utc=inicio_utc, fim_utc=fim_utc,
                                dry_run=False,
                                com_processos=args.com_processos,
                            )
                    metricas_por_orgao[cd_oj] = m
                    print(
                        f"  cdOJ={cd_oj:>3}  {nome}: "
                        f"sessões={m['sessoes']}, processos={m['processos']}"
                    )
                except Exception as e:
                    erros.append(f"cdOJ={cd_oj} ({nome}): {e}")
                    metricas_por_orgao[cd_oj] = {"sessoes": 0, "processos": 0, "erro": str(e)}
                    print(
                        f"  cdOJ={cd_oj:>3}  {nome}: ERRO — {e}",
                        file=sys.stderr,
                    )

        total_sessoes = sum(m.get("sessoes", 0) for m in metricas_por_orgao.values())
        total_processos = sum(m.get("processos", 0) for m in metricas_por_orgao.values())
        any_sucesso = any("erro" not in m for m in metricas_por_orgao.values())
        if not erros:
            status = "ok"
        elif any_sucesso:
            status = "parcial"
        else:
            status = "erro"

        print()
        print(f"RESUMO: status={status}  sessões={total_sessoes}  processos={total_processos}")

        if not args.dry_run and execucao_id is not None:
            log_execucao_fim(
                conn, execucao_id,
                status=status,
                mensagem=("; ".join(erros) if erros else None),
                metricas={
                    "janela_inicio_utc": inicio_utc.isoformat(),
                    "janela_fim_utc": fim_utc.isoformat(),
                    "total_sessoes": total_sessoes,
                    "total_processos": total_processos,
                    "por_orgao": metricas_por_orgao,
                },
            )
        return 0 if status == "ok" else 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
