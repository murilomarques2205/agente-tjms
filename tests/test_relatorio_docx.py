"""Testes da geração do relatório em .docx."""

from __future__ import annotations

from datetime import date

from docx import Document

from agente_tjms.relatorio_docx import gerar_docx


def _processo(**over):
    base = {
        "codigo_processo": "P0001",
        "numero_unificado": "14057412120268120000",
        "classe": "Habeas Corpus Criminal",
        "relator": "Des. Fulano",
        "orgao": {"cd": 8, "nome": "1ª Câmara Criminal - Tribunal de Justiça"},
        "dt_julgamento": "2026-05-07",
        "dt_publicacao_dje": "2026-05-11",
        "cd_documento": 35,
        "partes": {
            "ativa": {"tipo": "Impetrante", "nome": "João", "nome_social": None},
            "passiva": None,
        },
        "decisao": "Ordem denegada",
        "exibir_decisao": True,
        "segredo_justica": False,
        "ementa": "EMENTA DE TESTE. Linha um.\nLinha dois.",
    }
    base.update(over)
    return base


def _texto(path):
    return "\n".join(p.text for p in Document(str(path)).paragraphs)


def test_gerar_docx_basico(tmp_path):
    saida = tmp_path / "2026-W19.docx"
    res = gerar_docx(
        [_processo()], de=date(2026, 5, 4), ate=date(2026, 5, 10),
        label="2026-W19", saida_path=saida,
    )
    assert res == saida and saida.exists()
    texto = _texto(saida)
    assert "RELATÓRIO SEMANAL DE ACÓRDÃOS — TJMS" in texto
    assert "1ª Câmara Criminal - Tribunal de Justiça (1 acórdão)" in texto
    assert "1405741-21.2026.8.12.0000" in texto  # CNJ formatado
    assert "EMENTA DE TESTE. Linha um." in texto
    assert "Linha dois." in texto


def test_gerar_docx_vazio(tmp_path):
    saida = tmp_path / "vazio.docx"
    gerar_docx(
        [], de=date(2026, 5, 4), ate=date(2026, 5, 10),
        label="2026-W19", saida_path=saida,
    )
    assert saida.exists()
    assert "Nenhum acórdão publicado nesta semana." in _texto(saida)


def test_gerar_docx_aplica_redacao(tmp_path):
    saida = tmp_path / "red.docx"
    redatado = _processo(partes="[REDATADO]", ementa="[REDATADO]", decisao="[REDATADO]")
    gerar_docx(
        [redatado], de=date(2026, 5, 4), ate=date(2026, 5, 10),
        label="2026-W19", saida_path=saida,
    )
    assert "[REDATADO]" in _texto(saida)
