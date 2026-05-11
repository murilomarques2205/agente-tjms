# agente-tjms

Agente para coletar pautas de julgamento dos órgãos criminais do TJMS, rastrear a publicação de acórdãos correspondentes e gerar relatórios periódicos.

> Este README é o **plano aprovado na Sessão 1 (discovery)** em 2026-05-11. A implementação começa na Sessão 2 — não há código ainda neste repositório.

## Escopo

Coleta diária das pautas dos **6 órgãos criminais** do TJMS publicadas na semana anterior à execução, com rastreio posterior dos acórdãos.

### Órgãos monitorados

Todos com `cdForo=900` (Tribunal de Justiça).

| # | Órgão (`nmOrgaoJulgador`) | `cdOrgaoJulgador` |
|---|---|---|
| 1 | 1ª Câmara Criminal - Tribunal de Justiça | 8 |
| 2 | 2ª Câmara Criminal - Tribunal de Justiça | 9 |
| 3 | 3ª Câmara Criminal - Tribunal de Justiça | 49 |
| 4 | 1ª Seção Criminal - Tribunal de Justiça | 53 |
| 5 | 2ª Seção Criminal - Tribunal de Justiça | 51 |
| 6 | Seção Especial - Criminal - Tribunal de Justiça | 52 |

## Arquitetura

Três módulos independentes, compartilhando `config`, `client` HTTP e `db`.

| Módulo | Responsabilidade | Periodicidade |
|---|---|---|
| `coletor_pauta` | Para cada órgão, lista sessões agendadas, filtra `dtPauta ∈ [hoje−7d, hoje]` e coleta os processos paginados; upsert em `sessao` + `processo_pautado`. | **Diário, 07:00** — idempotente; protege contra remarcação de sessão de última hora. |
| `rastreador_acordao` | Para cada `processo_pautado` com `status_acordao='pendente'`, consulta o e-SAJ; grava URL do PDF do acórdão (sem extrair texto agora). | Diário, 07:30. |
| `relatorio` | Lê o DB e gera Markdown + JSON consolidados em `data/relatorios/`. | Semanal, sexta 18:00. |

### Particularidades técnicas (descobertas no discovery)

- **SPA Angular/React.** A página de consulta não tem `<form>` HTML — o front é renderizado por `cpaj-bundle-nonIE.js`. A automação chama a API REST diretamente, sem precisar de browser headless.
- **API base:** `https://esaj.tjms.jus.br/pauta-julgamento/api/1.0`.
- **Endpoints públicos:** `consulta/orgaos-julgadores`, `sessao-agendada`.
- **Endpoint protegido:** `processos-em-pauta` retorna `302 → /sajcas/login` sem `JSESSIONID`. O `client` deve fazer **bootstrap de sessão** com um `GET` em `/pauta-julgamento/consulta?servico=526100` antes da primeira chamada protegida.
- **Filtro por data é client-side.** A API de sessões não aceita parâmetros de data; recebemos todas as sessões agendadas e filtramos pelo campo `dtPauta` (ISO 8601 UTC, convertido para `America/Campo_Grande`).
- **Cabeçalhos recomendados:** `Accept: application/json`, `Referer: …/pauta-julgamento/consulta?servico=526100`, `User-Agent` realista.

## Fluxo end-to-end

1. Cron dispara `python -m agente_tjms coletar` às 07:00.
2. `client` faz `GET` na página da consulta para obter `JSESSIONID`.
3. Para cada um dos 6 `cdOrgaoJulgador`, chama `GET /sessao-agendada?cdForo=900&cdOrgaoJulgador=X` e filtra sessões com `dtPauta` em [hoje−7d, hoje].
4. Para cada sessão filtrada: chama `GET /processos-em-pauta/?cdOrgaoJulgador=X&nuSessao=Y&nuSeqSessao=Z&paginacao.tamanhoPagina=200&paginacao.paginaAtual=N` até esgotar páginas; upsert em `sessao` e `processo_pautado`.
5. Cron diário 07:30 dispara `rastrear`: para cada `processo_pautado` com `status_acordao='pendente'`, consulta o e-SAJ; ao encontrar o acórdão, grava URL e data em `acordao` e marca o processo como `publicado`.
6. Cron semanal sexta 18:00 dispara `relatorio`, que faz `JOIN` entre as tabelas e grava `data/relatorios/AAAA-WW.md` + `data/relatorios/AAAA-WW.json`.
7. Cada execução loga uma linha em `execucao` com métricas e status.

## Estrutura de pastas

```
agente-tjms/
├── README.md                  # este arquivo
├── pyproject.toml             # (a ser criado na Sessão 2)
├── .env.example
├── .gitignore
├── data/
│   ├── tjms.sqlite            # gerado em runtime
│   └── relatorios/            # AAAA-WW.md e AAAA-WW.json
├── logs/
├── src/
│   └── agente_tjms/
│       ├── __init__.py
│       ├── config.py          # IDs dos 6 órgãos, URL base, timezone
│       ├── client.py          # requests.Session + bootstrap JSESSIONID + retry
│       ├── db.py              # conexão sqlite3, migrations, helpers upsert
│       ├── coletor_pauta.py
│       ├── rastreador_acordao.py
│       ├── relatorio.py
│       └── cli.py             # `python -m agente_tjms coletar|rastrear|relatorio`
├── scripts/
│   └── init_db.py             # cria tabelas a partir do schema
└── tests/
    ├── fixtures/
    │   └── orgaos.json        # snapshot real coletado no discovery
    └── test_*.py
```

