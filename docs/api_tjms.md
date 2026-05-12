# API e-SAJ pauta-julgamento (TJMS)

Referência dos endpoints REST usados pelo `agente-tjms`. Atualizada na Sessão 3
após confirmação empírica de que `/processo-em-pauta` (singular) é público.

## Base

- URL base: `https://esaj.tjms.jus.br/pauta-julgamento/api/1.0`
- Página SPA correspondente: `https://esaj.tjms.jus.br/pauta-julgamento/consulta?servico=526100`
  (bundle `cpaj-bundle-nonIE.js`; sem `<form>` HTML — interação 100% JSON).
- **Autenticação:** nenhum dos endpoints abaixo requer JSESSIONID. Não há bootstrap.
- Cabeçalhos enviados pelo client: `Accept: application/json`, `User-Agent` realista.

## Endpoints

### 1. `GET /consulta/orgaos-julgadores`

Lista todos os órgãos julgadores. Sem parâmetros. Resposta: array.

| Campo | Tipo | Notas |
|---|---|---|
| `cdForo` | int | 900 = TJMS principal; 901/997 outros |
| `cdOrgaoJulgador` | int | chave do órgão |
| `nmOrgaoJulgador` | string | nome legível |
| `cdTipoOrgaoJulgador` | int | tipo numérico |
| `deTipoOrgaoJulgador` | string | descrição do tipo |

29 órgãos no TJMS. Snapshot: `tests/fixtures/orgaos.json`.

### 2. `GET /sessao-agendada?cdForo={f}&cdOrgaoJulgador={o}`

Lista todas as sessões agendadas de um órgão. **A API não aceita filtro por data**;
o coletor filtra `dtPauta` client-side.

| Campo | Tipo | Notas |
|---|---|---|
| `cdOrgaoJulgador` | int | espelha o parâmetro |
| `dtPauta` | string ISO 8601 UTC | ex.: `"2026-05-07T18:00:00Z"` |
| `nuSessao` | int | sequencial por órgão |
| `nuSeqSessao` | int | identificador único da sessão |

### 3. `GET /processo-em-pauta` (singular)

Lista processos pautados em uma sessão específica.

**Atenção:** a URL plural `/processos-em-pauta` é uma rota de **busca** por critério
(`?codigoProcesso=…`, `?nomeParte=…`, `?numeroUnificado=…`). Não confundir — a
confusão entre as duas URLs custou uma sessão sob hipótese errada de CAS.

Parâmetros:

| Parâmetro | Tipo | Notas |
|---|---|---|
| `cdOrgaoJulgador` | int | obrigatório |
| `nuSessao` | int | obrigatório |
| `nuSeqSessao` | int | obrigatório |
| `paginacao.tamanhoPagina` | int | **`0` retorna toda a sessão em uma resposta** |
| `paginacao.paginaAtual` | int | 0-based; ignorado se `tamanhoPagina=0` |

Resposta:

```json
{
  "processos": [ /* itens — vide tabela abaixo */ ],
  "paginacao": {
    "tamanhoPagina": 0,
    "paginaAtual": 0,
    "total": 20,
    "limit": 0,
    "offset": 0
  }
}
```

Campos por item de `processos` (35 no total — snapshot em
`tests/fixtures/processo_em_pauta_sample.json`):

| Campo | Tipo | Notas |
|---|---|---|
| `nuOrdemPauta` | int | ordem na pauta da sessão |
| `nuProcesso` | string | número CNJ (20 dígitos) |
| `cdProcesso` | string | chave interna do e-SAJ |
| `deLista` | string | ex.: `"Processos Pautados"` |
| `deClasse` | string | classe processual (ex.: `"Apelação Criminal"`) |
| `nmMagistrado` | string | nome do relator |
| `deSitPauta` | string | `Adiado` \| `Julgado` \| `Pautado` \| `Aguardando Julgamento` |
| `assunto` | string | descrição do assunto |
| `decisao` | string ou null | texto da decisão (server-side respeita segredo) |
| `exibirDecisao` | bool | se a decisão pode ser exibida publicamente |
| `tpSegredo` | bool | segredo de justiça |
| `cdSituacaoProc` | string | `T` (trâmite) \| `J` (julgado) |
| `cdSituacaoJulgam` | int | código numérico da situação |
| `deTipoPrincParteAtiva` | string ou ausente | `Impetrante`, `Apelante`, ... |
| `nmPartePrincipalAtiva` | string ou ausente | nome (iniciais se segredo) |
| `nmSocialPartePrincipalAtiva` | string ou null | nome social |
| `deTipoPrincPartePassiva` | string ou ausente | `Impetrado`, `Apelado`, ... |
| `nmPartePrincipalPassiva` | string ou ausente | nome (iniciais se segredo) |
| `nmSocialPartePrincipalPassiva` | string ou null | nome social |
| `urlDeConsulta` | string ou null | link para a página do processo |
| `nmVara` | string | redundante com `cdOrgaoJulgador` |
| `nuSeqProcJulgam` | int | sequencial do processo na sessão |
| `cdForo` | int | 900 |
| `dtSessao` | string ISO UTC | redundante com `sessao.dtPauta` |
| `numeroSessao` | int | redundante com `nuSessao` |
| `encerrado` | null observado | uso desconhecido |
| `numeroSequencialSessaoJulgamento` | null observado | uso desconhecido |
| `quantidadePedidosSustentacao` | int | fluxo de sustentação oral (fora do escopo) |
| `tipoPedidoSustentacaoUsuario` | null observado | sustentação oral |
| `nuSeqHistSustSes` | null observado | sustentação oral |
| `abertoParaPedidosSustentacao` | bool | sustentação oral |
| `usuarioPodeFazerPedidosSustentacao` | bool | sustentação oral (requer login) |
| `pedidosAtivosSustentacao` | array | sustentação oral |
| `nomeSolicitante` | null observado | uso desconhecido |
| `tipoPedidoSustentacao` | null observado | uso desconhecido |

