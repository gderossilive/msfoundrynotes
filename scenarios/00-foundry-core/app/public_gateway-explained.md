# Guida al Public Gateway di 00a

Il [profilo Public Gateway](../00a-foundry-core-public/README.md#optional-public-gateway-api-management-basic-v2)
aggiunge API Management Basic v2 alla lane pubblica 00a, non una nuova lane
o un agente. Questa guida segue infrastruttura,
[`apply-gateway-policy.sh`](../../../scripts/apply-gateway-policy.sh) e client
del [README applicazione](README.md#public-gateway-00a).

## Obiettivo

Dimostrare che un gateway davanti a un endpoint Foundry pubblico e' **una porta
aggiuntiva, non l'unica**: un deployer con ruolo diretto puo' aggirarlo.
Budget e attribuzione per chiamante coprono solo il traffico che attraversa APIM.
Il profilo non impone accesso gateway-only e non modifica i ruoli necessari a
benchmark, fine-tuning o monitoring diretto.

## Flusso generale

```text
                   +-> Foundry pubblico (ruolo diretto): bypass possibile
chiamante Entra ---+
                   +-> APIM Basic v2 -> token validato -> allowlist object ID
                       -> [budget] -> [metrica Caller] -> managed identity
                       -> stesso deployment Foundry
```

## 1. Parametri e risorse Bicep

[`main.bicep`](../00a-foundry-core-public/infra/main.bicep) ha
`enableGateway=false`: il deployment base rimane account, progetto e modello.
Il profilo richiama
[`foundry-public-gateway`](../../../modules/apim/foundry-public-gateway/main.bicep)
dopo la creazione della fondazione Foundry.

Il modulo genera nomi deterministici, crea un solo APIM pubblico senza VNet,
con managed identity di sistema, ruolo Cognitive Services OpenAI User
sull'account, API `openai/v1` e operazione `POST /chat/completions`.
Il tier predefinito e' Basic v2; Standard v2 e' ammesso ma non provato nel run
storico. Nessuna subscription key e' richiesta dall'API.

**Il provisioning non applica la policy.** Nel laboratorio il gateway rispondeva
anche prima di applicarla. L'ipotesi dell'inoltro del token del deployer non e'
stata verificata. Non considerare quell'intervallo deny-all e applica la policy
subito dopo il provisioning, senza esporre dati reali.

## 2. Policy condivisa con 00c

I wrapper [`00a`](../00a-foundry-core-public/infra/apim-policy.bicep) e
[`00c`](../00c-foundry-core-byo-vnet/infra/apim-policy.bicep) richiamano lo stesso
[`foundry-chat-policy`](../../../modules/apim/foundry-chat-policy/main.bicep).
I test confrontano i wrapper per evitare divergenze.

La policy valida tenant e audience Entra, estrae `oid`, lo normalizza e applica
l'allowlist. Lista vuota = tutti negati. Solo dopo autorizzazione inserisce gli
eventuali limite e metrica, ottiene il token della managed identity del gateway
per il backend ed elimina una eventuale api-key client.

Il budget usa object ID validato, non IP o header client. `tokensPerMinute=0`
lo disattiva. Per i dettagli del 429 e la demo con due identita', vedi
[`token_limit_demo.py`](token_limit_demo-explained.md).

## 3. Script di applicazione

`apply-gateway-policy.sh` accetta lane e ambiente, seleziona la directory azd
corretta e legge resource group, APIM e allowlist. Valida budget intero
0-10.000.000, allowlist e flag metriche prima del deployment della policy.
Se un'opzione azd e' assente, controlla l'exit status: azd puo' stampare il
diagnostico su stdout. Il default documentato e' 0 per budget e false per metriche.

Con metriche attive distribuisce anche
[`foundry-usage-metrics`](../../../modules/apim/foundry-usage-metrics/main.bicep):
workspace di 30 giorni, Application Insights Entra-only, logger APIM con
managed identity e Monitoring Metrics Publisher, diagnostica API senza body.
Memorizza nel solo ambiente azd gli ID del workspace.
E' supporto tecnico alla verifica del bypass, non una release Usage Attribution.

## 4. Client e secondo chiamante

[`chat_completions.py`](chat_completions-explained.md) accetta l'endpoint APIM
anche su 00a; gli output gateway vuoti significano profilo disabilitato.
`--target direct` continua a usare Foundry, `--target gateway` usa APIM.

[`manage-second-caller.sh`](../../../scripts/manage-second-caller.sh) crea
opzionalmente un'app/service principal senza ruoli Azure, con certificato di
un giorno e profilo Azure CLI separato nella directory ignorata `.azure/`.
Aggiunge all'allowlist l'object ID del service principal, **non** l'application ID.
Richiede permessi per app registration. Una seconda identita' utente autorizzata
e' alternativa manuale. Non copiare credenziali o stato in Git.

## Argomenti, impostazioni e codici di uscita

| Superficie | Valore |
| --- | --- |
| `AZURE_ENABLE_GATEWAY` | `false` di default; enable prima di provisioning autorizzato |
| `AZURE_GATEWAY_APIM_SKU` | `BasicV2` di default, oppure `StandardV2` |
| `AZURE_APIM_PUBLISHER_EMAIL/NAME` | Contatto publisher configurato dal deployer |
| `AZURE_APIM_ALLOWED_PRINCIPAL_IDS` | Array JSON di object ID Entra, default `[]` |
| `AZURE_APIM_TOKENS_PER_MINUTE` | `0` di default per 00a/00c |
| `AZURE_APIM_USAGE_METRICS` | `false` di default; crea risorse telemetria se true |
| `apply-gateway-policy.sh <00a\|00c> <environment>` | Applica policy alla lane selezionata |
| `manage-second-caller.sh <00a\|00c> <create\|cleanup> <environment>` | Gestisce la sola identita' B registrata |

Gli script usano `2` per argomenti/configurazione rifiutati; altri errori CLI
interrompono l'esecuzione con esito nonzero. Il client usa `0` per risposta,
`1` per errore richiesta e `2` per configurazione non valida.

## Come eseguirlo

Prima autorizza costi APIM e permessi. Configura tenant/subscription come nel
[README root](../../../README.md#configure-and-deploy), senza cambiare altri lab.
Dalla root:

```bash
scripts/bootstrap-scenario-env.sh 00-foundry-core/00a-foundry-core-public
cd scenarios/00-foundry-core/00a-foundry-core-public
environment=<your-00a-azd-environment>
azd env set AZURE_ENABLE_GATEWAY true --environment "$environment"
azd env set AZURE_APIM_ALLOWED_PRINCIPAL_IDS '["<caller-object-id>"]' --environment "$environment"
azd provision --environment "$environment"
cd ../../..
scripts/apply-gateway-policy.sh 00a "$environment"
```

Dall'app, dopo installazione delle dipendenze base:

```bash
cd scenarios/00-foundry-core/app
python chat_completions.py --environment "$environment" --scenario 00a --target direct "Reply with one word: ready."
python chat_completions.py --environment "$environment" --scenario 00a --target gateway "Reply with one word: ready."
```

Per verificare budget e bypass, abilita separatamente budget e metriche dalla
directory della lane, riapplica la policy dalla root, poi usa
[`token_limit_demo.py`](token_limit_demo-explained.md) con `--scenario 00a` e
[`usage_report.py`](usage_report-explained.md) con `--scenario 00a`.
La demo non imposta automaticamente un budget o crea identita'.

## Come interpretare i risultati

Il [report d'uso](usage_report-explained.md) confronta `AppMetrics` per Caller
con `InputTokens`/`OutputTokens` dello stesso deployment. Usa nomi metrici
esatti senza sommare famiglie duplicate. I token di reasoning sono gia'
inclusi nelle completion. Allinea la finestra ai minuti interi e attendi
l'ingestione.

`model_minus_gateway_input/output` positivi misurano token che il modello ha
servito ma la metrica APIM non ha visto. Possono indicare bypass, traffico prima
dell'attivazione o confini temporali: non attribuirli automaticamente a un
chiamante. La differenza e' segnalata con exit code `1`, anche quando nel lab
e' intenzionale. Nessun dato e' exit code `3`, non un report vuoto riuscito.

## Evidenza storica: 2026-11-02, Italy North

Basic v2 con `gpt-4.1-mini`: provisioning 3m08s, teardown 4m57s.
Direct e gateway hanno entrambi restituito 200; senza token o con token
malformato il gateway con policy ha restituito 401.

Budget 600 non raggiunto in 15 chiamate; con 120 token/min A ha avuto nove
200, poi 429 (`Retry-After: 3`), B 200 e A nuovamente 200.
I tier v2 usano token bucket con refill: non trasferire loro i tempi della
finestra scorrevole di APIM Developer.

Due chiamate dirette erano assenti dalla metrica gateway:
modello meno gateway = esattamente 28 token input + 6 output.
Gli header della demo coincidevano con APIM (A 157, B 16 token).
Il laboratorio e il secondo chiamante sono stati rimossi.
Nessun nuovo provisioning o run live e' implicato da questa pubblicazione.

## Test, costi e pulizia

I test statici compilano Bicep e verificano profilo opt-in, account pubblico,
ruoli, assenza di VNet nel gateway e policy condivisa. I test Python mockano
azd, Azure e modello: non provano deployment o enforcement live.

APIM resta fatturabile anche inattivo. Monitoring e model calls hanno costi
separati. Disabilitare un parametro non elimina risorse ARM incremental.
Per B, dalla root, usa cleanup e riapplica la policy:

```bash
scripts/manage-second-caller.sh 00a cleanup "$environment"
scripts/apply-gateway-policy.sh 00a "$environment"
```

Poi, solo dopo verifica di subscription, ambiente e resource group, dalla lane:

```bash
azd env get-value AZURE_RESOURCE_GROUP --environment "$environment"
azd down --environment "$environment" --force --purge
```

## Limiti intenzionali

Nessun gateway-only, sicurezza di produzione, streaming, piu' istanze,
stress test o fatturazione per chiamante. Il 429 del modello non e' stato
provocato; un codice 429 da solo non identifica il livello che lo ha generato.
Uso esclusivo di dati sintetici e Microsoft Foundry new.
