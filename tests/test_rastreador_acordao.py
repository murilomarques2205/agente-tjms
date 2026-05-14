"""Testes do rastreador_acordao — parser e seleção de fila, sem dependência de rede."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from agente_tjms.config import PROJECT_ROOT
from agente_tjms.db import (
    init_db,
    upsert_orgao,
    upsert_processo_pautado,
    upsert_sessao,
)
from agente_tjms.rastreador_acordao import (
    MAX_TENTATIVAS_ABSOLUTO,
    parse_html,
    selecionar_fila,
)

FIX_DIR = PROJECT_ROOT / "tests" / "fixtures"

# --- helpers de fila ---

# agora fixo pros testes de selecionar_fila (TZ -04:00, como America/Campo_Grande)
_TZ = timezone(timedelta(hours=-4))
_AGORA = datetime(2026, 5, 14, 12, 0, 0, tzinfo=_TZ)


def _iso_dias_atras(dias: int) -> str:
    return (_AGORA - timedelta(days=dias)).isoformat(timespec="seconds")


def _conn_teste() -> tuple[sqlite3.Connection, int]:
    """Banco em memória com schema + um órgão e uma sessão. Retorna (conn, sessao_id)."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_db(conn)
    upsert_orgao(conn, cd_orgao_julgador=8, cd_foro=900, nome="1ª Câmara Criminal")
    sessao_id = upsert_sessao(
        conn, nu_sessao=1, nu_seq_sessao=1, cd_orgao_julgador=8,
        dt_pauta_utc="2026-05-01T12:00:00Z",
    )
    conn.commit()
    return conn, sessao_id


def _add_processo(
    conn: sqlite3.Connection,
    sessao_id: int,
    codigo: str,
    *,
    status: str = "pendente",
    tentativas: int = 0,
    ultimo_rastreio: str | None = None,
    url: str | None = "https://esaj.tjms.jus.br/cposg5/x",
) -> None:
    pid = upsert_processo_pautado(
        conn, sessao_id=sessao_id, codigo_processo=codigo, url_consulta=url,
    )
    conn.execute(
        "UPDATE processo_pautado "
        "   SET status_acordao = ?, tentativas_rastreador = ?, ultimo_rastreio_em = ? "
        " WHERE id = ?",
        (status, tentativas, ultimo_rastreio, pid),
    )
    conn.commit()


def test_julgado_publicado_extrai_ementa_e_cd_documento_do_acordao():
    html = (FIX_DIR / "cposg_proc_julgado.html").read_text(encoding="utf-8")
    out = parse_html(html)

    assert out["status"] == "publicado"
    assert out["cd_documento_acordao"] == 26
    assert out["dt_julgamento"] == "11/05/2026"       # movimentação primária ("Não-Provimento")
    assert out["dt_publicacao_dje"] == "12/05/2026"   # Certidão DJE secundária
    assert out["ementa"].startswith("Ementa: DIREITO PENAL")
    assert "APELAÇÃO" in out["ementa"]
    assert "&Ccedil;" not in out["ementa"]
    assert len(out["ementa"]) > 1000


def test_em_tramite_retorna_pendente():
    html = (FIX_DIR / "cposg_proc_tramite.html").read_text(encoding="utf-8")
    assert parse_html(html) == {
        "status": "pendente",
        "ementa": None,
        "cd_documento_acordao": None,
        "dt_julgamento": None,
        "dt_publicacao_dje": None,
    }


def test_segredo_de_justica_detectado_por_form_de_senha():
    html = (FIX_DIR / "cposg_proc_segredo.html").read_text(encoding="utf-8")
    assert parse_html(html) == {
        "status": "sob_segredo",
        "ementa": None,
        "cd_documento_acordao": None,
        "dt_julgamento": None,
        "dt_publicacao_dje": None,
    }


def test_julgamento_virtual_finalizado_sem_ementa_inline_retorna_julgado_sem_acordao():
    html = """
    <html><body><table><tbody>
      <tr class="fundoClaro movimentacaoProcesso">
        <td class="dataMovimentacaoProcesso">11/05/2026</td>
        <td></td>
        <td class="descricaoMovimentacaoProcesso">
          Julgamento Virtual Finalizado
          <br/><span style="font-style: italic;"></span>
        </td>
      </tr>
    </tbody></table></body></html>
    """
    assert parse_html(html) == {
        "status": "julgado_sem_acordao",
        "ementa": None,
        "cd_documento_acordao": None,
        "dt_julgamento": None,
        "dt_publicacao_dje": None,
    }


