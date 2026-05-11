# CLAUDE.md

Instruções pra Claude trabalhar nesse projeto. Carregado automaticamente.

## Sobre

Agente coletor de pautas e acórdãos criminais do TJMS. Detalhes em `README.md`.
Histórico de sessões em [docs/SESSION_LOG.md](docs/SESSION_LOG.md).
Referência da API em [docs/api_tjms.md](docs/api_tjms.md).

## Como trabalhar aqui

**Discovery-first.** Em mudanças não-triviais (novos endpoints, novo módulo, mudança de arquitetura): investigação read-only primeiro (sondas HTTP, leitura de schema, fixtures), apresentar plano numerado em português, esperar aprovação explícita antes de codar. Padrão estabelecido na Sessão 1.

**File-by-file.** Apresentar o código completo antes de salvar; aguardar OK do usuário. Idem para edições via Edit tool — mostrar Old/New limpos.

**Validar após escrever arquivos Python.** Rodar `ast.parse` + checagem de funções únicas com `collections.Counter`. Já houve casos recorrentes em sessões anteriores em que o preview da ferramenta Write/Edit mostrou duplicação aparente — validar contra o disco resolve.

**Edits grandes preferencialmente como inserções com âncoras pequenas** em vez de substituir blocos extensos.

## Setup

```
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/agente-tjms init-db
.venv/bin/agente-tjms coletar --dias-atras 7
.venv/bin/pytest -q
```

## Coordenadas rápidas

- API base: `https://esaj.tjms.jus.br/pauta-julgamento/api/1.0`
- 6 órgãos criminais alvo: `cdOrgaoJulgador` ∈ {8, 9, 49, 51, 52, 53} — todos `cdForo=900`
- Banco: `data/tjms.sqlite` (gitignored, gerado por `init-db`)
- TZ: `America/Campo_Grande`
