# agente-tjms

Agente para coletar pautas de julgamento dos órgãos criminais do TJMS, rastrear a publicação de acórdãos correspondentes e gerar relatórios periódicos.

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
| `coletor_pauta` | Para cada órgão, lista sessões agendadas, filtra `dtPauta ∈ [hoje−7d, hoje]` e coleta os processos paginados; upsert em `sessao` + `processo_pautado`. | **Diário, 04:30** — idempotente; protege contra remarcação de sessão de última hora. |
| `rastreador_acordao` | Para cada `processo_pautado` com `status_acordao` em `pendente`/`julgado_sem_acordao`, baixa o HTML CPOSG5 e extrai ementa inline; upsert em `acordao` e atualiza `status_acordao`. Rastreio diário nos primeiros 10 dias, depois semanal por ~6 meses; processo sem acórdão após esse prazo sai da fila e gera aviso no Telegram. | Diário, 21:00. |
| `relatorio` | Lê o DB e gera Markdown (com redação de privacidade) + JSON (íntegro) em `data/relatorios/{AAAA-WW}.{md,json}`. Filtro: `dt_publicacao_dje` na semana civil anterior. | Semanal, segunda 07:00. |

### Particularidades técnicas (descobertas no discovery)

- **SPA Angular/React.** A página de consulta não tem `<form>` HTML — o front é renderizado por `cpaj-bundle-nonIE.js`. A automação chama a API REST diretamente, sem precisar de browser headless.
- **API base:** `https://esaj.tjms.jus.br/pauta-julgamento/api/1.0`.
- **Endpoints públicos:** `consulta/orgaos-julgadores`, `sessao-agendada`, `processo-em-pauta` (singular). A URL plural `processos-em-pauta` é uma rota de **busca** por critério (`?codigoProcesso=…`, `?nomeParte=…`), não de listagem por sessão — confusão dela com a singular custou a hipótese errada de auth CAS na Sessão 2.
- **Sem autenticação.** Nenhum dos três endpoints exige `JSESSIONID`. Não há bootstrap.
- **Filtro por data é client-side.** A API de sessões não aceita parâmetros de data; recebemos todas as sessões agendadas e filtramos pelo campo `dtPauta` (ISO 8601 UTC, convertido para `America/Campo_Grande`).
- **Paginação trivial:** `processo-em-pauta` com `paginacao.tamanhoPagina=0` retorna todos os processos da sessão em uma única resposta + `paginacao.total`. O coletor faz uma chamada por sessão.
- **Cabeçalhos recomendados:** `Accept: application/json`, `User-Agent` realista.

## Fluxo end-to-end

1. **systemd-timer** (user) dispara `agente-tjms coletar` às 04:30 (diário).
2. Para cada um dos 6 `cdOrgaoJulgador`, chama `GET /sessao-agendada?cdForo=900&cdOrgaoJulgador=X` e filtra sessões com `dtPauta` em [hoje−7d, hoje].
3. Para cada sessão filtrada: chama `GET /processo-em-pauta?cdOrgaoJulgador=X&nuSessao=Y&nuSeqSessao=Z&paginacao.tamanhoPagina=0` (resposta única com todos os processos); upsert em `sessao` e `processo_pautado`.
4. Às 21:00 (diário) dispara `agente-tjms rastrear-acordaos`: seleciona os `processo_pautado` em `pendente`/`julgado_sem_acordao` ainda dentro da janela de rastreamento — fase diária (`tentativas_rastreador < 10`) ou fase semanal (até 36 tentativas, no máximo 1×/semana) — baixa o HTML CPOSG5 e extrai a ementa inline; upsert em `acordao` (`status='publicado'`) ou atualiza `status_acordao` (`sob_segredo` / `julgado_sem_acordao` / `pendente`). Processos que atingem 36 tentativas sem acórdão saem da fila e geram um aviso no Telegram.
5. Segunda 07:00 dispara `agente-tjms relatorio`: filtra `acordao.dt_publicacao_dje` na semana civil anterior (seg-dom TZ Campo Grande) e grava `data/relatorios/{AAAA-WW}.md` + `.json`.
6. Cada execução loga uma linha em `execucao` com métricas, avisos e status.

## Estrutura de pastas

