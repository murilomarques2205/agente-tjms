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
