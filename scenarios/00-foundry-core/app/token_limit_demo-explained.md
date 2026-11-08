# Guida a `token_limit_demo.py`

Questa guida spiega [`token_limit_demo.py`](token_limit_demo.py) e il limite di token
opzionale del gateway API Management dello scenario `00c` (livello 00, lane c),
oppure del [Public Gateway 00a](public_gateway-explained.md) con `--scenario 00a`.
Vedi il [README applicazione](README.md#per-caller-token-governance-00a00c).

Lo script non crea risorse: usa un ambiente `azd` già distribuito, con la policy del gateway
applicata e il limite attivo. Non è un agente e non è un test di carico.

## Obiettivo

Mostrare tre comportamenti osservabili:

1. un chiamante (A) che supera il proprio budget riceve `429` con `Retry-After`;
2. un secondo chiamante (B), con un altro object ID Entra, non è influenzato;
3. dopo l'attesa indicata, A torna a ricevere `200`.

## Come funziona il limite

Il Bicep [`apim-policy.bicep`](../00c-foundry-core-byo-vnet/infra/apim-policy.bicep) passa il
parametro `tokensPerMinute` (default `0`, limite disattivato) al modulo condiviso
[`foundry-chat-policy`](../../../modules/apim/foundry-chat-policy/main.bicep), che compone la policy.
Quando il valore è maggiore di zero, la
policy inserisce `llm-token-limit` dopo la validazione del token e l'allowlist, e prima che il
gateway ottenga il proprio token verso Foundry:

```text
validate-azure-ad-token -> allowlist (oid) -> llm-token-limit -> managed identity -> Foundry
```

- `counter-key` usa `caller-object-id`, già estratto dal token validato. Non si usano header
  forniti dal client né l'indirizzo IP.
- `estimate-prompt-tokens="false"`: il conteggio usa i token riportati dalla risposta del
  modello. Una richiesta può quindi superare il budget prima che il contatore lo registri.
- Le risposte riuscite includono `x-foundrylab-consumed-tokens` e `x-foundrylab-remaining-tokens`.

Il valore si imposta con `AZURE_APIM_TOKENS_PER_MINUTE` nell'ambiente `azd` e si applica con
`scripts/apply-00c-apim-policy.sh`. Il secondo chiamante si gestisce con
`scripts/manage-00c-second-caller.sh` (service principal senza ruoli Azure, certificato di un
giorno, profilo Azure CLI separato in `.azure/`, rimosso dal `cleanup`).

## Flusso dello script

```text
azd env (00c o 00a) -> load_deployment -> due client (profilo A, profilo B)
   A: richieste limitate fino a 429 (max --max-calls)
   B: una richiesta
   A: attesa Retry-After (max 90 s + 1) e una richiesta
   -> verdetto e report JSON locale
```

- Ogni client è creato con `max_retries=0`: i retry automatici dell'SDK nasconderebbero il `429`.
- Il token Entra è ottenuto con `az account get-access-token`, usando `AZURE_CONFIG_DIR` per B.
- Ogni richiesta ha un prompt fisso e `max_completion_tokens=64`.
- Il report (`token-limit-results.json`, ignorato da Git) contiene stato, contatori e tempi:
  mai prompt, risposte o token di accesso. I chiamanti sono etichettati A e B, non con gli object ID.

## Funzioni, argomenti ed esecuzione

`Observation` e' una dataclass immutabile: etichetta A/B, esito HTTP,
contatori, Retry-After, durata e timestamp. `header_int()` interpreta gli header,
lasciando `None` se mancanti o non numerici. `az_token_provider()` ottiene il token
tramite Azure CLI nel profilo selezionato senza salvarlo nel report.

`send_request()` legge status e header sia dalla risposta raw sia dagli errori
HTTP; gli errori di connessione non diventano risposte riuscite.
`run_demo()` ferma A al primo 429 o errore inatteso, poi verifica B e recupero A.
`retry_wait_seconds()` usa Retry-After o 60 secondi di default, con tetto di
90 secondi piu' un secondo. `main()` carica la lane e i client, stampa il
verdetto e scrive il report; non riapplica la policy.

| Argomento | Significato |
| --- | --- |
| `--environment` | Ambiente azd, obbligatorio |
| `--scenario` | `00c` di default; `00a` richiede il gateway opt-in |
| `--caller-b-config-dir` | Profilo Azure CLI gia' autenticato come B, obbligatorio |
| `--max-calls` | 15 di default; da 1 a 50, limite ai tentativi iniziali di A |
| `--output` | Report locale, default `token-limit-results.json` |

Dalla root, dopo provisioning, allowlist e budget autorizzati:

```bash
scripts/manage-second-caller.sh 00c create <azd-environment-name>
scripts/apply-gateway-policy.sh 00c <azd-environment-name>
cd scenarios/00-foundry-core/app
python token_limit_demo.py --environment <azd-environment-name> --scenario 00c \
  --caller-b-config-dir ../../../.azure/00c-second-caller/<azd-environment-name>/az
```

Per 00a sostituisci lane e percorso del profilo con `00a`. Il budget Basic v2
puo' richiedere un valore inferiore per raggiungere il 429 nel campione limitato.

## Codici di uscita

| Codice | Significato |
| --- | --- |
| `0` | Limite applicato, B non influenzato, A recuperato |
| `1` | Almeno una condizione non verificata, oppure errore di richiesta |
| `2` | Configurazione non valida (ambiente, profilo di B) |

Se il limite non viene raggiunto entro `--max-calls`, lo script lo dice: controllare che
`AZURE_APIM_TOKENS_PER_MINUTE` sia maggiore di zero e che la policy sia stata riapplicata.

## Limiti da tenere presenti

- Il gateway di `00c` usa il livello Developer, con una sola istanza: non rappresenta la
  produzione. I contatori dei livelli classici usano una finestra scorrevole.
- Il gateway 00a Basic v2 usa invece token bucket: il refill modifica residui e Retry-After.
  Nel run del 2026-11-02 con `gpt-4.1-mini`, budget 120 token/min, A ha avuto nove
  200, poi 429 con Retry-After 3 secondi, B 200 e A recuperato. Il budget 600 non
  era stato raggiunto entro 15 chiamate. Non e' un risultato garantito a ogni run.
- Con lo streaming i token sono stimati; non è il percorso mostrato qui.
- Un `429` non dice da solo quale livello lo ha prodotto (gateway o modello). Nel run live del
  2026-11-02 il `429` del gateway portava `Retry-After` e `x-foundrylab-remaining-tokens: 0`, senza
  l'header dei token consumati; un `429` del modello non e' stato provocato, quindi la distinzione
  non e' dimostrata.
- Il budget e' per gateway e per minuto: non sostituisce capacità del deployment, filtri di
  contenuto né attribuzione dei costi (tema dell'episodio successivo).
- Il run live (2026-11-02) e' una sola esecuzione con un prompt breve: mostra il meccanismo, non
  e' una misura. Una richiesta iniziata sotto il budget puo' terminare sopra di esso (9 chiamate,
  639 token su 600), come atteso con `estimate-prompt-tokens="false"`.

## Come eseguire i test

```bash
python3 -m unittest -v test_token_limit_demo.py
```

I test simulano il client e non chiamano Azure.

## Costi e pulizia

La demo consuma token; APIM rimane fatturabile anche inattivo. Il certificato di
B scade dopo un giorno, ma questo non elimina app registration o service principal.
Dalla root rimuovi solo il secondo chiamante registrato e riapplica l'allowlist:

```bash
scripts/manage-second-caller.sh 00c cleanup <azd-environment-name>
scripts/apply-gateway-policy.sh 00c <azd-environment-name>
```

Per 00a usa `00a`. I lab live del 2026-11-02 sono stati rimossi. Il cleanup del
resource group e' un'operazione separata, dopo verifica del target nella lane.
Questo companion non registra una cronologia di budget e non pubblica
l'episodio separato Usage Attribution.