```
agente-tjms/
├── README.md                  # este arquivo
├── pyproject.toml
├── .env.example
├── .gitignore
├── data/
│   ├── tjms.sqlite            # gerado em runtime
│   └── relatorios/            # AAAA-WW.md e AAAA-WW.json (a partir da Sessão 4)
├── logs/
├── src/
│   └── agente_tjms/
│       ├── __init__.py
│       ├── __main__.py        # `python -m agente_tjms` → cli.main()
│       ├── config.py          # IDs dos 6 órgãos, URL base, timezone
│       ├── client.py          # requests.Session + retry tenacity (endpoints públicos)
│       ├── db.py              # conexão sqlite3, schema, migrações, helpers upsert
│       ├── coletor_pauta.py
│       ├── rastreador_acordao.py   # (Sessão 4)
│       ├── relatorio.py            # (Sessão 4)
│       └── cli.py             # subcomandos init-db | coletar
├── scripts/
│   └── init_db.py             # cria schema + popula orgao_julgador (29) a partir da fixture
└── tests/
    ├── fixtures/
    │   ├── orgaos.json                    # 29 órgãos reais (snapshot Sessão 1)
    │   └── processo_em_pauta_sample.json  # 3 processos reais (snapshot Sessão 3)
    └── test_client.py
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
    de_sit_pauta      TEXT,                        -- deSitPauta: Adiado | Julgado | Pautado
    assunto           TEXT,                        -- assunto
    decisao           TEXT,                        -- decisao (texto bruto)
    exibir_decisao    INTEGER NOT NULL DEFAULT 0,  -- exibirDecisao (0/1)
    segredo_justica   INTEGER NOT NULL DEFAULT 0,  -- tpSegredo (0/1)
    cd_situacao_proc  TEXT,                        -- cdSituacaoProc: T (trâmite) | J (julgado)
    cd_situacao_julgam INTEGER,                    -- cdSituacaoJulgam
    url_consulta      TEXT,                        -- urlDeConsulta
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

_Acrescidos na Sessão 3 (correção da premissa errada da Sessão 2):_

- **Endpoint correto: `/processo-em-pauta` (singular), público.** A URL plural era rota de busca por critério (`?codigoProcesso=…`), não de listagem por sessão; a hipótese de CAS caiu.
- **`paginacao.tamanhoPagina=0` retorna toda a sessão em uma resposta.** Uma chamada HTTP por sessão; coletor não pagina.
- **8 colunas novas em `processo_pautado`** cobrem `deSitPauta`, `assunto`, `decisao`, `exibirDecisao`, `tpSegredo`, `cdSituacaoProc`, `cdSituacaoJulgam`, `urlDeConsulta`.
- **`partes_json` estruturado** como `{"ativa": {tipo,nome,nome_social}|null, "passiva": ...}` em vez de array bruto.
- **Migração via `_migrate()` idempotente** (`ALTER TABLE ADD COLUMN` por coluna nova, gateada por `PRAGMA table_info`).

## Agendamento (Windows + WSL — recomendado: Task Scheduler)

Em Windows + WSL, o `systemd-timer` interno só roda enquanto o WSL está em execução; o WSL desliga sozinho quando ocioso e fica suspenso até alguém abrir um terminal Ubuntu (ou outro processo iniciar o WSL). Pra evitar que os agendamentos sejam perdidos, registramos os 3 jobs no **Windows Task Scheduler**, que aciona o WSL automaticamente na hora marcada.

### Wrapper

`scripts/run-via-task-scheduler.sh` é o ponto de entrada chamado por cada tarefa: carrega `~/.config/agente-tjms/agente-tjms.env`, executa o subcomando do `agente-tjms`, loga tudo em `logs/task-scheduler.log` e — em caso de falha — manda alerta no Telegram com a cauda do log (substitui o `OnFailure` do systemd nesse modo). Propaga o código de saída pro Task Scheduler.

### Registrar as tarefas (PowerShell, uma vez)

Troque `SEU_USUARIO` pelo seu usuário Linux dentro do WSL antes de rodar.

```powershell
# Pede a senha do Windows uma vez — vai pro Credential Manager (criptografada).
$pwSecure = Read-Host "Senha do Windows para $env:USERNAME" -AsSecureString
$plainPw = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($pwSecure)
)

