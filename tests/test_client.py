"""Testes do TJMSClient — sem dependência de rede."""

from __future__ import annotations

import json

import pytest
import requests
import responses

from agente_tjms.client import API_BASE, TJMSClient
from agente_tjms.config import BASE_URL, PROJECT_ROOT

FIXTURE_ORGAOS = json.loads(
    (PROJECT_ROOT / "tests" / "fixtures" / "orgaos.json").read_text(encoding="utf-8")
)
FIXTURE_PROCESSO = json.loads(
    (PROJECT_ROOT / "tests" / "fixtures" / "processo_em_pauta_sample.json").read_text(
        encoding="utf-8"
    )
)


@responses.activate
def test_get_orgaos_julgadores_retorna_lista_e_raw_text():
    responses.add(
        responses.GET,
        f"{BASE_URL}{API_BASE}/consulta/orgaos-julgadores",
        json=FIXTURE_ORGAOS,
        status=200,
    )
    with TJMSClient() as client:
        orgaos, raw = client.get_orgaos_julgadores()

    assert isinstance(orgaos, list)
    assert len(orgaos) == 29
    assert {o["cdOrgaoJulgador"] for o in orgaos} >= {8, 9, 49, 51, 52, 53}
    assert json.loads(raw) == FIXTURE_ORGAOS


@responses.activate
def test_get_processo_em_pauta_retorna_processos_e_paginacao():
    responses.add(
        responses.GET,
        f"{BASE_URL}{API_BASE}/processo-em-pauta",
        json=FIXTURE_PROCESSO,
        status=200,
    )
    with TJMSClient() as client:
        payload, raw = client.get_processo_em_pauta(
            cd_orgao_julgador=8, nu_sessao=1546, nu_seq_sessao=20523
        )

    assert payload["paginacao"]["total"] == 3
    assert len(payload["processos"]) == 3

    p1 = payload["processos"][0]
    assert p1["cdProcesso"] == "P0000SGQR0000"
    assert p1["tpSegredo"] is True
    assert p1["deSitPauta"] == "Adiado"

    # Processo 9 é sparse: várias chaves estão ausentes do JSON
    p9 = payload["processos"][2]
    assert p9["cdProcesso"] == "P0000SOW10000"
    assert "nuProcesso" not in p9
    assert "nmPartePrincipalAtiva" not in p9

    assert json.loads(raw) == FIXTURE_PROCESSO


@responses.activate
def test_get_processo_em_pauta_propaga_404():
    responses.add(
        responses.GET,
        f"{BASE_URL}{API_BASE}/processo-em-pauta",
        json={"erro": "sessao inexistente"},
        status=404,
    )
    with (
        TJMSClient() as client,
        pytest.raises(requests.exceptions.HTTPError) as exc_info,
    ):
        client.get_processo_em_pauta(
            cd_orgao_julgador=8, nu_sessao=99999, nu_seq_sessao=99999
        )

    assert exc_info.value.response.status_code == 404


@responses.activate
def test_baixar_pagina_processo_retorna_html_cru():
    url = (
        "https://esaj.tjms.jus.br/cposg5/search.do"
        "?processo.codigo=P0000SMB70000&paginaConsulta=1"
    )
    html_fixture = (
        PROJECT_ROOT / "tests" / "fixtures" / "cposg_proc_julgado.html"
    ).read_text(encoding="utf-8")
    responses.add(
        responses.GET, url, body=html_fixture, status=200,
        content_type="text/html; charset=utf-8",
    )

    with TJMSClient() as client:
        html = client.baixar_pagina_processo(url)

    assert html == html_fixture
    assert "Não-Provimento" in html  # sanity: fixture real do julgado
    assert "Ementa: DIREITO PENAL" in html
