"""Testes do parser parse_html do rastreador_acordao — sem dependência de rede."""

from __future__ import annotations

from agente_tjms.config import PROJECT_ROOT
from agente_tjms.rastreador_acordao import parse_html

FIX_DIR = PROJECT_ROOT / "tests" / "fixtures"


def test_julgado_publicado_extrai_ementa_e_cd_documento_do_acordao():
    html = (FIX_DIR / "cposg_proc_julgado.html").read_text(encoding="utf-8")
    out = parse_html(html)

    assert out["status"] == "publicado"
    assert out["cd_documento"] == 26
    assert out["data_publicacao"] == "11/05/2026"
    assert out["ementa"].startswith("Ementa: DIREITO PENAL")
    assert "APELAÇÃO" in out["ementa"]
    assert "&Ccedil;" not in out["ementa"]
    assert len(out["ementa"]) > 1000


def test_em_tramite_retorna_pendente():
    html = (FIX_DIR / "cposg_proc_tramite.html").read_text(encoding="utf-8")
    assert parse_html(html) == {
        "status": "pendente",
        "ementa": None,
        "cd_documento": None,
        "data_publicacao": None,
    }


def test_segredo_de_justica_detectado_por_form_de_senha():
    html = (FIX_DIR / "cposg_proc_segredo.html").read_text(encoding="utf-8")
    assert parse_html(html) == {
        "status": "sob_segredo",
        "ementa": None,
        "cd_documento": None,
        "data_publicacao": None,
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
        "cd_documento": None,
        "data_publicacao": None,
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
    html = "<html><body><table><tbody>" + mov + "</tbody><tbody id='tabelaTodasMovimentacoes'>" + mov + "</tbody></table></body></html>"
    out = parse_html(html)
    assert out["status"] == "publicado"
    assert out["cd_documento"] == 99
    assert out["ementa"] == "Ementa: TESTE."
    assert out["data_publicacao"] == "11/05/2026"


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
    assert out["cd_documento"] == 33
    assert out["ementa"] == "Ementa: FALLBACK."
    assert out["data_publicacao"] == "12/05/2026"