$wsl = "$env:SystemRoot\System32\wsl.exe"
$scriptPath = "/home/SEU_USUARIO/projetos/agente-tjms/scripts/run-via-task-scheduler.sh"
$userLogon = "$env:USERDOMAIN\$env:USERNAME"

$jobs = @(
    @{ Name='agente-tjms-coletor'
       Triggers=@(
           (New-ScheduledTaskTrigger -Daily -At '04:30'),
           (New-ScheduledTaskTrigger -AtLogOn -User $userLogon)
       )
       Args="-d Ubuntu -u SEU_USUARIO -- bash $scriptPath coletar" },
    @{ Name='agente-tjms-rastreador'
       Triggers=@(
           (New-ScheduledTaskTrigger -Daily -At '21:00'),
           (New-ScheduledTaskTrigger -AtLogOn -User $userLogon)
       )
       Args="-d Ubuntu -u SEU_USUARIO -- bash $scriptPath rastrear-acordaos" },
    @{ Name='agente-tjms-relatorio'
       Triggers=@(
           (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At '09:00'),
           (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At '10:00'),
           (New-ScheduledTaskTrigger -AtLogOn -User $userLogon)
       )
       Args="-d Ubuntu -u SEU_USUARIO -- bash $scriptPath relatorio --telegram" }
)

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable -WakeToRun `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -MultipleInstances IgnoreNew

foreach ($job in $jobs) {
    $action = New-ScheduledTaskAction -Execute $wsl -Argument $job.Args
    Register-ScheduledTask -TaskName $job.Name -Action $action `
        -Trigger $job.Triggers -Settings $settings `
        -User $userLogon -Password $plainPw -RunLevel Limited -Force | Out-Null
}
```

Opções-chave:
- `-StartWhenAvailable`: dispara o job perdido assim que possível depois (ex.: PC ligado às 9h30 roda o agendamento perdido de 9h).
- `-WakeToRun`: acorda o PC se estiver dormindo na hora marcada.
- `-User`/`-Password`: senha do Windows vai pro Credential Manager (criptografada, só o Windows local lê). A tarefa roda **mesmo sem usuário logado**.
- Trigger `-AtLogOn`: rede de segurança — se a hora marcada falhar, dispara assim que você logar.
- Dois triggers semanais no `relatorio` (Mon 09:00 + Mon 10:00): primeira tentativa + retry uma hora depois. O **dedupe** (abaixo) impede envio duplicado.
- `-MultipleInstances IgnoreNew`: se a tarefa já estiver rodando, ignora disparos novos.

### Dedupe de envio do relatório

O comando `relatorio --telegram` registra cada envio bem-sucedido em `execucao` (`semana` + `telegram=ok`). Antes de enviar, consulta esse histórico — **se a semana já foi enviada, o envio é pulado** (mas os arquivos `.md/.json/.docx` são regerados normalmente).

Isso evita duplicação quando o Task Scheduler dispara mais de uma vez (retry, catch-up tardio) ou um envio manual antecede o agendamento.

Para forçar reenvio (ex.: arquivo perdido): `agente-tjms relatorio --telegram --forcar-telegram --semana 2026-W23`.

### Verificação e operação

```powershell
# listar
Get-ScheduledTask -TaskName 'agente-tjms-*' | Format-Table TaskName, State

# rodar manualmente
Start-ScheduledTask -TaskName 'agente-tjms-coletor'

# último resultado
Get-ScheduledTaskInfo -TaskName 'agente-tjms-coletor' |
    Format-List LastRunTime, LastTaskResult, NextRunTime

# desinstalar
Get-ScheduledTask -TaskName 'agente-tjms-*' | Unregister-ScheduledTask -Confirm:$false
```

Logs (dentro do WSL):

```bash
tail -f ~/projetos/agente-tjms/logs/task-scheduler.log
```

---

## Agendamento (alternativa: systemd-timer dentro do WSL ou Linux nativo)

Os 3 jobs rodam como **user units** do systemd (sem `sudo`, sem root). Pré-requisitos: projeto em `~/projetos/agente-tjms/` com `.venv/` configurado (`pip install -e ".[dev]"`). Se seu layout difere, edite `WorkingDirectory` e `ExecStart` nos `.service` antes de instalar.

