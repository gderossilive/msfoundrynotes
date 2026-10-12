# Guida a `chat_completions.py`

Questa guida spiega, con un approccio didattico, com'è composto e come funziona
[`chat_completions.py`](chat_completions.py).

Lo script è un'applicazione da riga di comando molto piccola: legge la
configurazione di uno scenario Microsoft Foundry già distribuito, autentica
l'utente con Azure CLI, invia un singolo prompt al modello e stampa la prima
risposta testuale ricevuta.

Non crea risorse Azure e non distribuisce un'applicazione. Inoltre, non è un
agente: non usa strumenti, memoria, retrieval o un ciclo autonomo.

## Obiettivo dello script

Lo stesso client supporta due scenari:

| Scenario | Topologia | Destinazioni disponibili |
|---|---|---|
| `00a` | Foundry con endpoint pubblico | `direct` |
| `00c` | Foundry isolato in una VNet e API Management | `direct`, `gateway` |

Nello scenario `00a`, la richiesta raggiunge direttamente l'endpoint pubblico
di Foundry. Nello scenario `00c`, una chiamata `direct` eseguita da una macchina
esterna deve normalmente fallire perché l'accesso pubblico è disabilitato; la
destinazione `gateway` passa invece attraverso Azure API Management.

## Flusso generale

L'esecuzione segue questi passaggi:

```text
Argomenti della CLI
        |
        v
Lettura dell'ambiente azd
        |
        v
Validazione della configurazione
        |
        v
Scelta dell'endpoint direct/gateway
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

Lo script usa esclusivamente moduli della libreria standard nella fase iniziale:

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

### Scope dei token

```python
TOKEN_SCOPE = "https://ai.azure.com/.default"
COGNITIVE_SERVICES_SCOPE = "https://cognitiveservices.azure.com/.default"
```

`TOKEN_SCOPE` è lo scope predefinito usato per ottenere il token Microsoft
Entra ID con cui viene chiamato Foundry. `COGNITIVE_SERVICES_SCOPE` è disponibile
per gli altri flussi condivisi dall'applicazione, per esempio quelli che
richiedono lo scope dei servizi cognitivi.

### Directory degli scenari

```python
LANE_DIRECTORIES = {
    "00a": ... / "00a-foundry-core-public",
    "00c": ... / "00c-foundry-core-byo-vnet",
}
```

Ogni ambiente `azd` appartiene alla directory dello scenario che lo ha creato.
Per questo lo script non cerca l'ambiente in una posizione generica: usa
esplicitamente la directory associata a `00a` o `00c`.

### Espressioni regolari

Tre pattern controllano che i valori recuperati da `azd` abbiano una forma
attesa:

- `ACCOUNT_PATTERN` valida il nome dell'account Foundry;
- `MODEL_PATTERN` valida il nome del deployment e del progetto;
- `GATEWAY_ENDPOINT_PATTERN` accetta solo un endpoint HTTPS di API Management
  che termina con `/openai/v1/`.

Questi controlli intercettano configurazioni mancanti o malformate prima di
effettuare una chiamata di rete.

## 2. `ConfigurationError`

```python
class ConfigurationError(RuntimeError):
    pass
```

Questa eccezione distingue gli errori di configurazione dagli errori restituiti
dalle API. Alcuni esempi sono:

- scenario non supportato;
- ambiente `azd` inesistente o associato alla lane sbagliata;
- account o deployment mancanti;
- endpoint del gateway non valido;
- prompt vuoto.

In `main()` questi errori producono un messaggio chiaro su `stderr` e il codice
di uscita `2`.

## 3. Il modello dati `Deployment`

`Deployment` raccoglie la configurazione necessaria per una chiamata:

```python
@dataclass(frozen=True)
class Deployment:
    lane_id: str
    account_name: str
    model_deployment_name: str
    gateway_endpoint: str | None = None
    project_name: str | None = None
    resource_group: str | None = None
    subscription_id: str | None = None