## Schema SQLite

```sql
CREATE TABLE orgao_julgador (
    cd_orgao_julgador INTEGER PRIMARY KEY,
    cd_foro           INTEGER NOT NULL,
    nome              TEXT    NOT NULL,
    monitorado        INTEGER NOT NULL DEFAULT 0   -- 1 para os 6 alvo
);

CREATE TABLE sessao (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    nu_sessao         INTEGER NOT NULL,
    nu_seq_sessao     INTEGER NOT NULL,
    cd_orgao_julgador INTEGER NOT NULL REFERENCES orgao_julgador(cd_orgao_julgador),
    dt_pauta_utc      TEXT    NOT NULL,            -- ISO 8601 UTC, como vem da API
    coletada_em       TEXT    NOT NULL,
    UNIQUE (nu_sessao, nu_seq_sessao)
);
CREATE INDEX idx_sessao_dtpauta ON sessao(dt_pauta_utc);

CREATE TABLE processo_pautado (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    sessao_id         INTEGER NOT NULL REFERENCES sessao(id) ON DELETE CASCADE,
    codigo_processo   TEXT    NOT NULL,            -- chave interna do e-SAJ
    numero_unificado  TEXT,                        -- CNJ
    classe            TEXT,
    relator           TEXT,
    partes_json       TEXT,                        -- snapshot bruto das partes (NÃO normalizado)
    ordem_pauta       INTEGER,
    status_acordao    TEXT    NOT NULL DEFAULT 'pendente',  -- pendente|publicado|nao_julgado
    coletado_em       TEXT    NOT NULL,
    atualizado_em     TEXT    NOT NULL,
    raw_json          TEXT,                        -- payload completo da API
    UNIQUE (sessao_id, codigo_processo)
);
CREATE INDEX idx_pp_status     ON processo_pautado(status_acordao);
CREATE INDEX idx_pp_numero_cnj ON processo_pautado(numero_unificado);

CREATE TABLE acordao (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    processo_pautado_id INTEGER NOT NULL REFERENCES processo_pautado(id) ON DELETE CASCADE,
    dt_publicacao       TEXT,
    numero_acordao      TEXT,
    ementa              TEXT,
    url_pdf             TEXT,
    capturado_em        TEXT    NOT NULL,
    UNIQUE (processo_pautado_id)
);

CREATE TABLE execucao (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    modulo        TEXT NOT NULL,                   -- coletor|rastreador|relatorio
    iniciado_em   TEXT NOT NULL,
    finalizado_em TEXT,
    status        TEXT NOT NULL,                   -- ok|erro|parcial
    mensagem      TEXT,
    metricas_json TEXT                             -- ex.: {"sessoes":3,"processos":42}
);
```

Nota sobre `partes_json`: armazenado como JSON inline por enquanto. Quando for útil filtrar por nome de parte, será normalizado em tabela própria — não agora.

## Dependências Python

| Pacote | Uso |
|---|---|
| `requests` | HTTP com `Session` (cookies/keep-alive). |
| `tenacity` | Retry com backoff exponencial em 5xx / timeout. |
| `python-dateutil` | Conversão `dtPauta` UTC → `America/Campo_Grande`. |
| `beautifulsoup4` + `lxml` | Parse do e-SAJ no `rastreador_acordao`. |
| `pdfplumber` | Reservado para extração de texto de PDFs de acórdão (uso na fase de análise; o rastreador atual só guarda a URL). |
| `python-dotenv` | Carregar `.env`. |

Dev/test:

| Pacote | Uso |
|---|---|
| `pytest` + `responses` | Testes unitários com fixtures dos JSONs reais coletados no discovery. |
| `ruff` | Linter/formatter. |

Stack HTTP fixa: `requests` + `tenacity` (sem `httpx`).

## Saída do relatório

Cada execução semanal grava **dois arquivos** com o mesmo nome-base em `data/relatorios/`:

- `AAAA-WW.md` — relatório legível por humano, consolidado por órgão, listando processos pautados e seu status de acórdão.
- `AAAA-WW.json` — mesmo conteúdo em formato estruturado, para alimentar a fase de análise de acórdãos numa sessão futura.

CSV não é gerado.

## Decisões deste plano (feedback consolidado da Sessão 1)

- **Coletor diário, não semanal.** Idempotente; custo zero adicional; robustez contra remarcação de sessões de última hora.
- **`partes_json` inline.** Sem normalização agora — simplicidade > flexibilidade futura. Normalizar quando houver necessidade real.
- **`pdfplumber` previsto no `pyproject.toml`.** Não usado ainda; entra na fase de análise.
- **Saída do relatório: Markdown + JSON simultâneos.** Sem CSV.
- **Stack HTTP: `requests` + `tenacity` + `bs4` + `lxml`.** Não substituir por `httpx`.

## Status

- ✅ **Sessão 1 — discovery + plano** (2026-05-11). Endpoints mapeados, IDs dos 6 órgãos confirmados, fixture `orgaos.json` salva em `tests/fixtures/`.
- ⏳ **Sessão 2 — implementação inicial**: `config`, `client` (com bootstrap de sessão), `db`, `scripts/init_db.py`, `coletor_pauta` MVP e testes unitários sobre as fixtures.
- ⏳ **Sessão 3+ — `rastreador_acordao`, `relatorio`, agendamento (cron) e observabilidade.**
