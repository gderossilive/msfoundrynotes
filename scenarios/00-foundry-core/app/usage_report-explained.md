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

## Flusso dello script

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

## Codici di uscita

| Codice | Significato |
| --- | --- |
| `0` | Dati trovati e confronti riusciti |
| `1` | Un confronto non coincide, oppure errore di Azure CLI |
| `2` | Configurazione non valida (metriche non attive, etichette, finestra) |
| `3` | Nessun dato ancora nella finestra: l'ingestione può richiedere alcuni minuti |

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

```bash
python3 -m unittest -v test_usage_report.py
```

I test simulano Azure CLI e non chiamano Azure.
