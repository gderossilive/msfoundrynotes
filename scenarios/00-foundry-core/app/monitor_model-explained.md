# Guida a `monitor_model.py`

[`monitor_model.py`](monitor_model.py) osserva il modello dello
[scenario 00a, livello 00, lane a](../00a-foundry-core-public/README.md).
Non crea risorse, non distribuisce un'applicazione, non esegue fine-tuning e non
crea un agente. Le risorse di telemetria sono un profilo Bicep separato, opt-in.
Vedi anche il [README dell'applicazione](README.md#model-monitoring-00a).

## Obiettivo

Separare tre domande: la richiesta ha funzionato, quanti token ha consumato,
e la risposta e' corretta rispetto al riferimento? Una risposta HTTP 200 non
garantisce una classificazione valida o corretta. Un segnale assente non e' zero.

| Domanda | Segnale | Confine |
| --- | --- | --- |
| Quante chiamate e quali esiti? | `ModelRequests`, dimensione `StatusCode` dove disponibile | Account Foundry, filtro `ModelDeploymentName`, aggregazione Sum |
| Quanti token? | `InputTokens`, `OutputTokens`, `TotalTokens` | Stessa finestra UTC e deployment; non sommare famiglie metriche equivalenti |
| Quanto tempo? | `TimeToLastByte` o `AzureOpenAITTLTInMS`; durata client | Disponibilita' e aggregazione da verificare; servizio e client non misurano lo stesso intervallo |
| Cosa e' successo a una richiesta? | Span client, trace ID e request ID | Application Insights richiede profilo e `--trace`; nessun join con log di piattaforma e' presunto |
| Classificazione corretta? | Quattro grader nativi `string_check` | `--evaluate`; accuratezza sulle classificazioni valide, da leggere con coverage |
| Segnali di rischio? | Quattro evaluator nativi hosted | `--evaluate-safety`; un campione benigno non certifica la sicurezza |
| Costo effettivo? | Azure Cost Management | I contatori di token non sono una fattura; metriche di costo preview restano stime |

Metriche e diagnostiche sono sull'**account**, valutazioni sul **progetto**.
Non usare `Latency`, `TotalCalls` o `TotalErrors` generici come sostituti dei
segnali specifici del modello. Le metriche RAI (`RAIHarmfulRequests`,
`RAIRejectedRequests`, `RAITotalRequests`) non coincidono con il rifiuto testuale
di un modello. Il dashboard e la continuous evaluation degli agenti non fanno
parte di questo companion senza agente.

## Flusso generale

```text
ambiente azd 00a -> deployment + dieci documenti sintetici
    -> dieci tentativi sequenziali, senza retry automatici
    -> esito HTTP, token, durata e classificazione
    -> [span client] [valutazione qualita'] [valutazione safety]
    -> report JSON locale senza contenuti o credenziali
```

## 1. Import, costanti e contratti riusati

Lo script riusa dal [benchmark](benchmark_documents-explained.md) documenti,
schema JSON, parser e funzioni di valutazione. Dal
[client condiviso](chat_completions-explained.md) riusa caricamento ambiente,
endpoint e autenticazione Azure CLI. Non duplica classificatore o evaluator.

`OUTPUT_TOKEN_LIMIT=128` limita l'output di ogni richiesta; il timeout e' 60
secondi, `max_retries=0`, `stream=False`. Il limite di dieci riguarda i tentativi
di inferenza, non il costo aggiuntivo degli evaluator. `utc_now()` produce
timestamp UTC e `uuid4()` identifica ogni run.

## 2. Caricamento della configurazione di tracing

`load_connection_string()` richiede `AZURE_MONITORING_ENABLED=true` e verifica
che l'Application Insights appartenga a subscription e resource group del
deployment. Solo allora legge la configurazione tramite Azure CLI. Non stampa
la connection string e non la salva nel report.

Il [profilo monitoring](../00a-foundry-core-public/infra/monitoring.bicep)
aggiunge Log Analytics con retention di 30 giorni, Application Insights con
`DisableLocalAuth=true`, connessione AppInsights e diagnostiche `Audit` e
`RequestResponse`. Non esporta `AllMetrics` e non abilita tutti i log.
Assegna al deployer Monitoring Reader su account e Application Insights,
Log Analytics Reader sul workspace e Monitoring Metrics Publisher su
Application Insights. Questi ruoli sono distinti da inferenza/evaluation.

La connessione Foundry usa metadata `ApiKey`, ma l'ingestione client usa
`AzureCliCredential`, non una chiave di autenticazione locale.

## 3. Classe `Telemetry`

Il provider OpenTelemetry isolato crea span di tipo **CLIENT**, con sampling
sempre attivo per questo piccolo campione. Non sono trace server del modello
o dell'agente. `CheckedExporter` registra export falliti e numero di span
accettati. `close()` esegue flush e shutdown, fallendo se l'export non riesce.
L'exporter riceve il provider esplicito e non usa storage offline.

`annotate_span()` esporta soltanto attributi operativi consentiti: modello,
run/document index, esito, durata, request/response ID e token. Non registra
prompt, risposte, eventi con messaggi o testo delle eccezioni.
L'accettazione dell'export non prova che i dati siano gia' interrogabili.

## 4. Raccolta delle osservazioni

`collect_observations()` rifiuta campioni diversi dai dieci documenti previsti.
Per ogni documento legge la risposta HTTP raw, conserva status e identificativi,
poi valida la classificazione. `token_usage()` accetta solo interi non negativi;
usage mancante resta `null`, non diventa zero.

Una classificazione malformata, troncata o rifiutata mantiene l'eventuale esito
HTTP ma non entra nelle righe di qualita'. Un errore di richiesta conserva solo
tipo, stato e ID disponibili e produce un diagnostico sanitizzato su stderr.
Le risposte testuali disponibili possono entrare nella valutazione safety anche
se la classificazione non e' valida. Prompt e risposte rimangono in memoria:
non vengono scritti nel report o negli span.

La durata HTTP e' acquisita prima del parsing della classificazione; la durata
complessiva dello span puo' includere altro lavoro client. Dieci misure non
sono un percentile di latenza rappresentativo di produzione.

## 5. Valutazioni native, senza un secondo giro di inferenza

`run_foundry_evaluation()` invia etichette predette e attese a quattro
`string_check`: tipo, reparto, priorita' e tutti i campi insieme.
Coverage = classificazioni valide / 10; accuratezza = pass rate fra quelle valide.

`run_safety_evaluation()` usa `builtin.violence`, `builtin.self_harm`,
`builtin.hate_unfairness`, `builtin.sexual` sui testi sintetici in memoria.
Rinomina `accuracy` in `pass_rate`: non e' accuratezza di business.
Disponibilita' regionale, autorizzazioni, risultati incompleti ed errori devono
essere verificati, non convertiti in un tasso di difetti zero.
Dataset e run di evaluation persistono in Foundry; possono comportare costi.

## 6. CLI e `main()`

`main()` valida la destinazione del report, carica la lane 00a e apre il client
diretto. Tracing e valutazioni sono indipendenti e richiesti esplicitamente.
Chiude i client, conserva le osservazioni anche se una valutazione fallisce,
verifica il conteggio degli span e scrive l'esito finale.

| Argomento | Significato |
| --- | --- |
| `--environment` | Ambiente azd 00a, obbligatorio |
| `--output` | File locale, default `monitoring-results.json`; directory padre gia' esistente |
| `--trace` | Export di span senza contenuti; richiede profilo e dipendenze opzionali |
| `--evaluate` | Evaluation nativa delle etichette |
| `--evaluate-safety` | Evaluation hosted dei testi sintetici |

| Exit code | Significato |
| --- | --- |
| `0` | Dieci classificazioni valide e operazioni richieste completate; accuratezza non necessariamente 100% |
| `1` | Run parziale, errore operativo/evaluation o tracing fallito |
| `2` | Configurazione, dipendenze o scrittura report non valide |

## Come eseguirlo

Da un clone completo, configura prima l'ambiente come nel
[README della lane](../00a-foundry-core-public/README.md). Per un nuovo
laboratorio, solo dopo approvazione di risorse e costi, dalla root:

```bash
scripts/bootstrap-scenario-env.sh 00-foundry-core/00a-foundry-core-public \
  --new-instance --environment monitoring --location swedencentral
cd scenarios/00-foundry-core/00a-foundry-core-public
environment=<generated-azd-environment>
azd env set AZURE_ENABLE_MONITORING true --environment "$environment"
azd provision --environment "$environment"
```

Per usare una lane gia' autorizzata, non creare un nuovo laboratorio. Verifica
prima subscription, resource group, metric definitions e categorie diagnostiche:

```bash
account_id=$(azd env get-value AZURE_AI_ACCOUNT_ID --environment "$environment")
az monitor metrics list-definitions --resource "$account_id" --output json
az monitor diagnostic-settings categories list --resource "$account_id" --output json
```

Dalla directory applicazione:

```bash
cd ../app
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-monitoring.txt
python monitor_model.py --environment "$environment" --trace --evaluate --evaluate-safety
```

Senza `--trace` bastano le dipendenze base. Ogni comando avvia un **nuovo run**
di massimo dieci richieste: non valuta un report precedente.
Usa Microsoft Foundry **new**, mai classic. Azure portal Monitor > Metrics
sull'account e' una superficie alternativa per i contatori del modello.

## Come interpretare i risultati

Il report ignorato da Git contiene confini UTC, coverage, status, ID, token e
durate, non messaggi, etichette o credenziali. Interroga metriche e trace nella
stessa finestra e deployment, con margine per bucket e ingestione. Per gli span
nel workspace:

```kusto
AppDependencies
| where TimeGenerated > ago(1h)
| where AppRoleName == "foundry-notes-00a-monitoring"
| where tostring(Properties["monitoring.run_id"]) == "<run-id>"
| project TimeGenerated, Name, OperationId, DurationMs, Success,
    InputTokens=Properties["gen_ai.usage.input_tokens"],
    OutputTokens=Properties["gen_ai.usage.output_tokens"]
```

Nel contesto application-scoped lo schema equivalente usa `dependencies`,
`customDimensions`, `operation_Id`, `duration` e `cloud_RoleName`: non mescolare
le due tabelle. Per le diagnostiche verifica prima `AzureDiagnostics | getschema`,
poi conta righe per `_ResourceId`, categoria e intervallo senza leggere body.
Nessun dato puo' significare ritardo, scope/finestra errati o permessi insufficienti.

## Evidenza storica: 2026-11-01, Sweden Central

Una sola esecuzione con `gpt-4.1-mini`, versione `2025-04-14`, GlobalStandard,
capacita' 30:

| Segnale | Risultato osservato |
| --- | --- |
| Inferenza e coverage | Dieci HTTP 200, dieci classificazioni valide |
| Token | 3.813 input + 147 output = 3.960; client e piattaforma coincidono |
| Trace | Dieci trace ID originali trovati in `AppDependencies`; somme token coincidenti |
| Latenza servizio | `AzureOpenAITTLTInMS` media 149,6 ms nel bucket popolato; client circa 654-2.538 ms |
| Qualita' | Tipo 100%, reparto 100%, priorita' 50%, tutti i campi 50%; coverage 100% |
| Safety | Quattro evaluator passati su dieci risposte benigne ciascuno |
| Log e RAI | Routing configurato, ma nessuna riga diagnostica e nessuna serie RAI interrogata |

La finestra metriche era 19:00-19:05 UTC, con bucket popolato alle 19:02.
`TimeToLastByte` era discoverable ma senza serie. Il warning iniziale
sull'exporter e' stato corretto passando il provider isolato: test offline e
un controllo separato di un solo span, senza inferenza, non un nuovo run dei
dieci documenti.

Una regola temporanea senza action group ha raggiunto `Fired` alle 19:43:36 UTC:
`ModelRequests` Sum > 0, filtro deployment, valutazione ogni minuto e finestra
di un'ora per riusare le richieste esistenti. E' stata rimossa e la sua assenza
verificata. Non sono state inviate notifiche o nuove chiamate modello.
Screenshot, rendering nella Foundry Traces UI e walkthrough del portale non
sono verificati. Il laboratorio risultava ancora attivo alla data del run:
non e' una verifica del suo stato attuale.

## Perche' questa struttura e' utile

```bash
python -m unittest -v test_monitor_model.py test_benchmark_documents.py test_chat_completions.py
```

I mock verificano limiti, parsing, privacy del report, evaluation e fallimenti
di export, senza chiamare Azure. I test del contratto SDK di tracing richiedono
le dipendenze opzionali; altrimenti vengono indicati come skipped. Nessun test
unitario dimostra ingestione live, permessi, disponibilita' regionale o qualita'.

## Costi, stato e pulizia

Inferenza, evaluation, ingestione/retention Log Analytics e alert possono avere
costi distinti. Non viene creata automaticamente una regola di alert.
Disabilitare `AZURE_ENABLE_MONITORING` **non elimina** risorse precedenti:
ARM incremental le mantiene, con possibili costi e ingestione residui.

Per cleanup selettivo verifica gli ID esatti, eventuale condivisione e ruoli,
rimuovi prima routing diagnostico e connessione, poi le destinazioni e gli
eventuali alert del laboratorio. Non eliminare account o modello soltanto per
fermare monitoring. Nessun cleanup e' automatico o autorizzato da questa guida.

## Limiti intenzionali e riferimenti

Campione sintetico minimo, nessun carico concorrente o stress test, nessuna
continuous evaluation agente. Un rifiuto non e' un outage; un campione benigno
non certifica safety. La verifica live storica non garantisce risultati futuri.

- [Monitor models](https://learn.microsoft.com/azure/foundry/foundry-models/how-to/monitor-models)
- [Metriche e log](https://learn.microsoft.com/azure/foundry/openai/monitor-openai-reference)
- [Evaluation](https://learn.microsoft.com/azure/foundry/concepts/evaluation-overview)
- [Safety evaluator](https://learn.microsoft.com/azure/foundry/concepts/evaluation-evaluators/risk-safety-evaluators)
- [Tracing e privacy](https://learn.microsoft.com/azure/foundry/observability/how-to/trace-agent-setup)
- [Confine dashboard agente](https://learn.microsoft.com/azure/foundry/observability/how-to/how-to-monitor-agents-dashboard)
