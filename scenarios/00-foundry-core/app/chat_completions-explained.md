# Guida a `chat_completions.py`

Questa guida spiega, con un approccio didattico, com'è composto e come funziona
[`chat_completions.py`](chat_completions.py).

Lo script è un'applicazione da riga di comando molto piccola: legge la
configurazione dello scenario Microsoft Foundry `00a` già distribuito,
autentica l'utente con Azure CLI, invia un singolo prompt al modello e stampa
la prima risposta testuale ricevuta.

Non crea risorse Azure e non distribuisce un'applicazione. Inoltre, non è un
agente: non usa strumenti, memoria, retrieval o un ciclo autonomo.

## Obiettivo dello script

Il client chiama direttamente l'endpoint pubblico OpenAI v1 del modello
distribuito dallo scenario `00a-foundry-core-public`:

```text
https://<account>.services.ai.azure.com/openai/v1/
```

L'accesso è keyless. Lo script usa un token Microsoft Entra ID appartenente
all'utente connesso ad Azure CLI e non legge né memorizza API key.

## Flusso generale

L'esecuzione segue questi passaggi:

```text
Argomenti della CLI
        |
        v
Lettura dell'ambiente azd della lane 00a
        |
        v
Validazione della configurazione
        |
        v
Costruzione dell'endpoint Foundry
        |
        v
Autenticazione con AzureCliCredential
        |
        v
Creazione del client OpenAI
        |
        v
Invio di un messaggio con ruolo "user"
        |
        v
Validazione e stampa della risposta
```

Il punto di ingresso è `main()`, ma il lavoro è suddiviso in funzioni piccole,
ognuna con una responsabilità precisa.

## 1. Import e costanti

Lo script usa moduli della libreria standard nella fase iniziale:

- `argparse` interpreta gli argomenti della riga di comando;
- `json` decodifica l'output di `azd`;
- `re` valida i valori letti dall'ambiente;
- `subprocess` esegue Azure Developer CLI;
- `sys` gestisce `stderr` e il codice di uscita;
- `dataclass` definisce un oggetto di configurazione immutabile;
- `Path` costruisce percorsi indipendenti dalla directory corrente;
- `Any` e `Sequence` descrivono i tipi usati dalle funzioni.

Le dipendenze Azure e OpenAI vengono importate solo quando servono, dentro le
relative funzioni.

### Scope del token

```python
TOKEN_SCOPE = "https://ai.azure.com/.default"
```

Questo è lo scope richiesto a Microsoft Entra ID per ottenere il token con cui
viene chiamato Foundry.

### Directory della lane

```python
LANE_DIRECTORY = (
    Path(__file__).resolve().parent.parent / "00a-foundry-core-public"
)
```

Gli ambienti `azd` sono locali alla directory del progetto che li ha creati.
Per questo lo script esegue `azd` dalla directory della lane `00a`, anche se il
comando Python viene lanciato dalla directory `app`.

### Espressioni regolari

Due pattern controllano che i valori recuperati da `azd` abbiano la forma
attesa:

- `ACCOUNT_PATTERN` valida il nome dell'account Foundry;
- `MODEL_PATTERN` valida il nome del deployment.

Questi controlli intercettano configurazioni mancanti o malformate prima di
effettuare una chiamata di rete.

## 2. `ConfigurationError`

```python
class ConfigurationError(RuntimeError):
    pass
```

Questa eccezione distingue gli errori di configurazione dagli errori restituiti
dalle API. Alcuni esempi sono:

- ambiente `azd` inesistente o associato a una lane diversa da `00a`;
- account o deployment mancanti;
- output `azd` non valido;
- prompt vuoto.

In `main()` questi errori producono un messaggio chiaro su `stderr` e il codice
di uscita `2`.

## 3. Il modello dati `Deployment`

`Deployment` raccoglie la configurazione necessaria per una chiamata:

```python
@dataclass(frozen=True)
class Deployment:
    account_name: str
    model_deployment_name: str
```

L'opzione `frozen=True` rende l'istanza immutabile dopo la creazione. In questo
modo la configurazione validata non può essere modificata accidentalmente.

La proprietà `base_url` costruisce l'endpoint OpenAI v1 diretto:

```text
https://<account>.services.ai.azure.com/openai/v1/
```

## 4. Caricamento della configurazione

La funzione `load_deployment(environment_name)` trasforma un ambiente `azd` in
un oggetto `Deployment` affidabile.

### Esecuzione di `azd`

La funzione esegue:

```text
azd env get-values --environment <nome> --output json
```

Il comando viene avviato dalla directory della lane `00a`. Lo script cattura
sia `stdout` sia `stderr` e controlla esplicitamente il codice di uscita.

Se `azd` non è installato, oppure il comando fallisce, viene sollevato un
`ConfigurationError` che conserva il dettaglio diagnostico disponibile.

### Decodifica e verifica

L'output deve essere un oggetto JSON. Successivamente la funzione verifica che:

1. `FOUNDRY_SCENARIO_LANE_ID` sia esattamente `00a`;
2. `AZURE_AI_ACCOUNT_NAME` sia presente e valido;
3. `AZURE_AI_MODEL_DEPLOYMENT_NAME` sia presente e valido.

