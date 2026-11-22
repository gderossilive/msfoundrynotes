# Guida a `usage_report.py`

Questa guida spiega [`usage_report.py`](usage_report.py) e le metriche d'uso opzionali del
gateway API Management dello scenario `00c` (livello 00, lane c), o del
[Public Gateway 00a](public_gateway-explained.md) selezionato con `--scenario 00a`.

Lo script non crea risorse: legge un ambiente `azd` in cui le metriche sono state attivate e
produce un resoconto dei token consumati da ciascun chiamante. Non è una fattura e non è un agente.

## Obiettivo

Rispondere a «chi ha consumato quanti token?» e verificare che il numero sia credibile,
confrontandolo con due fonti indipendenti:

1. le metriche di piattaforma del deployment del modello (`InputTokens`, `OutputTokens`);
2. gli header `x-foundrylab-consumed-tokens` registrati da [`token_limit_demo.py`](token_limit_demo.py).

## Come funziona la raccolta

Con `AZURE_APIM_USAGE_METRICS=true`, `scripts/apply-00c-apim-policy.sh` distribuisce
[`foundry-usage-metrics`](../../../modules/apim/foundry-usage-metrics/main.bicep) insieme alla policy:

- un workspace Log Analytics (30 giorni) e un Application Insights collegato, con
  `DisableLocalAuth` attivo: si invia solo con identità Entra;
- un logger API Management con `identityClientId: systemAssigned` e il ruolo
  `Monitoring Metrics Publisher` per la managed identity del gateway, limitato a quella risorsa;
- una diagnostica sull'API con `metrics: true`. Nessun body di richiesta o risposta è configurato,
  quindi prompt e risposte non vengono registrati; `alwaysLog: allErrors` registra solo gli errori.

La policy aggiunge `llm-emit-token-metric` dopo l'autorizzazione, con una sola dimensione,
`Caller`, presa dall'object ID già validato. Non si usano header del client.

```text
token validato -> allowlist -> [limite] -> llm-emit-token-metric(Caller) -> Foundry
                                                  |
                                 Application Insights (Entra) -> tabella AppMetrics
```

## Cosa si trova in `AppMetrics`

Nel run live del 2026-11-02 il workspace (basato su Application Insights) ha ricevuto i dati nella
tabella `AppMetrics`, non in `customMetrics`:

- `Prompt Tokens`, `Completion Tokens`, `Completion Reasoning Tokens`, `Total Tokens` e altri
  dettagli (cache, audio, predizioni), ciascuno con la dimensione `Caller` in `Properties`;
- gli stessi dati, in parallelo, come metrica `azure.ai_gateway.client.token.usage` con la
  dimensione `gen_ai.token.type`.

**Le due famiglie descrivono le stesse richieste: sommarle raddoppia i totali.** Lo script usa
solo i nomi esatti della prima famiglia. I token di ragionamento sono già inclusi nei
`Completion Tokens`: sono mostrati a parte e non vengono aggiunti al costo.

## Flusso generale

```text
azd env (00c o 00a) -> workspace + account -> query KQL su AppMetrics (per Caller)
                                     -> az monitor metrics list (modello)
                                     -> confronto e report JSON locale
```

- `--caller ETICHETTA=OBJECT_ID` assegna un nome leggibile; un chiamante senza etichetta compare come
  `unlabeled-` più otto caratteri, mai con l'object ID completo. Il report non contiene object ID.
