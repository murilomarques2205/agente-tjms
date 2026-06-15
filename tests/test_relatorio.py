"""Testes do módulo relatorio."""

from __future__ import annotations

import sqlite3
from datetime import date

from agente_tjms.db import init_db, log_execucao_fim, log_execucao_inicio
from agente_tjms.relatorio import (
    REDATADO,
    aplicar_privacidade,
    calcular_janela,
    gerar_json,
    gerar_md,
    relatorio_telegram_ja_enviado,
)


def test_calcular_janela_terca_retorna_semana_imediata_anterior():
    de, ate, label = calcular_janela(hoje=date(2026, 5, 12))
    assert (de, ate, label) == (date(2026, 5, 4), date(2026, 5, 10), "2026-W19")


def test_calcular_janela_segunda_tambem_da_semana_anterior_completa():
    de, ate, label = calcular_janela(hoje=date(2026, 5, 11))
    assert (de, ate, label) == (date(2026, 5, 4), date(2026, 5, 10), "2026-W19")


def test_calcular_janela_domingo_volta_para_a_semana_civil_que_se_encerra_em_si():
    # Domingo é o ÚLTIMO dia da semana civil corrente; "anterior" é a anterior a essa.
    de, ate, label = calcular_janela(hoje=date(2026, 5, 10))
    assert (de, ate, label) == (date(2026, 4, 27), date(2026, 5, 3), "2026-W18")


def test_calcular_janela_virada_de_ano_iso():
    # 2026-01-01 é quinta; semana ISO atual = 2026-W01; anterior = 2025-W52.
    de, ate, label = calcular_janela(hoje=date(2026, 1, 1))
    assert (de, ate, label) == (date(2025, 12, 22), date(2025, 12, 28), "2025-W52")


def test_calcular_janela_via_semana_iso_explicita():
    de, ate, label = calcular_janela(semana_iso="2026-W19")
    assert (de, ate, label) == (date(2026, 5, 4), date(2026, 5, 10), "2026-W19")


def test_aplicar_privacidade_processo_publico_passa_intacto():
    p = {
        "numero_unificado": "0001",
        "partes": {"ativa": {"nome": "Fulano"}},
        "ementa": "Ementa: TESTE.",
        "decisao": "Negado provimento",
        "segredo_justica": False,
        "exibir_decisao": True,
    }
    out = aplicar_privacidade(p)
    assert out["partes"] == {"ativa": {"nome": "Fulano"}}
    assert out["ementa"] == "Ementa: TESTE."
    assert out["decisao"] == "Negado provimento"


def test_aplicar_privacidade_segredo_justica_redata():
    p = {"partes": {"a": 1}, "ementa": "x", "decisao": "y",
         "segredo_justica": True, "exibir_decisao": True}
    out = aplicar_privacidade(p)
    assert out["partes"] == REDATADO
    assert out["ementa"] == REDATADO
    assert out["decisao"] == REDATADO


def test_aplicar_privacidade_exibir_decisao_false_redata_mesmo_sem_segredo():
    p = {"partes": {"a": 1}, "ementa": "x", "decisao": "y",
         "segredo_justica": False, "exibir_decisao": False}
    out = aplicar_privacidade(p)
    assert out["partes"] == REDATADO
    assert out["ementa"] == REDATADO


def test_gerar_md_lista_vazia_diz_nenhum_acordao():
    md = gerar_md([], de=date(2026, 5, 4), ate=date(2026, 5, 10), label="2026-W19")
    assert "Nenhum acórdão publicado nesta semana" in md
    assert "2026-W19" in md
    assert "04/05/2026" in md
    assert "10/05/2026" in md


def test_gerar_md_com_publico_e_redatado_separa_corretamente():
    publico = {
        "codigo_processo": "P1",
        "numero_unificado": "0001-23.2026.8.12.0001",
        "classe": "Apelação Criminal",
        "relator": "Des. A",
        "orgao": {"cd": 8, "nome": "1ª Câmara"},
        "dt_julgamento": "2026-05-08",
        "dt_publicacao_dje": "2026-05-10",
        "cd_documento": 26,
        "partes": {"ativa": {"tipo": "Apelante", "nome": "M.S.", "nome_social": None},
                   "passiva": {"tipo": "Apelado", "nome": "J.B.", "nome_social": None}},
        "decisao": None,
        "exibir_decisao": True,
        "segredo_justica": False,
        "ementa": "Ementa: TESTE PÚBLICO.",
    }
    redatado = {
        **publico,
        "codigo_processo": "P2",
        "numero_unificado": "0002-23.2026.8.12.0001",
        "classe": "Habeas Corpus",
        "partes": REDATADO,
        "ementa": REDATADO,
        "decisao": REDATADO,
    }
    md = gerar_md([publico, redatado], de=date(2026, 5, 4), ate=date(2026, 5, 10), label="2026-W19")
    assert "1ª Câmara" in md
    assert "Apelação Criminal 0001-23.2026.8.12.0001" in md
    assert "Apelante: M.S." in md
    assert "Ementa: TESTE PÚBLICO." in md
    assert "Habeas Corpus 0002-23.2026.8.12.0001  *[REDATADO]*" in md
    assert md.count(REDATADO) >= 2  # partes + ementa redatados


def test_gerar_json_inclui_metadados_total_e_acordaos():
    p = {"numero_unificado": "0001", "ementa": "x"}
    out = gerar_json([p], de=date(2026, 5, 4), ate=date(2026, 5, 10), label="2026-W19")
    assert out["semana"] == "2026-W19"
    assert out["de"] == "2026-05-04"
    assert out["ate"] == "2026-05-10"
    assert out["total"] == 1
    assert out["acordaos"] == [p]
    assert "gerado_em" in out


# === dedupe de envio ao Telegram ===


def _conn_teste() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def _registrar_execucao(conn, *, label: str, telegram: str | None) -> int:
    """Simula uma execução do relatório como se já tivesse rodado."""
    eid = log_execucao_inicio(conn, "relatorio")
    metricas = {"semana": label}
    if telegram is not None:
        metricas["telegram"] = telegram
    log_execucao_fim(conn, eid, status="ok", metricas=metricas)
    return eid


def test_relatorio_telegram_ja_enviado_detecta_sucesso():
    conn = _conn_teste()
    _registrar_execucao(conn, label="2026-W23", telegram="ok")
    assert relatorio_telegram_ja_enviado(conn, label="2026-W23") is True


def test_relatorio_telegram_ja_enviado_ignora_semana_diferente():
    conn = _conn_teste()
    _registrar_execucao(conn, label="2026-W22", telegram="ok")
    assert relatorio_telegram_ja_enviado(conn, label="2026-W23") is False


def test_relatorio_telegram_ja_enviado_ignora_execucao_sem_telegram():
    conn = _conn_teste()
    _registrar_execucao(conn, label="2026-W23", telegram=None)
    assert relatorio_telegram_ja_enviado(conn, label="2026-W23") is False


def test_relatorio_telegram_ja_enviado_ignora_erro_no_telegram():
    conn = _conn_teste()
    _registrar_execucao(conn, label="2026-W23", telegram="erro: timeout")
    assert relatorio_telegram_ja_enviado(conn, label="2026-W23") is False


def test_relatorio_telegram_ja_enviado_ignora_marcador_de_skip():
    """O próprio marker de 'ja enviado' não pode contar como envio."""
    conn = _conn_teste()
    _registrar_execucao(
        conn, label="2026-W23",
        telegram="ja enviado anteriormente — pulado (use --forcar-telegram pra reenviar)",
    )
    assert relatorio_telegram_ja_enviado(conn, label="2026-W23") is False