def test_dedupe_entre_tbodies_pega_so_a_primeira_ocorrencia():
    mov = """
      <tr class="fundoClaro movimentacaoProcesso">
        <td class="dataMovimentacaoProcesso">11/05/2026</td>
        <td><a class="linkMovVincProc" cdDocumento="99">x</a></td>
        <td class="descricaoMovimentacaoProcesso">
          <a class="linkMovVincProc" cdDocumento="99">Não-Provimento</a>
          <br/><span style="font-style: italic;">Ementa: TESTE.</span>
        </td>
      </tr>
    """
    html = (
        "<html><body><table><tbody>" + mov
        + "</tbody><tbody id='tabelaTodasMovimentacoes'>" + mov
        + "</tbody></table></body></html>"
    )
    out = parse_html(html)
    assert out["status"] == "publicado"
    assert out["cd_documento_acordao"] == 99
    assert out["ementa"] == "Ementa: TESTE."
    assert out["dt_julgamento"] == "11/05/2026"
    assert out["dt_publicacao_dje"] is None  # sintético só tem movimentação primária


def test_fallback_secundario_quando_so_ha_certidao_dje():
    html = """
    <html><body><table><tbody>
      <tr class="fundoClaro movimentacaoProcesso">
        <td class="dataMovimentacaoProcesso">12/05/2026</td>
        <td><a class="linkMovVincProc" cdDocumento="33">x</a></td>
        <td class="descricaoMovimentacaoProcesso">
          <a class="linkMovVincProc" cdDocumento="33">Certidão de Publicação - DJE</a>
          <br/><span style="font-style: italic;">Teor do ato: &quot;Ementa: FALLBACK.&quot;</span>
        </td>
      </tr>
    </tbody></table></body></html>
    """
    out = parse_html(html)
    assert out["status"] == "publicado"
    assert out["cd_documento_acordao"] == 33  # secundário vira fonte do cd quando primário ausente
    assert out["ementa"] == "Ementa: FALLBACK."
    assert out["dt_julgamento"] is None  # sintético não tem movimentação primária
    assert out["dt_publicacao_dje"] == "12/05/2026"


# === selecionar_fila ===


def test_selecionar_fila_fase_diaria_entra():
    conn, sid = _conn_teste()
    _add_processo(conn, sid, "P-DIARIA", tentativas=3, ultimo_rastreio=None)
    fila = selecionar_fila(conn, agora=_AGORA)
    assert [r["codigo_processo"] for r in fila] == ["P-DIARIA"]
    conn.close()


def test_selecionar_fila_fase_semanal_vencida_entra():
    conn, sid = _conn_teste()
    _add_processo(conn, sid, "P-SEMANAL", tentativas=15, ultimo_rastreio=_iso_dias_atras(10))
    fila = selecionar_fila(conn, agora=_AGORA)
    assert [r["codigo_processo"] for r in fila] == ["P-SEMANAL"]
    conn.close()


def test_selecionar_fila_fase_semanal_recente_nao_entra():
    conn, sid = _conn_teste()
    _add_processo(conn, sid, "P-RECENTE", tentativas=15, ultimo_rastreio=_iso_dias_atras(2))
    assert selecionar_fila(conn, agora=_AGORA) == []
    conn.close()


def test_selecionar_fila_teto_absoluto_nao_entra():
    conn, sid = _conn_teste()
    _add_processo(
        conn, sid, "P-TETO",
        tentativas=MAX_TENTATIVAS_ABSOLUTO, ultimo_rastreio=_iso_dias_atras(100),
    )
    assert selecionar_fila(conn, agora=_AGORA) == []
    conn.close()


def test_selecionar_fila_ignora_publicado_e_sob_segredo():
    conn, sid = _conn_teste()
    _add_processo(conn, sid, "P-PUBLICADO", status="publicado", tentativas=2)
    _add_processo(conn, sid, "P-SEGREDO", status="sob_segredo", tentativas=2)
    assert selecionar_fila(conn, agora=_AGORA) == []
    conn.close()


def test_selecionar_fila_ignora_sem_url_consulta():
    conn, sid = _conn_teste()
    _add_processo(conn, sid, "P-SEM-URL", tentativas=2, url=None)
    assert selecionar_fila(conn, agora=_AGORA) == []
    conn.close()