**Sparse:** alguns campos podem estar **ausentes do JSON** (não `null`) em processos
com menos metadados. O coletor usa `.get()` para todos exceto `cdProcesso` (obrigatório).

## Outras rotas observadas (não usadas atualmente)

- `GET /sessao-julgamento?nuSessao=…&nuSeqSessao=…&cdOrgaoJulgador=…` — detalhe da sessão.
- `GET/POST /pedidos-sustentacao/…` — fluxo de sustentação oral (requer login).

## CPOSG5 — página HTML do processo (rastreador de acórdão)

Usado por `rastreador_acordao.py` (Sessão 4) para detectar publicação de
acórdão e capturar ementa inline — sem necessidade de baixar PDF do
inteiro teor.

**URL:** `https://esaj.tjms.jus.br/cposg5/search.do?processo.codigo={cdProcesso}&...`

Vem pronta no campo `urlDeConsulta` da API `/processo-em-pauta` e fica
armazenada em `processo_pautado.url_consulta`. Pública, sem login.

**Resposta:** HTML do "Consulta de Processos do 2º Grau" (~30-120kb).
`Content-Type` vem com `charset=utf-8` em produção (mocks de teste
precisam declarar explicitamente — caso contrário `requests` cai em
ISO-8859-1).

### Sentinels usados pelo parser `parse_html(html) -> dict`

| `status` retornado | Como detectar |
|---|---|
| `sob_segredo` | HTML contém `name="senhaProcesso"` ou classe `orientacao-senha-parte`; zero `<tr class="movimentacaoProcesso">` |
| `publicado` | Alguma `<tr class="movimentacaoProcesso">` traz `<span style="font-style: italic;">` cujo conteúdo contém `Ementa:` |
| `julgado_sem_acordao` | Não tem ementa inline, mas existe a movimentação `Julgamento Virtual Finalizado` |
| `pendente` | Nenhum dos sinais acima — processo ainda não julgado |

### Caminho primário vs secundário

O texto da ementa pode aparecer em **duas movimentações** do mesmo processo:

- **Primário** — `<span>Ementa: ...</span>` (acórdão em si; descrição típica
  "Não-Provimento", "Provimento", "Parcial Provimento", etc.). É o registro
  com `cdDocumento` apontando para o PDF do voto.
- **Secundário** — `<span>Teor do ato: &quot;Ementa: ...&quot;</span>` ou
  variante multilinha `<span>Publicado em DD/MM/AAAA\nNúmero do Diário
  Eletrônico: NNNN\nTeor do ato: Ementa: ...</span>` (Certidão de Publicação
  no DJE). O `cdDocumento` aqui é o PDF da Certidão, não do voto.

O parser prefere o primário pra `cd_documento_acordao` e `ementa`. As datas
saem separadas (e ambas nullable independentemente):

- `dt_julgamento` — data do `<td class="dataMovimentacaoProcesso">` da
  movimentação primária. Tipicamente o dia em que o julgamento virtual
  encerrou.
- `dt_publicacao_dje` — data análoga da movimentação secundária. Tipicamente
  o dia útil seguinte ao julgamento.

### Outras peculiaridades

- **2 `<tbody>` redundantes**: o HTML emite a tabela de movimentações na
  visível e em `<tbody id="tabelaTodasMovimentacoes" style="display:none;">`
  com todas as movimentações. Parser deduplica mantendo só a primeira
  ocorrência de cada tipo (primário/secundário).
- **Unescape**: `&Ccedil;` → `Ç`, `&Atilde;` → `Ã`, `&quot;` → `"` etc.
  já vem normalizado pelo parser via `html.unescape`.
- **`Número do Acórdão` não aparece no HTML público** (confirmado por
  grep). O `Número do Diário Eletrônico` aparece dentro do span secundário
  mas não é capturado hoje.
- **Sessão virtual concluída** é sinalizada pelo texto literal `Julgamento
  Virtual Finalizado` em alguma movimentação (sem link).

### Validação em produção

Run real em 2026-05-12 sobre os 365 processos da coleta S3:
- 365 HTTP 200, 0 erros
- Distribuição: `publicado=64`, `julgado_sem_acordao=19`, `sob_segredo=121`, `pendente=161`
- Tempo total ~5min com `--throttle 0.8`
- 64/64 acórdãos detectados tinham **ambas** as datas preenchidas (em prod, primário e secundário coexistem; cenários "só primário" / "só secundário" ficam só nos testes sintéticos)