Solo dopo tutti i controlli viene creato e restituito `Deployment`. Il resto
del programma lavora quindi con dati già validati.

## 5. Autenticazione e client OpenAI

`create_openai_client(base_url)` crea il client che invierà la richiesta:

```python
token_provider = get_bearer_token_provider(
    AzureCliCredential(),
    TOKEN_SCOPE,
)
return OpenAI(base_url=base_url, api_key=token_provider)
```

Il flusso è il seguente:

1. `AzureCliCredential` usa l'identità con cui è stato eseguito `az login`;
2. `get_bearer_token_provider` crea una funzione che richiede e rinnova i token;
3. il provider viene passato al parametro `api_key` del client OpenAI;
4. il client usa il token Entra ID come credenziale Bearer per le richieste.

Non viene letta né memorizzata una API key.

L'uso esplicito di `AzureCliCredential`, invece di una catena più ampia come
`DefaultAzureCredential`, rende prevedibile l'identità usata dal tutorial:
è quella attualmente connessa ad Azure CLI.

## 6. Invio del prompt

`complete_prompt(client, deployment, prompt)` esegue una singola Chat
Completion.

Prima rimuove gli spazi iniziali e finali:

```python
normalized_prompt = prompt.strip()
```

Un prompt vuoto viene rifiutato. Quindi viene inviata questa richiesta:

```python
client.chat.completions.create(
    model=deployment.model_deployment_name,
    messages=[{"role": "user", "content": normalized_prompt}],
)
```

Due aspetti sono importanti:

- `model` contiene il **nome del deployment**, non necessariamente il nome del
  modello nel catalogo;
- `messages` contiene un solo messaggio con ruolo `user`, quindi lo script non
  mantiene una conversazione tra esecuzioni.

Infine la funzione controlla che esista almeno una scelta, prende
`choices[0].message.content`, verifica che sia testo non vuoto e restituisce la
risposta senza spazi superflui.

## 7. Argomenti della riga di comando

`parse_args()` definisce due argomenti:

| Argomento | Obbligatorio | Significato |
|---|---:|---|
| `--environment` | sì | Nome dell'ambiente `azd` `00a` già provisionato |
| `prompt` | sì | Testo da inviare al modello |

## 8. Orchestrazione in `main()`

`main()` collega tutte le parti:

```text
parse_args()
    -> load_deployment()
    -> create_openai_client()
    -> complete_prompt()
    -> print()
```

La gestione degli errori assegna un significato preciso ai codici di uscita:

| Codice | Significato |
|---:|---|
| `0` | Risposta ricevuta e stampata |
| `1` | Errore di connessione o stato HTTP restituito dall'API |
| `2` | Configurazione o input non validi |

Gli errori sono scritti su `stderr`, mentre una risposta valida viene scritta
su `stdout`. Questa distinzione permette di usare lo script anche in pipeline
o comandi shell.

Il blocco finale:

```python
if __name__ == "__main__":
    raise SystemExit(main())
```

esegue `main()` solo quando il file viene avviato direttamente e restituisce al
sistema operativo il codice prodotto dalla funzione. Se il modulo viene
importato nei test, `main()` non parte automaticamente.

## Esempio di esecuzione

```bash
python chat_completions.py \
  --environment <ambiente-00a> \
  "Spiega Microsoft Foundry in una frase."
```

## Come interpretare gli errori

| Sintomo | Possibile causa |
|---|---|
| `Azure Developer CLI ... was not found` | `azd` non è installato o non è nel `PATH` |
| Ambiente non leggibile | Nome errato o ambiente creato in un'altra lane |
| Errore di binding della lane | L'ambiente non appartiene a `00a` |
| `401` | Identità assente, token non valido o ruolo mancante |
| `403` | L'utente Azure CLI non è autorizzato sul modello |
| Nessuna choice o testo vuoto | Il servizio non ha restituito una risposta utilizzabile |

## Perché questa struttura è utile

Anche se lo script è breve, applica alcune buone pratiche:

- separa parsing, configurazione, autenticazione e chiamata al modello;
- valida i dati prima di costruire l'endpoint o inviare richieste;
- controlla la lane per evitare di usare l'ambiente sbagliato;
- usa autenticazione keyless con Microsoft Entra ID;
- conserva la compatibilità con l'API OpenAI v1;
- distingue errori locali da errori della richiesta;
- espone funzioni piccole che possono essere testate con mock;
- evita stato globale mutabile e cronologia implicita.

## Limiti intenzionali

Questo esempio dimostra soltanto il percorso minimo dal prompt alla risposta.
Non include:

- streaming dei token;
- messaggi `system`, cronologia o conversazioni multi-turn;
- retry, backoff o gestione dei rate limit;
- tool calling;
- retrieval o grounding;
- telemetria applicativa;
- gestione di dati sensibili;
- un runtime applicativo distribuito;
- un agente Microsoft Foundry.

Questi limiti mantengono il campione abbastanza piccolo da poter seguire
l'intero flusso: configurazione, identità, endpoint, richiesta e risposta.
