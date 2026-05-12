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