```

L'opzione `frozen=True` rende l'istanza immutabile dopo la creazione. In questo
modo la configurazione validata non può essere modificata accidentalmente
durante l'esecuzione.

### Proprietà degli endpoint

`direct_base_url` costruisce l'endpoint OpenAI v1 diretto:

```text
https://<account>.services.ai.azure.com/openai/v1/
```

`fine_tuning_base_url` costruisce invece l'endpoint usato dai flussi di
fine-tuning:

```text
https://<account>.openai.azure.com/openai/v1/
```

`project_base_url` costruisce l'endpoint OpenAI v1 del progetto `00a`. Se la
lane o il nome del progetto non sono corretti, solleva `ConfigurationError`
invece di produrre un URL non valido.

### Scelta della destinazione

Il metodo `base_url(target)` applica le regole di routing:

- `direct` restituisce sempre l'endpoint Foundry diretto;
- `gateway` è accettato solo per `00c` e solo se l'endpoint APIM è configurato;
- ogni combinazione non supportata genera un errore.

Di conseguenza, per esempio, non è possibile chiedere per errore a `00a` di
usare un gateway che quello scenario non possiede.

## 4. Caricamento della configurazione

La funzione `load_deployment(environment_name, lane_id)` è la parte più estesa
dello script. Il suo compito è trasformare un ambiente `azd` in un oggetto
`Deployment` affidabile.

### Esecuzione di `azd`

La funzione esegue:

```text
azd env get-values --environment <nome> --output json
```

Il comando viene avviato dalla directory della lane selezionata. Lo script
cattura sia `stdout` sia `stderr` e controlla esplicitamente il codice di
uscita.

Se `azd` non è installato, oppure il comando fallisce, viene sollevato un
`ConfigurationError` che conserva il dettaglio diagnostico disponibile.

### Decodifica e verifica

L'output deve essere un oggetto JSON. Successivamente la funzione verifica che:

1. `FOUNDRY_SCENARIO_LANE_ID` corrisponda alla lane richiesta;
2. `AZURE_AI_ACCOUNT_NAME` sia presente e valido;
3. `AZURE_AI_MODEL_DEPLOYMENT_NAME` sia presente e valido;
4. l'eventuale `AZURE_AI_PROJECT_NAME` sia valido;
5. `00a` esponga resource group e subscription ID;
6. `00c` esponga un endpoint API Management valido;
7. `00a` non esponga per errore un endpoint API Management.

Solo dopo tutti i controlli viene creato e restituito `Deployment`.

Questa separazione è importante: il resto del programma lavora con dati già
validati e non deve ripetere gli stessi controlli.

## 5. Autenticazione e client OpenAI

`create_openai_client(base_url, token_scope)` crea il client che invierà la
richiesta:

```python
token_provider = get_bearer_token_provider(
    AzureCliCredential(),
    token_scope,
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

Un prompt vuoto viene rifiutato. Quindi viene inviata questa richiesta logica:

```python
client.chat.completions.create(
    model=deployment.model_deployment_name,
    messages=[
        {
            "role": "user",
            "content": normalized_prompt,
        }
    ],
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

`parse_args()` definisce l'interfaccia della CLI:

| Argomento | Obbligatorio | Valore predefinito | Significato |
|---|---:|---|---|
| `--environment` | sì | - | Nome dell'ambiente `azd` già provisionato |
| `--scenario` | no | `00a` | Lane proprietaria dell'ambiente |
| `--target` | no | `direct` | Endpoint `direct` oppure `gateway` |
| `prompt` | sì | - | Testo da inviare al modello |

Le `choices` di `argparse` impediscono di inserire scenari o destinazioni non
riconosciuti.

## 8. Orchestrazione in `main()`

`main()` collega tutte le parti:

```text
parse_args()
    -> load_deployment()
    -> deployment.base_url()
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

## Esempi di esecuzione

### Scenario pubblico `00a`

```bash
python chat_completions.py \
  --environment <ambiente-00a> \
  "Spiega Microsoft Foundry in una frase."
```

Poiché `00a` e `direct` sono i valori predefiniti, non è necessario indicarli.

### Chiamata diretta allo scenario privato `00c`

```bash
python chat_completions.py \
  --environment <ambiente-00c> \
  --scenario 00c \
  "Rispondi esattamente: Hello from Foundry."
```

Da una macchina esterna alla VNet questa chiamata deve normalmente fallire:
serve a verificare che l'accesso pubblico a Foundry sia realmente bloccato.

### Scenario `00c` tramite API Management

```bash
python chat_completions.py \
  --environment <ambiente-00c> \
  --scenario 00c \
  --target gateway \
  "Rispondi esattamente: Hello from Foundry."
```

In questo caso il client presenta il token dell'utente ad API Management. La
policy del gateway valida il chiamante e inoltra la richiesta a Foundry usando
l'identità gestita del gateway.

## Come interpretare gli errori

| Sintomo | Possibile causa |
|---|---|
| `Azure Developer CLI ... was not found` | `azd` non è installato o non è nel `PATH` |
| Ambiente non leggibile | Nome errato o ambiente creato in un'altra lane |
| Errore di binding della lane | `--scenario` non corrisponde all'ambiente |
| `Configuration error` sull'endpoint APIM | `00c` non è configurato completamente |
| `401` | Identità assente, token non valido o ruolo mancante |
| `403` su `00a` | L'utente Azure CLI non è autorizzato sul modello |
| `403` diretto su `00c` | Comportamento atteso se l'accesso pubblico è disabilitato |
| `403` dal gateway | Utente non incluso nell'allowlist APIM |
| Nessuna choice o testo vuoto | Il servizio non ha restituito una risposta utilizzabile |

## Perché questa struttura è utile

Anche se lo script è breve, applica alcune buone pratiche:

- separa parsing, configurazione, autenticazione e chiamata al modello;
- valida i dati prima di costruire endpoint o inviare richieste;
- rende esplicita la lane per evitare di usare l'ambiente sbagliato;
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