```bash
# 1. copiar units pro diretório de user systemd
mkdir -p ~/.config/systemd/user
cp deploy/systemd/*.service deploy/systemd/*.timer ~/.config/systemd/user/

# 2. recarregar systemd
systemctl --user daemon-reload

# 3. ativar e iniciar os 3 timers
systemctl --user enable --now coletor.timer rastreador.timer relatorio.timer

# 4. (servidor/laptop) habilitar lingering pra rodar sem sessão aberta
loginctl enable-linger $USER
```

Verificação:

```bash
systemctl --user list-timers                      # próximas execuções agendadas
journalctl --user -u coletor.service -n 50        # logs da última execução
systemctl --user start coletor.service            # rodar manualmente sem esperar o timer
```

Desinstalar:

```bash
systemctl --user disable --now coletor.timer rastreador.timer relatorio.timer
rm ~/.config/systemd/user/{coletor,rastreador,relatorio}.{service,timer}
systemctl --user daemon-reload
```

Notas:
- `Persistent=true` nos timers faz catch-up se a máquina estava desligada na hora marcada (roda quando ligar).
- `RandomizedDelaySec=10min` no coletor + rastreador distribui carga no e-SAJ.
- **WSL2**: precisa `systemd=true` em `/etc/wsl.conf`; timers só correm enquanto o WSL está em execução.
- **Observabilidade**: alertas opcionais via Telegram quando algum job falha — ver subseção abaixo.

### Alertas via Telegram (opcional)

Quando um service falha (`exit != 0`, exception Python, OOM etc.), o systemd dispara `alerta@<job>.service`, que envia um sumário pra um bot Telegram. Sem o env file presente, o alerta falha silenciosamente — os jobs continuam normalmente.

Setup (uma vez):

```bash
# 1. criar bot e descobrir chat_id
#    - no Telegram: @BotFather → /newbot → siga as instruções → guarde o TOKEN
#    - dê /start no novo bot pelo seu Telegram
#    - rode:  curl "https://api.telegram.org/bot${TOKEN}/getUpdates"
#      e copie result[0].message.chat.id da resposta

# 2. instalar config gitignored
mkdir -p ~/.config/agente-tjms
cp deploy/systemd/agente-tjms.env.example ~/.config/agente-tjms/agente-tjms.env
chmod 600 ~/.config/agente-tjms/agente-tjms.env
$EDITOR ~/.config/agente-tjms/agente-tjms.env   # preencher AGENTE_TJMS_HOME, _TG_TOKEN, _TG_CHAT_ID

# 3. instalar template do alerta
cp deploy/systemd/alerta@.service ~/.config/systemd/user/
systemctl --user daemon-reload

# 4. (opcional) testar disparo manual sem esperar uma falha real
systemctl --user start alerta@coletor.service
journalctl --user -u alerta@coletor.service -n 20
```

Como funciona:
- Cada um dos 3 services existentes tem `OnFailure=alerta@%N.service` em `[Unit]`. Quando termina com `exit != 0`, systemd instancia o template.
- O template lê `~/.config/agente-tjms/agente-tjms.env`, invoca `deploy/systemd/alerta.sh <job>`, que monta o payload (última row de `execucao` + últimas 15 linhas do journal) e faz `curl` pro Telegram.
- Falhas do próprio alerta (token inválido, sem rede) ficam no journal de `alerta@<job>.service` e não afetam os jobs originais.

## Status

- ✅ **Sessão 1 — discovery + plano** (2026-05-11). Endpoints mapeados, IDs dos 6 órgãos confirmados, fixture `orgaos.json` salva.
- ✅ **Sessão 2 — scaffolding** (2026-05-11). Pacote, schema inicial, client, coletor, cli, init-db, 4 testes verdes. Coleta operou em escopo B reduzido (só `sessao`) por hipótese errada de auth no endpoint plural.
- ✅ **Sessão 3 — endpoint correto + schema expandido** (2026-05-11). `/processo-em-pauta` (singular, público), 8 colunas novas, fixture `processo_em_pauta_sample.json`. Primeira coleta completa real (sessões + processos).
- ⏳ **Sessão 4+ — `rastreador_acordao`, `relatorio`, agendamento (cron), observabilidade.**
