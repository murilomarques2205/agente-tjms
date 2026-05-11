"""Coletor de pauta — sessões e processos dos órgãos monitorados.

Para cada órgão em ORGAOS_MONITORADOS:
  1. GET /sessao-agendada (público) → todas as sessões agendadas.
  2. Filtra dtPauta na janela [agora - dias_atras, agora] em UTC.
  3. Para cada sessão, GET /processo-em-pauta (público) com tamanhoPagina=0,
     que retorna todos os processos da sessão em uma única resposta.
  4. Upsert em sessao + processo_pautado (idempotente).
  5. Loga métricas e avisos em execucao.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

from dateutil.parser import isoparse

from .client import TJMSClient
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
    return p.parse_args(argv)


def _montar_partes_json(p: dict[str, Any]) -> str:
    """Serializa polos ativo/passivo para a coluna partes_json.

    Cada polo vira null se deTipoPrincParte{Ativa|Passiva} estiver ausente.
    """
    def _polo(tipo_key: str, nome_key: str, nome_social_key: str) -> dict[str, Any] | None:
        tipo = p.get(tipo_key)
        if tipo is None:
            return None
        return {
            "tipo": tipo,
            "nome": p.get(nome_key),
            "nome_social": p.get(nome_social_key),
        }

    partes = {
        "ativa": _polo(
            "deTipoPrincParteAtiva", "nmPartePrincipalAtiva", "nmSocialPartePrincipalAtiva"
        ),
        "passiva": _polo(
            "deTipoPrincPartePassiva", "nmPartePrincipalPassiva", "nmSocialPartePrincipalPassiva"
        ),
    }
    return json.dumps(partes, ensure_ascii=False)


def _coletar_orgao(
    client: TJMSClient,
    conn: sqlite3.Connection,
    *,
    cd_foro: int,
    cd_orgao_julgador: int,
    inicio_utc: datetime,
    fim_utc: datetime,
    dry_run: bool,
) -> dict[str, Any]:
    """Coleta sessões+processos de um órgão. Retorna {sessoes, processos, avisos}."""
    avisos: list[str] = []
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

        # Uma chamada única: tamanho_pagina=0 faz a API retornar todos os
        # processos da sessão e preencher paginacao.total.
        payload, _ = client.get_processo_em_pauta(
            cd_orgao_julgador=cd_orgao_julgador,
            nu_sessao=s["nuSessao"],
            nu_seq_sessao=s["nuSeqSessao"],
        )
        processos = payload["processos"]
        total = (payload.get("paginacao") or {}).get("total")
        if total is not None and len(processos) != total:
            aviso = (
                f"discrepância em sessao {s['nuSessao']}/{s['nuSeqSessao']} "
                f"(cdOJ={cd_orgao_julgador}): paginacao.total={total}, "
                f"recebidos={len(processos)}"
            )
            avisos.append(aviso)
            print(f"  AVISO: {aviso}", file=sys.stderr)

        for p in processos:
            n_processos += 1
            if dry_run:
                continue
            assert sessao_id is not None  # garantido: dry_run faz continue acima
            upsert_processo_pautado(
                conn,
                sessao_id=sessao_id,
                codigo_processo=p["cdProcesso"],
                numero_unificado=p.get("nuProcesso"),
                classe=p.get("deClasse"),
                relator=p.get("nmMagistrado"),
                partes_json=_montar_partes_json(p),
                ordem_pauta=p.get("nuOrdemPauta"),
                raw_json=json.dumps(p, ensure_ascii=False),
                de_sit_pauta=p.get("deSitPauta"),
                assunto=p.get("assunto"),
                decisao=p.get("decisao"),
                exibir_decisao=bool(p.get("exibirDecisao", False)),
                segredo_justica=bool(p.get("tpSegredo", False)),
                cd_situacao_proc=p.get("cdSituacaoProc"),
                cd_situacao_julgam=p.get("cdSituacaoJulgam"),
                url_consulta=p.get("urlDeConsulta"),
            )

    return {"sessoes": n_sessoes, "processos": n_processos, "avisos": avisos}


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
    avisos_globais: list[str] = []

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
                        )
                    else:
                        with conn:  # transação por órgão
                            m = _coletar_orgao(
                                client, conn,
                                cd_foro=o["cdForo"], cd_orgao_julgador=cd_oj,
                                inicio_utc=inicio_utc, fim_utc=fim_utc,
                                dry_run=False,
                            )
                    metricas_por_orgao[cd_oj] = m
                    avisos_globais.extend(m.get("avisos", []))
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
        print(
            f"RESUMO: status={status}  sessões={total_sessoes}  "
            f"processos={total_processos}  avisos={len(avisos_globais)}"
        )

        if not args.dry_run and execucao_id is not None:
            mensagem_partes: list[str] = []
            if erros:
                mensagem_partes.append("ERROS: " + "; ".join(erros))
            if avisos_globais:
                mensagem_partes.append("AVISOS: " + "; ".join(avisos_globais))
            mensagem = " | ".join(mensagem_partes) if mensagem_partes else None
            log_execucao_fim(
                conn, execucao_id,
                status=status,
                mensagem=mensagem,
                metricas={
                    "janela_inicio_utc": inicio_utc.isoformat(),
                    "janela_fim_utc": fim_utc.isoformat(),
                    "total_sessoes": total_sessoes,
                    "total_processos": total_processos,
                    "por_orgao": metricas_por_orgao,
                    "avisos": avisos_globais,
                },
            )
        return 0 if status == "ok" else 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
