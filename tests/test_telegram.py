"""Testes do módulo telegram — sem dependência de rede."""

from __future__ import annotations

import pytest
import requests
import responses

from agente_tjms import telegram

TOKEN = "123:ABC"
CHAT = "999"


def test_ler_credenciais_presentes(monkeypatch):
    monkeypatch.setenv("AGENTE_TJMS_TG_TOKEN", "tok")
    monkeypatch.setenv("AGENTE_TJMS_TG_CHAT_ID", "42")
    assert telegram.ler_credenciais() == ("tok", "42")


def test_ler_credenciais_ausentes(monkeypatch):
    monkeypatch.delenv("AGENTE_TJMS_TG_TOKEN", raising=False)
    monkeypatch.delenv("AGENTE_TJMS_TG_CHAT_ID", raising=False)
    assert telegram.ler_credenciais() is None


def test_ler_credenciais_parcial(monkeypatch):
    monkeypatch.setenv("AGENTE_TJMS_TG_TOKEN", "tok")
    monkeypatch.delenv("AGENTE_TJMS_TG_CHAT_ID", raising=False)
    assert telegram.ler_credenciais() is None


@responses.activate
def test_enviar_mensagem_ok():
    responses.add(
        responses.POST,
        f"{telegram.API_BASE}/bot{TOKEN}/sendMessage",
        json={"ok": True, "result": {}},
        status=200,
    )
    telegram.enviar_mensagem(TOKEN, CHAT, "oi")  # não levanta
    assert len(responses.calls) == 1


@responses.activate
def test_enviar_mensagem_erro_levanta():
    responses.add(
        responses.POST,
        f"{telegram.API_BASE}/bot{TOKEN}/sendMessage",
        json={"ok": False, "description": "chat not found"},
        status=400,
    )
    with pytest.raises(telegram.TelegramError, match="chat not found"):
        telegram.enviar_mensagem(TOKEN, CHAT, "oi")


@responses.activate
def test_enviar_documento_ok(tmp_path):
    arq = tmp_path / "rel.docx"
    arq.write_bytes(b"conteudo binario")
    responses.add(
        responses.POST,
        f"{telegram.API_BASE}/bot{TOKEN}/sendDocument",
        json={"ok": True, "result": {}},
        status=200,
    )
    telegram.enviar_documento(TOKEN, CHAT, arq, legenda="teste")
    assert len(responses.calls) == 1


@responses.activate
def test_enviar_documento_erro_levanta(tmp_path):
    arq = tmp_path / "rel.docx"
    arq.write_bytes(b"x")
    responses.add(
        responses.POST,
        f"{telegram.API_BASE}/bot{TOKEN}/sendDocument",
        json={"ok": False, "description": "file too big"},
        status=400,
    )
    with pytest.raises(telegram.TelegramError, match="file too big"):
        telegram.enviar_documento(TOKEN, CHAT, arq)


@responses.activate
def test_enviar_mensagem_erro_de_rede_vira_telegram_error():
    responses.add(
        responses.POST,
        f"{telegram.API_BASE}/bot{TOKEN}/sendMessage",
        body=requests.exceptions.ConnectionError("dns down"),
    )
    with pytest.raises(telegram.TelegramError, match="falha de rede"):
        telegram.enviar_mensagem(TOKEN, CHAT, "oi")
