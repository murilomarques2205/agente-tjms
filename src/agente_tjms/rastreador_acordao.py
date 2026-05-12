"""Rastreador de acórdãos: parser HTML CPOSG5 do e-SAJ/TJMS.

Discovery do padrão registrado em docs/SESSION_LOG.md (Sessão 4). O HTML do
processo no CPOSG5 traz movimentações com ementa inline em <span> itálico;
não é preciso baixar PDF do inteiro teor pra detectar publicação ou capturar
o texto da ementa.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import time
from datetime import datetime
from html import unescape

from .client import TJMSClient
from .db import get_conn, log_execucao_fim, log_execucao_inicio

# Form de senha em vez de movimentações = processo sob segredo de justiça
_SENTINEL_SEGREDO = re.compile(
    r'name="senhaProcesso"|class="orientacao-senha-parte"'
)

# Cada movimentação no DOM
_TR_MOVIMENTACAO = re.compile(
    r'<tr[^>]*movimentacaoProcesso[^>]*>(.*?)</tr>',
    re.DOTALL | re.IGNORECASE,
)

# Spans em itálico carregam descrição complementar (ementa, "Teor do ato", etc.)
_SPAN_ITALICO = re.compile(
    r'<span\s+style="font-style:\s*italic;"\s*>([^<]*?)</span>',
    re.DOTALL,
)

_CD_DOCUMENTO = re.compile(r'cdDocumento="(\d+)"')

_DATA_MOVIMENTACAO = re.compile(
    r'class="dataMovimentacaoProcesso"[^>]*>\s*(\d{2}/\d{2}/\d{4})',
    re.DOTALL,
)

# Texto fixo de movimentação após sessão virtual concluída
_SENTINEL_JULGAMENTO_VIRTUAL = "Julgamento Virtual Finalizado"


def parse_html(html: str) -> dict:
    """Classifica o estado do acórdão num HTML CPOSG5 do TJMS.

    Retorna dict com chaves:
      status: 'publicado' | 'julgado_sem_acordao' | 'sob_segredo' | 'pendente'
      ementa: str ou None  (já html-unescaped)
      cd_documento_acordao: int ou None  (cd da movimentação primária; cai pro secundário só se primário ausente)
      dt_julgamento: str 'DD/MM/AAAA' ou None  (data da movimentação primária — acórdão em si)
      dt_publicacao_dje: str 'DD/MM/AAAA' ou None  (data da movimentação secundária — Certidão/Publicação no DJE)
    """
    if _SENTINEL_SEGREDO.search(html):
        return {
            "status": "sob_segredo",
            "ementa": None,
            "cd_documento_acordao": None,
            "dt_julgamento": None,
            "dt_publicacao_dje": None,
        }

    primario: dict | None = None    # <span>Ementa: ...</span> (acórdão em si)
    secundario: dict | None = None  # <span>...Teor do ato:...Ementa:...</span> (Certidão DJE / Publicação)
    tem_julgamento_virtual = False

    for tr in _TR_MOVIMENTACAO.finditer(html):
        bloco = tr.group(1)
        if _SENTINEL_JULGAMENTO_VIRTUAL in bloco:
            tem_julgamento_virtual = True

        for span in _SPAN_ITALICO.finditer(bloco):
            conteudo = span.group(1)
            idx = conteudo.find("Ementa:")
            if idx == -1:
                continue

            eh_primario = conteudo[:idx].strip() == ""
            # Mantém só o primeiro de cada tipo (CPOSG5 lista em ordem reversa-cronológica,
            # então o primeiro é o acórdão mais recente).
            if (eh_primario and primario is not None) or (not eh_primario and secundario is not None):
                break

            ementa_raw = conteudo[idx:]
            if ementa_raw.endswith("&quot;"):
                ementa_raw = ementa_raw[:-6]
            ementa = unescape(ementa_raw).strip()

            cd_match = _CD_DOCUMENTO.search(bloco)
            data_match = _DATA_MOVIMENTACAO.search(bloco)

            achado = {
                "ementa": ementa,
                "cd_documento": int(cd_match.group(1)) if cd_match else None,
                "data": data_match.group(1) if data_match else None,
            }
            if eh_primario:
                primario = achado
            else:
                secundario = achado
            break  # 1 ementa por movimentação basta

    if primario is not None or secundario is not None:
        # Ementa/cd_documento vêm preferencialmente do primário (acórdão em si);
        # cai pro secundário só se primário não existir.
        fonte = primario or secundario
        return {
            "status": "publicado",
            "ementa": fonte["ementa"],
            "cd_documento_acordao": fonte["cd_documento"],
            "dt_julgamento": primario["data"] if primario else None,
            "dt_publicacao_dje": secundario["data"] if secundario else None,
        }

    if tem_julgamento_virtual:
        return {
            "status": "julgado_sem_acordao",
            "ementa": None,
            "cd_documento_acordao": None,
            "dt_julgamento": None,
            "dt_publicacao_dje": None,
        }
    return {
        "status": "pendente",
        "ementa": None,
        "cd_documento_acordao": None,
        "dt_julgamento": None,
        "dt_publicacao_dje": None,
    }


# ==== Orquestrador ====

MAX_TENTATIVAS = 10
THROTTLE_S_DEFAULT = 0.8
STATUS_PROCESSAVEIS = ("pendente", "julgado_sem_acordao")


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _data_br_para_iso(dt: str | None) -> str | None:
    """Converte 'DD/MM/AAAA' para 'AAAA-MM-DD'. None passa direto."""
    if dt is None:
        return None
    return datetime.strptime(dt, "%d/%m/%Y").strftime("%Y-%m-%d")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="rastreador_acordao",
        description="Visita o CPOSG5 dos processos pendentes pra detectar acórdão publicado.",
    )
    p.add_argument(
        "--limite", type=int, default=None,
        help="Máximo de processos a processar nesta execução (default: todos da fila).",
    )
    p.add_argument(
        "--throttle", type=float, default=THROTTLE_S_DEFAULT,
        help=f"Segundos de espera entre requests (default: {THROTTLE_S_DEFAULT}).",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Não grava no DB; só classifica e imprime contadores.",
    )
    return p.parse_args(argv)


def selecionar_fila(
    conn: sqlite3.Connection, *, limite: int | None = None
) -> list[sqlite3.Row]:
    """Retorna processos elegíveis pro rastreamento.

    Critério: status em ('pendente', 'julgado_sem_acordao'), tentativas < MAX,
    url_consulta não-nula. Ordenado por menos tentativas primeiro.
    """
    sql = """
        SELECT id, codigo_processo, url_consulta, status_acordao, tentativas_rastreador
          FROM processo_pautado
         WHERE status_acordao IN (?, ?)
           AND tentativas_rastreador < ?
           AND url_consulta IS NOT NULL AND url_consulta != ''
         ORDER BY tentativas_rastreador ASC, id ASC
    """
    params: list = [*STATUS_PROCESSAVEIS, MAX_TENTATIVAS]
    if limite is not None:
        sql += " LIMIT ?"
        params.append(limite)
    return conn.execute(sql, params).fetchall()


def aplicar_resultado(
    conn: sqlite3.Connection, processo_pautado_id: int, resultado: dict
) -> None:
    """Persiste o retorno do parse_html.

    Sempre atualiza processo_pautado (status, tentativas++, ultimo_rastreio_em).
    Se status='publicado', upsert em acordao.
    """
    agora = _now_iso()
    conn.execute(
        """
        UPDATE processo_pautado
           SET status_acordao        = ?,
               tentativas_rastreador = tentativas_rastreador + 1,
               ultimo_rastreio_em    = ?,
               atualizado_em         = ?
         WHERE id = ?
        """,
        (resultado["status"], agora, agora, processo_pautado_id),
    )
    if resultado["status"] == "publicado":
        conn.execute(
            """
            INSERT INTO acordao (
                processo_pautado_id, dt_julgamento, dt_publicacao_dje,
                ementa, cd_documento, capturado_em
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(processo_pautado_id) DO UPDATE SET
                dt_julgamento     = excluded.dt_julgamento,
                dt_publicacao_dje = excluded.dt_publicacao_dje,
                ementa            = excluded.ementa,
                cd_documento      = excluded.cd_documento,
                capturado_em      = excluded.capturado_em
            """,
            (
                processo_pautado_id,
                _data_br_para_iso(resultado["dt_julgamento"]),
                _data_br_para_iso(resultado["dt_publicacao_dje"]),
                resultado["ementa"],
                resultado["cd_documento_acordao"],
                agora,
            ),
        )


def _registrar_erro(conn: sqlite3.Connection, processo_pautado_id: int) -> None:
    """Incrementa tentativas mesmo em erro pra evitar loop infinito."""
    agora = _now_iso()
    conn.execute(
        """
        UPDATE processo_pautado
           SET tentativas_rastreador = tentativas_rastreador + 1,
               ultimo_rastreio_em    = ?,
               atualizado_em         = ?
         WHERE id = ?
        """,
        (agora, agora, processo_pautado_id),
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    conn = get_conn()
    execucao_id = None if args.dry_run else log_execucao_inicio(conn, "rastreador_acordao")

    contadores = {
        "publicado": 0, "julgado_sem_acordao": 0,
        "sob_segredo": 0, "pendente": 0, "erro": 0,
    }
    erros: list[str] = []

    try:
        fila = selecionar_fila(conn, limite=args.limite)
        print(f"fila: {len(fila)} processos  (limite={args.limite}, dry_run={args.dry_run})")
        print()

        with TJMSClient() as client:
            for i, row in enumerate(fila, 1):
                try:
                    html = client.baixar_pagina_processo(row["url_consulta"])
                    resultado = parse_html(html)
                    status = resultado["status"]
                    if not args.dry_run:
                        with conn:  # transação por processo
                            aplicar_resultado(conn, row["id"], resultado)
                    contadores[status] += 1
                    print(
                        f"  [{i:>3}/{len(fila)}] {row['codigo_processo']} → {status}"
                    )
                except Exception as e:
                    contadores["erro"] += 1
                    erros.append(f"{row['codigo_processo']}: {e}")
                    if not args.dry_run:
                        with conn:
                            _registrar_erro(conn, row["id"])
                    print(
                        f"  [{i:>3}/{len(fila)}] {row['codigo_processo']} → ERRO: {e}",
                        file=sys.stderr,
                    )

                if i < len(fila):
                    time.sleep(args.throttle)

        if contadores["erro"] == 0:
            status_global = "ok"
        elif contadores["erro"] < len(fila):
            status_global = "parcial"
        else:
            status_global = "erro"

        print()
        print(
            f"RESUMO: status={status_global}  total={len(fila)}  "
            + "  ".join(f"{k}={v}" for k, v in contadores.items())
        )

        if execucao_id is not None:
            log_execucao_fim(
                conn, execucao_id,
                status=status_global,
                mensagem=("; ".join(erros[:5]) + (f" (+{len(erros)-5})" if len(erros) > 5 else "")) if erros else None,
                metricas={
                    "total": len(fila),
                    "limite": args.limite,
                    "throttle_s": args.throttle,
                    "contadores": contadores,
                },
            )
        return 0 if status_global == "ok" else 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
