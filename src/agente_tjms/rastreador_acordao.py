"""Rastreador de acórdãos: parser HTML CPOSG5 do e-SAJ/TJMS.

Discovery do padrão registrado em docs/SESSION_LOG.md (Sessão 4). O HTML do
processo no CPOSG5 traz movimentações com ementa inline em <span> itálico;
não é preciso baixar PDF do inteiro teor pra detectar publicação ou capturar
o texto da ementa.
"""

from __future__ import annotations

import re
from html import unescape

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
      cd_documento: int ou None
      data_publicacao: str 'DD/MM/AAAA' ou None
    """
    if _SENTINEL_SEGREDO.search(html):
        return {
            "status": "sob_segredo",
            "ementa": None,
            "cd_documento": None,
            "data_publicacao": None,
        }

    achados_primarios: list[dict] = []   # <span>Ementa: ...</span> (acórdão em si)
    achados_secundarios: list[dict] = [] # <span>Teor do ato: "Ementa: ..."</span> (Certidão DJE)
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

            primario = conteudo[:idx].strip() == ""

            ementa_raw = conteudo[idx:]
            if ementa_raw.endswith("&quot;"):
                ementa_raw = ementa_raw[:-6]
            ementa = unescape(ementa_raw).strip()

            cd_match = _CD_DOCUMENTO.search(bloco)
            data_match = _DATA_MOVIMENTACAO.search(bloco)

            achado = {
                "status": "publicado",
                "ementa": ementa,
                "cd_documento": int(cd_match.group(1)) if cd_match else None,
                "data_publicacao": data_match.group(1) if data_match else None,
            }
            (achados_primarios if primario else achados_secundarios).append(achado)
            break  # 1 ementa por movimentação basta

    if achados_primarios:
        return achados_primarios[0]
    if achados_secundarios:
        return achados_secundarios[0]
    if tem_julgamento_virtual:
        return {
            "status": "julgado_sem_acordao",
            "ementa": None,
            "cd_documento": None,
            "data_publicacao": None,
        }
    return {
        "status": "pendente",
        "ementa": None,
        "cd_documento": None,
        "data_publicacao": None,
    }
