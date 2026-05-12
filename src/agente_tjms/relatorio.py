"""Relatório semanal de acórdãos publicados.

Gera dois arquivos por semana civil (seg-dom, TZ America/Campo_Grande):
  data/relatorios/{AAAA-WW}.md   — humano-legível, com redação de privacidade
  data/relatorios/{AAAA-WW}.json — máquina-legível, sempre completo

Critério: dt_publicacao_dje BETWEEN segunda E domingo da janela.
Redação no MD: aplica em partes/ementa/decisao quando
segredo_justica=1 OR exibir_decisao=0.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import PROJECT_ROOT
from .db import get_conn, log_execucao_fim, log_execucao_inicio

TZ_CG = ZoneInfo("America/Campo_Grande")
SAIDA_DIR_DEFAULT = PROJECT_ROOT / "data" / "relatorios"
REDATADO = "[REDATADO]"


def _now_iso() -> str:
    return datetime.now(tz=TZ_CG).isoformat(timespec="seconds")


def calcular_janela(
    hoje: date | None = None, *, semana_iso: str | None = None
) -> tuple[date, date, str]:
    """Calcula (segunda, domingo, label) da semana civil.

    Se semana_iso='AAAA-WW' for dado, usa essa semana ISO.
    Senão, retorna a semana civil imediatamente anterior à de hoje.
    Label sempre no formato 'AAAA-WW'.
    """
    if hoje is None:
        hoje = datetime.now(tz=TZ_CG).date()
    if semana_iso is not None:
        ano_s, semana_s = semana_iso.split("-W")
        seg = date.fromisocalendar(int(ano_s), int(semana_s), 1)
    else:
        seg_da_semana_atual = hoje - timedelta(days=hoje.weekday())
        seg = seg_da_semana_atual - timedelta(days=7)
    dom = seg + timedelta(days=6)
    ano_iso, semana_num, _ = seg.isocalendar()
    return seg, dom, f"{ano_iso:04d}-W{semana_num:02d}"


def selecionar_acordaos(
    conn: sqlite3.Connection, *, de: date, ate: date
) -> list[sqlite3.Row]:
    """Acórdãos publicados na janela [de, ate] inclusiva."""
    sql = """
        SELECT pp.id AS pp_id, pp.codigo_processo, pp.numero_unificado,
               pp.classe, pp.relator, pp.partes_json,
               pp.decisao, pp.exibir_decisao, pp.segredo_justica,
               a.dt_julgamento, a.dt_publicacao_dje, a.ementa, a.cd_documento,
               o.cd_orgao_julgador, o.nome AS orgao_nome
          FROM acordao a
          JOIN processo_pautado pp ON pp.id = a.processo_pautado_id
          JOIN sessao s            ON s.id = pp.sessao_id
          JOIN orgao_julgador o    ON o.cd_orgao_julgador = s.cd_orgao_julgador
         WHERE a.dt_publicacao_dje BETWEEN ? AND ?
         ORDER BY o.cd_orgao_julgador, a.dt_publicacao_dje, pp.numero_unificado
    """
    return conn.execute(sql, (de.isoformat(), ate.isoformat())).fetchall()


def _processo_para_dict(row: sqlite3.Row) -> dict:
    """Normaliza Row em dict pronto pra JSON, parseando partes_json."""
    partes = json.loads(row["partes_json"]) if row["partes_json"] else None
    return {
        "codigo_processo": row["codigo_processo"],
        "numero_unificado": row["numero_unificado"],
        "classe": row["classe"],
        "relator": row["relator"],
        "orgao": {"cd": row["cd_orgao_julgador"], "nome": row["orgao_nome"]},
        "dt_julgamento": row["dt_julgamento"],
        "dt_publicacao_dje": row["dt_publicacao_dje"],
        "cd_documento": row["cd_documento"],
        "partes": partes,
        "decisao": row["decisao"],
        "exibir_decisao": bool(row["exibir_decisao"]),
        "segredo_justica": bool(row["segredo_justica"]),
        "ementa": row["ementa"],
    }


def aplicar_privacidade(processo: dict) -> dict:
    """Redata partes/ementa/decisao se restrito. Mantém metadados.

    Restrição = segredo_justica True OR exibir_decisao False.
    """
    if not (processo["segredo_justica"] or not processo["exibir_decisao"]):
        return processo
    redatado = dict(processo)
    redatado["partes"] = REDATADO
    redatado["ementa"] = REDATADO
    redatado["decisao"] = REDATADO
    return redatado


def gerar_json(processos: list[dict], *, de: date, ate: date, label: str) -> dict:
    """Estrutura JSON completa (sem redação)."""
    return {
        "semana": label,
        "de": de.isoformat(),
        "ate": ate.isoformat(),
        "gerado_em": _now_iso(),
        "total": len(processos),
        "acordaos": processos,
    }


def _fmt_partes(partes: dict | str | None) -> str:
    """Formata as partes pra MD; aceita dict, string (redatada) ou None."""
    if partes is None:
        return "(sem partes informadas)"
    if isinstance(partes, str):
        return partes
    saidas: list[str] = []
    for polo in ("ativa", "passiva"):
        p = partes.get(polo)
        if p is None:
            continue
        nome = p.get("nome_social") or p.get("nome") or "(sem nome)"
        tipo = p.get("tipo") or polo.capitalize()
        saidas.append(f"{tipo}: {nome}")
    return "  •  ".join(saidas) if saidas else "(sem partes informadas)"


def gerar_md(processos: list[dict], *, de: date, ate: date, label: str) -> str:
    """Markdown agrupado por órgão julgador, com redação já aplicada."""
    de_br = de.strftime("%d/%m/%Y")
    ate_br = ate.strftime("%d/%m/%Y")
    total = len(processos)
    redatados = sum(1 for p in processos if p["ementa"] == REDATADO)

    linhas = [
        f"# Relatório semanal — {label} ({de_br} a {ate_br})",
        "",
        f"Gerado em {_now_iso()}.",
        f"Total: {total} acórdão(s) publicado(s)"
        + (f"  ({redatados} redatado(s) por privacidade)." if redatados else "."),
        "",
    ]

    if total == 0:
        linhas.append("Nenhum acórdão publicado nesta semana.")
        return "\n".join(linhas) + "\n"

    por_orgao: dict[int, list[dict]] = {}
    nomes_orgao: dict[int, str] = {}
    for p in processos:
        cd = p["orgao"]["cd"]
        por_orgao.setdefault(cd, []).append(p)
        nomes_orgao[cd] = p["orgao"]["nome"]

    for cd in sorted(por_orgao):
        linhas.append(f"## {nomes_orgao[cd]} (cdOJ={cd})")
        linhas.append("")
        for p in por_orgao[cd]:
            tag = "  *[REDATADO]*" if p["ementa"] == REDATADO else ""
            numero = p["numero_unificado"] or p["codigo_processo"]
            classe = p["classe"] or "Processo"
            linhas.append(f"### {classe} {numero}{tag}")
            linhas.append(f"- **Relator:** {p['relator'] or '(não informado)'}")
            datas: list[str] = []
            if p["dt_julgamento"]:
                datas.append(f"**Julgamento:** {p['dt_julgamento']}")
            if p["dt_publicacao_dje"]:
                datas.append(f"**Publicação DJE:** {p['dt_publicacao_dje']}")
            if datas:
                linhas.append("- " + "  •  ".join(datas))
            linhas.append(f"- **Partes:** {_fmt_partes(p['partes'])}")
            if p["ementa"] == REDATADO:
                linhas.append(f"- **Ementa:** {REDATADO}")
            elif p["ementa"]:
                linhas.append("- **Ementa:**")
                linhas.append("")
                linhas.append(p["ementa"])
            linhas.append("")
    return "\n".join(linhas) + "\n"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="relatorio",
        description="Gera relatório semanal de acórdãos publicados.",
    )
    p.add_argument(
        "--semana", default=None,
        help="Semana ISO no formato AAAA-WW (default: semana civil anterior).",
    )
    p.add_argument(
        "--de", default=None,
        help="Data inicial YYYY-MM-DD (override de --semana; exige --ate).",
    )
    p.add_argument(
        "--ate", default=None,
        help="Data final YYYY-MM-DD (override de --semana; exige --de).",
    )
    p.add_argument(
        "--saida-dir", default=str(SAIDA_DIR_DEFAULT),
        help=f"Diretório de saída (default: {SAIDA_DIR_DEFAULT}).",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Não grava arquivos; imprime o MD no stdout.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.de and args.ate:
        de = date.fromisoformat(args.de)
        ate = date.fromisoformat(args.ate)
        ano_iso, semana_num, _ = de.isocalendar()
        label = f"{ano_iso:04d}-W{semana_num:02d}-ad-hoc"
    elif args.de or args.ate:
        print("ERRO: --de e --ate devem ser usados juntos", file=sys.stderr)
        return 2
    else:
        de, ate, label = calcular_janela(semana_iso=args.semana)

    conn = get_conn()
    execucao_id = None if args.dry_run else log_execucao_inicio(conn, "relatorio")

    try:
        rows = selecionar_acordaos(conn, de=de, ate=ate)
        brutos = [_processo_para_dict(r) for r in rows]
        redatados = [aplicar_privacidade(p) for p in brutos]

        bruto_json = gerar_json(brutos, de=de, ate=ate, label=label)
        texto_md = gerar_md(redatados, de=de, ate=ate, label=label)

        n_redatados = sum(1 for p in redatados if p["ementa"] == REDATADO)
        print(f"janela: {de} → {ate} ({label})")
        print(f"acórdãos: {len(brutos)}  redatados: {n_redatados}")

        if args.dry_run:
            print()
            print("=" * 60)
            print(texto_md)
            return 0

        saida_dir = Path(args.saida_dir)
        saida_dir.mkdir(parents=True, exist_ok=True)
        md_path = saida_dir / f"{label}.md"
        json_path = saida_dir / f"{label}.json"
        md_path.write_text(texto_md, encoding="utf-8")
        json_path.write_text(json.dumps(bruto_json, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"escrito: {md_path}")
        print(f"escrito: {json_path}")

        if execucao_id is not None:
            log_execucao_fim(
                conn, execucao_id, status="ok",
                metricas={
                    "semana": label, "de": de.isoformat(), "ate": ate.isoformat(),
                    "total": len(brutos), "redatados": n_redatados,
                },
            )
        return 0
    except Exception as e:
        if execucao_id is not None:
            log_execucao_fim(conn, execucao_id, status="erro", mensagem=str(e))
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