- Per confrontare gli header, le etichette devono coincidere con quelle di `token_limit_demo.py` (`A`, `B`).
- `--since`/`--until` (UTC) delimitano la finestra; di default l'ultima ora. Gli estremi sono
  arrotondati ai minuti interi, perché le metriche del modello sono in bucket da un minuto: così le
  due fonti coprono lo stesso traffico. Se i totali divergono, lo script lo segnala: chiamate fatte
  negli stessi minuti senza la metrica del gateway (prima dell'attivazione, o aggirando il gateway)
  compaiono come differenza. Nel secondo run live una sola chiamata di prova, fatta a metriche
  spente nello stesso minuto dell'inizio, ha dato 11 token di input e 10 di output in più; spostando
  l'inizio al minuto successivo i totali sono tornati uguali.
- Il costo è calcolato solo se passi `--price-input-per-million` e `--price-output-per-million`:
  prezzi tuoi, nessun valore predefinito. Resta una stima dai token, non una fattura.
- `model_minus_gateway_input/output` quantifica la differenza modello-gateway.
  In 00a una chiamata diretta puo' aggirare APIM: nel run del 2026-11-02 due
  chiamate dirette hanno prodotto una differenza esatta di 28 token input e 6 output.
  La divergenza resta un esito nonzero anche quando e' intenzionale nella demo.

## Lettura del codice

### 1. Import, costanti e contratto dei dati

Lo script usa la libreria standard Python e riusa `ConfigurationError`,
`LANE_DIRECTORIES` e `load_deployment` del [client condiviso](chat_completions.py).
Non introduce un secondo sistema di autenticazione o una seconda mappa delle lane.
`GUID_PATTERN` valida gli identificativi, `LABEL_PATTERN` le etichette e
`RESOURCE_ID_PATTERN` l'ID Azure dell'account. `METRIC_KINDS` associa quattro
nomi esatti ai contatori `prompt`, `completion`, `reasoning` e `total`.
Non ci sono classi dati: query e report usano dizionari.

### 2. Finestra temporale, etichette e ambiente

`utc_now`, `parse_moment` e `iso` normalizzano le date; una data senza fuso
viene interpretata come UTC. `align_window` arrotonda l'inizio verso il basso
e la fine verso l'alto al minuto intero. Non restringe quindi la finestra:
puo' includere altre richieste negli stessi minuti.

`parse_caller_labels` legge le opzioni ripetute `--caller` e normalizza
l'object ID in minuscolo. Usare etichette diverse per chiamanti diversi:
l'aggregazione avviene per etichetta. `load_deployment` verifica che l'ambiente
sia legato alla lane scelta; `read_environment_values` legge anche gli output
del workspace e dell'account. `main` richiede entrambi gli identificativi validi.

### 3. Query del gateway e del modello

`run_az` esegue Azure CLI e interpreta il JSON; un comando fallito o un JSON
non valido genera un errore esplicito. `build_usage_query` limita la query
alla finestra, ai quattro nomi esatti e alla dimensione `Properties["Caller"]`.
`query_gateway_usage` usa `az rest` verso Log Analytics e trasforma colonne
e righe della prima tabella in dizionari.

`metric_kind` e `aggregate_gateway_rows` raggruppano i token per etichetta,
ignorando metriche estranee e righe senza chiamante. `query_model_tokens`
legge `InputTokens` e `OutputTokens` con `az monitor metrics list`, filtrando
`ModelDeploymentName` e sommando bucket `PT1M` con aggregazione `Total`.
Le query usano il login Azure CLI del lettore, non l'identita' del gateway.

### 4. Riconciliazione e costo

`reconcile` confronta prompt e completion del gateway con input e output
del modello. Le differenze `model_minus_gateway_input/output` sono firmate:
un valore positivo indica token visti dal modello ma non dalla metrica APIM;
non dimostra da solo un bypass.

`load_demo_totals` somma gli header di consumo delle sole osservazioni con
stato `200` nel report della demo. Il confronto usa l'unione delle etichette:
un chiamante presente in una sola fonte non viene ignorato.
`estimate_cost` richiede entrambi i prezzi e non aggiunge di nuovo i token
di ragionamento, gia' inclusi nelle completion. L'unita' monetaria e' quella
dei prezzi forniti; il programma non consulta un listino.

### 5. Argomenti, report e `main`

`parse_args` richiede l'ambiente, limita la lane a `00a` o `00c` e rifiuta
prezzi negativi o forniti a meta'. `main` valida la finestra, legge le due
fonti e, facoltativamente, il report della demo. Senza dati del gateway
restituisce `3` e non scrive un nuovo report.

`build_report` produce `window`, `callers`, `reconciliation` e `cost_note`;
`print_summary` mostra gli stessi contatori nel terminale. `main` scrive
il JSON locale e restituisce `1` se almeno un confronto non coincide.
In questo caso il report viene conservato per capire la differenza, non
presentato come una riconciliazione riuscita.

## Argomenti e codici di uscita

| Argomento | Default / significato |
| --- | --- |
| `--environment` | Obbligatorio: ambiente azd gia' distribuito |
| `--scenario` | `00c`; `00a` richiede il suo gateway opzionale |
| `--caller LABEL=OBJECT_ID` | Ripetibile; senza etichetta viene usato un prefisso dell'ID |
| `--since`, `--until` | Ultima ora; date ISO 8601, preferibilmente con `Z` |
| `--demo-report` | Facoltativo: report locale di `token_limit_demo.py` |
| `--price-input-per-million`, `--price-output-per-million` | Nessuna stima senza entrambi i prezzi |
| `--output` | `usage-report.json` nella directory dello script |

| Codice | Significato |
| --- | --- |
| `0` | Dati trovati e confronti riusciti |
| `1` | Un confronto non coincide, oppure errore di Azure CLI |
| `2` | Configurazione non valida (metriche non attive, etichette, finestra) |
| `3` | Nessun dato ancora nella finestra: l'ingestione può richiedere alcuni minuti |

## Come eseguirlo

Prima distribuire la [lane 00c](../00c-foundry-core-byo-vnet/README.md) e
applicare la policy con i chiamanti autorizzati. Il lettore deve avere
permessi di query sul workspace e di lettura delle metriche sull'account
Foundry, oltre al login Azure CLI. Il ruolo di pubblicazione assegnato
alla managed identity di APIM non concede questi permessi al lettore.

I comandi seguenti partono dalla directory `scenarios/00-foundry-core/app/`.
L'attivazione del profilo distribuisce risorse di telemetria e richiede
permessi e budget separati; il solo script Python esegue letture.

```bash
environment="<your-00c-azd-environment>"
(
  cd ../00c-foundry-core-byo-vnet
  azd env set AZURE_APIM_USAGE_METRICS true --environment "$environment"
)
bash ../../../scripts/apply-gateway-policy.sh 00c "$environment"
python3 usage_report.py --environment "$environment" --scenario 00c
```

La metrica vede solo richieste successive all'attivazione. Per generare
traffico sintetico si puo' eseguire, con autorizzazione ai costi di inferenza,
la [demo del limite](token_limit_demo-explained.md); richiede un budget
positivo e un secondo chiamante gia' autenticato. Attendere l'ingestione,
poi confrontare una finestra che includa tutte e sole le chiamate della demo:

```bash
python3 usage_report.py --environment "$environment" --scenario 00c \
  --caller "A=<caller-a-entra-object-id>" \
  --caller "B=<caller-b-entra-object-id>" \
  --since "<start-utc-iso8601>" --until "<end-utc-iso8601>" \
  --demo-report token-limit-results.json
```

Sostituire i segnaposto con valori reali locali; non aggiungerli a Git.
Le etichette A e B devono coincidere con quelle della demo. Omettere
`--demo-report` se non si vuole quel confronto; altre chiamate nella stessa
finestra possono farlo fallire. Per stimare il costo, aggiungere entrambi
i prezzi per milione relativi al modello e al contratto effettivi.

## Come interpretare i risultati

Nel run storico del **2026-11-02, Italy North**, poi ripetuto dopo il
refactor della policy, i totali erano:

| Fonte | Risultato |
| --- | --- |
| Gateway | 143 prompt + 650 completion = 793 token |
| Metriche del modello | 143 input + 650 output |
| Header per chiamante | A: 716; B: 77 |
| Ragionamento | 640 token, gia' compresi nei 650 di completion |

Il codice restituisce `0` solo se i confronti richiesti coincidono. Un `3`
non equivale a zero consumi: puo' significare ingestione incompleta o
finestra errata. Un `1` richiede l'esame della finestra, delle etichette
e del traffico non contabilizzato. Non azzerare artificialmente la differenza.
Questi risultati sono evidenze storiche, non un nuovo run di pubblicazione
ne' una misura rappresentativa di carico o costi di produzione.

## Costi, stato e pulizia

`usage_report.py` non crea risorse, non chiama il modello e non modifica
policy o identita'. Le query possono avere costi propri. L'attivazione
del profilo crea Log Analytics e Application Insights; APIM Developer,
rete privata, ingestione e inferenza hanno costi distinti.

Il report locale predefinito e' gitignored. Le etichette e i prefissi degli
ID restano informazioni pseudonime: non usare dati personali nelle etichette
e non pubblicare report o stato azd. I laboratori e i secondi chiamanti dei
run storici citati sono stati rimossi; nessun laboratorio viene creato
da questa pubblicazione.

Impostare le metriche a `false` e riapplicare la policy non elimina le
risorse di telemetria gia' create. Per un laboratorio usa-e-getta,
verificare l'ambiente e seguire la
[pulizia della lane](../00c-foundry-core-byo-vnet/README.md#cleanup).
Un eventuale secondo chiamante creato dalla demo ha una pulizia separata.

## Limiti da tenere presenti

- L'uguaglianza richiede che tutto il traffico del deployment nella finestra sia
  contabilizzato dal gateway. In 00a il ruolo diretto del deployer permette bypass;
  anche in 00c altri percorsi privati o chiamate a metriche spente romperebbero il confronto.
- Ogni dimensione ha un limite di 100 valori distinti e ogni namespace di 1.000 serie attive: oltre,
  i dati sono scartati in silenzio. Con pochi chiamanti non è un problema.
- L'object ID è un identificativo pseudonimo, salvato in chiaro in Log Analytics per 30 giorni.
- Non è stato attivato il pulsante del portale «Custom metrics (Preview) con dimensioni»: i dati
  basati su log sono arrivati comunque; la vista in Metrics Explorer non è stata verificata.
- Il percorso con Event Hub e Cosmos DB per il dettaglio per singola richiesta non è incluso.

## Come eseguire i test

Da questa directory:

```bash
python3 -m unittest -v test_usage_report.py test_token_limit_demo.py
```

Le funzioni separate permettono di simulare Azure CLI, righe KQL e header:
i test coprono nomi esatti, finestre, ragionamento, differenze, report ed
esiti nonzero senza chiamare Azure. Non provano disponibilita' regionale,
ingestione live, qualita' del modello o capacita' di produzione.

Per gli altri comandi, vedere l'[app README](README.md#per-caller-usage-attribution-00c).
