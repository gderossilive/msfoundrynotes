# Guida a `fine_tune_documents.py` e `prepare_finetuning_data.py`

Questa guida spiega, con un approccio didattico, come funzionano i due script
che portano il benchmark della lane `00a` dal modello di base a un modello
adattato con **supervised fine-tuning** (SFT):

- [`prepare_finetuning_data.py`](prepare_finetuning_data.py) costruisce, in modo
  deterministico, i file di addestramento e di validazione;
- [`fine_tune_documents.py`](fine_tune_documents.py) esegue l'esperimento:
  invia il job, lo monitora, sceglie un checkpoint e lo valuta.

Gli script riusano il codice descritto nella
[guida a `benchmark_documents.py`](benchmark_documents-explained.md) e nella
[guida a `chat_completions.py`](chat_completions-explained.md). Conviene leggerle prima.

Nulla viene eseguito dal provisioning della lane né dai test locali. Ogni fase
è un comando esplicito e può comportare costi.

## Obiettivo dell'esperimento

Il benchmark ha mostrato che `gpt-4.1-mini`, senza regole di instradamento nel
prompt, classifica correttamente tipo e reparto ma sbaglia spesso la priorità.
L'esperimento risponde a una domanda controllata:

> Se mostro al modello esempi etichettati, la sua classificazione sugli stessi
> dieci documenti del benchmark migliora?

Perché il confronto sia onesto, i dieci documenti del benchmark **non entrano
mai** nell'addestramento e non vengono usati per scegliere il checkpoint.

## Flusso generale

```text
business_documents_100.json (sorgente sintetica)
        |
        v
prepare: 78 training / 12 validazione / 10 held-out
        |
        v
submit: carica i file e crea il job SFT (Developer tier)
        |
        v
monitor: attende il job e legge i 3 checkpoint
        |
        v
evaluate-checkpoints: distribuisce e valuta ogni checkpoint sulla validazione
        |
        v
Scelta del migliore e deployment stabile; eliminazione di quelli temporanei
        |
        v
final-test: valutazione unica sui 10 documenti held-out
```

## Parte 1: `prepare_finetuning_data.py`

### Le costanti

```python
SOURCE_PATH = ... / "data" / "business_documents_100.json"
HELDOUT_PATH = ... / "data" / "business_documents_10.json"
DEFAULT_OUTPUT_DIR = ... / "data" / "fine-tuning"
SEED = "foundry-notes-00a-sft-v1"
```

La sorgente è un insieme di cento documenti sintetici; `HELDOUT_PATH` è la
fixture del benchmark. I file generati finiscono in `data/fine-tuning/`, che è
ignorata da Git. `SEED` è una stringa fissa: serve per rendere la suddivisione
riproducibile.

`prepare_finetuning_data.py` importa `FIELDS`, `SYSTEM_PROMPT` e
`ConfigurationError` da `benchmark_documents.py`. Il prompt di addestramento è
quindi **identico** a quello del benchmark, parola per parola.

### Caricare e validare le righe

`load_rows()` applica le stesse regole della fixture del benchmark: array non
vuoto, esattamente le chiavi `document_text`, `document_type`, `department` e
`priority`, valori stringa non vuoti. Qualsiasi violazione è un
`ConfigurationError`.

### La suddivisione deterministica

`split_rows()` rifiuta di procedere se una qualsiasi premessa non è vera:

| Verifica | Perché conta |
|---|---|
| Esattamente 100 righe sorgente e 10 held-out | Il piano dei numeri è fisso |
| I 10 held-out sono le prime 10 righe della sorgente | Il benchmark è davvero un sottoinsieme |
| Nessun testo duplicato nella sorgente | Un duplicato potrebbe finire sia in addestramento sia nel test |
| 15 righe non di test per ciascuna delle sei classi | Il bilanciamento è garantito |

Le 90 righe restanti si raggruppano per tipo di documento. Per ogni gruppo le
righe sono ordinate in base a un hash:

```python
key=lambda row: hashlib.sha256(
    f"{SEED}\0{row['document_text']}".encode("utf-8")
).digest()
```

Le prime due di ogni gruppo diventano **validazione**, le altre
**addestramento**. L'ordine dipende solo dal testo e dal seed, quindi a ogni
esecuzione la suddivisione è la stessa, senza numeri casuali. Il risultato è:

| Insieme | Righe | Uso |
|---|---:|---|
| Addestramento | 78 | Il modello impara da questi esempi |
| Validazione | 12 (2 per classe) | Scegliere il checkpoint migliore |
| Held-out | 10 | Test finale, una sola volta |

Un ultimo controllo verifica che i tre insiemi non abbiano testi in comune. Il
manifest registra seed, conteggi e distribuzioni per classe.

### Il formato dei file JSONL

`to_sft_jsonl()` produce una riga per esempio, con tre messaggi:

```json
{"messages":[
  {"role":"system","content":"<SYSTEM_PROMPT del benchmark>"},
  {"role":"user","content":"<testo del documento>"},
  {"role":"assistant","content":"{\"document_type\":\"...\",\"department\":\"...\",\"priority\":\"...\"}"}
]}
```

Il messaggio `assistant` è la risposta che il modello dovrebbe dare, nello
stesso JSON a tre campi del benchmark.

### Scrittura sicura

I file sono codificati UTF-8 **con BOM** (`utf-8-sig`), come richiesto dal
servizio di fine-tuning. `write_if_consistent()` non sovrascrive un file
esistente con contenuto diverso: serve `--force`. Il manifest aggiunge gli hash
SHA-256 della sorgente e dei due file, per riconoscere se i dati sono cambiati.

```bash
python prepare_finetuning_data.py
python prepare_finetuning_data.py --output-dir <cartella> --force
```

Esce con codice `0` se va a buon fine e `2` per un errore di configurazione.

## Parte 2: `fine_tune_documents.py`

### Le costanti dell'esperimento

```python
BASE_MODEL = "gpt-4.1-mini-2025-04-14"
TRAINING_TYPE = "Developer"
TRAINING_TYPE_WIRE = "developerTier"
FINE_TUNING_API_VERSION = "2025-05-15-preview"
N_EPOCHS = 3
LEARNING_RATE_MULTIPLIER = 0.5
SEED = 41
SUFFIX = "docs-00a-v1"
DEFAULT_DEPLOYMENT_NAME = "gpt-4.1-mini-docs-ft"
```

Tutti gli iperparametri sono dichiarati nel codice, quindi l'esperimento è
ripetibile. Il tier **Developer** non ha un SLA sul tempo di completamento né
garanzie di residenza dei dati. La versione dell'API di fine-tuning è una
*preview* fissata esplicitamente: la sua disponibilità può cambiare
indipendentemente da questo codice.

### Il file di stato

```python
DEFAULT_STATE = ... / "fine-tuning-state.json"
```

Tra un comando e l'altro lo script salva su disco un file di stato: ambiente
`azd`, identificatori dei file caricati, ID del job, checkpoint, valutazioni e
deployment temporanei. Il file è ignorato da Git e va tenuto privato, perché
contiene identificatori di risorse remote. Ogni comando lo carica con
`load_state()` e lo riscrive dopo ogni passo importante con `save_state()`: se
un comando si interrompe, quanto già fatto resta registrato.

### Chiamare l'API di fine-tuning

`fine_tuning_request()` non usa il client OpenAI: invia richieste REST dirette
all'endpoint del **progetto**:

```text
https://<account>.services.ai.azure.com/api/projects/<progetto>/fine_tuning/<percorso>
```

- Ottiene un token Entra ID con `AzureCliCredential` per lo scope
  `https://ai.azure.com/.default`: nessuna chiave API.
- Aggiunge `api-version` e il parametro `fineTuningJob=supervised`, richiesto
  dall'endpoint *preview* per le operazioni sui job.
- Imposta un timeout di 120 secondi.
- Trasforma ogni risposta HTTP 400 o superiore, ogni risposta non JSON e ogni
  JSON non oggetto in un `RuntimeError` con i dettagli.

### Rileggere la validazione come documenti

`load_sft_documents()` legge `validation.jsonl` e la converte in oggetti
`Document`, gli stessi del benchmark. Verifica per ogni riga che ci siano tre
messaggi, che il messaggio di sistema sia **esattamente** `SYSTEM_PROMPT`, che
l'ultimo sia la risposta con i tre campi attesi. Se il prompt del benchmark
cambia senza rigenerare i dati, il controllo segnala la deriva.

Così la validazione dei checkpoint riusa senza modifiche `collect_predictions`
e `run_foundry_evaluation`.

### Comando `prepare`

```bash
python fine_tune_documents.py prepare
```

Esegue solo la preparazione dei dati, in locale e senza chiamare Azure.

### Comando `submit`

```bash
python fine_tune_documents.py submit --environment <ambiente-azd-00a>
```

Il comando esegue, in ordine:

1. **Rifiuta di ripartire** se lo stato contiene già un job: un secondo invio
   creerebbe un secondo addestramento a pagamento. Per un nuovo esperimento si
   usa un nuovo file di stato.
2. Ricrea i dati con `prepare()`.
3. Legge l'ambiente `00a` e crea un client OpenAI sull'endpoint
   `https://<account>.openai.azure.com/openai/v1/`, con lo scope dei servizi
   cognitivi (`COGNITIVE_SERVICES_SCOPE`).
4. Carica i due file con `purpose="fine-tune"`, **a meno che** lo stato contenga
   già i loro ID: in tal caso li riusa.
5. **Salva lo stato prima di creare il job**: gli ID dei file non vanno persi
   se la richiesta successiva fallisce.
6. Crea il job `supervised` con modello di base, file, seed, suffisso,
   iperparametri e `trainingType` `developerTier`.
7. Registra `job_id` e stato nel file.

Una richiesta remota può riuscire prima che la risposta o lo stato locale
vengano salvati. In caso di errore o timeout, **un ID del job mancante in locale
non prova che nessun job sia stato creato**: va verificato nel progetto Foundry
prima di riprovare.

### Comando `monitor`

```bash
python fine_tune_documents.py monitor [--poll-seconds 60] [--timeout-seconds 21600]
```

Interroga il job ogni 60 secondi, per al massimo sei ore, aggiornando lo stato.
Quando il job termina:

- se non è `succeeded`, il comando fallisce riportando lo stato e l'errore;
- altrimenti legge i checkpoint e controlla che siano **esattamente tre**, uno
  per epoca (`N_EPOCHS`);
- salva modello addestrato, file dei risultati e checkpoint ordinati per
  `step_number`.

### Comando `evaluate-checkpoints`

```bash
python fine_tune_documents.py evaluate-checkpoints \
  --deployment-name gpt-4.1-mini-docs-ft \
  --sku-name GlobalStandard \
  --capacity 10
```

Per ciascun checkpoint:

1. Ricava l'ID del modello con `checkpoint_model_id()` (chiavi
   `fine_tuned_model_checkpoint` oppure `fine_tuned_model`).
2. Lo **distribuisce** con un deployment temporaneo, chiamando Azure CLI
   (`az cognitiveservices account deployment create`, versione modello `1`). Il
   nome è `docs-ft-<ultimi 6 caratteri del job>-cp<n>`. È registrato nello stato
   subito dopo la creazione e **prima** dell'attesa, così può essere ripulito in
   caso di errore.
3. Attende che il deployment risponda (`wait_for_deployment`): fino a dieci
   tentativi a distanza di trenta secondi, con una richiesta di classificazione
   su un solo documento. Solo errori di rete o API causano un nuovo tentativo.
4. Lo valuta sui 12 documenti di validazione (`evaluate_model`), cioè le stesse
   richieste del benchmark e gli stessi grader Foundry.
5. Salva la valutazione nello stato.

Il comando è **riprendibile**: i checkpoint già valutati sono saltati e un
deployment temporaneo già registrato non viene ricreato.

### Come si sceglie il checkpoint

```python
def validation_rank(evaluation):
    return (
        accuracy["all_fields"],
        accuracy["priority"],
        coverage,
        -valid_loss,
    )
```

La classifica è una tupla, quindi i criteri si applicano in ordine:

1. accuratezza su **tutti e tre i campi**;
2. a parità, accuratezza sulla **priorità**;
3. poi la copertura;
4. infine la **perdita di validazione più bassa** (negata, perché `max` cerca il
   valore più grande). Se la perdita manca, il checkpoint è ultimo in questo
   criterio.

`checkpoint_valid_loss()` legge `full_valid_loss` oppure `valid_loss` dalle
metriche del checkpoint.

Il vincitore viene distribuito con il nome stabile scelto dall'utente
(`gpt-4.1-mini-docs-ft` per default), poi **solo** i deployment temporanei
registrati nello stato vengono eliminati. Il deployment del modello di base e
quelli estranei all'esperimento non vengono toccati. Usa un nome riservato a
questo esperimento: non riusare un deployment esistente.

> **Perché tre checkpoint?** Un modello addestrato più a lungo non è sempre
> migliore su dati nuovi. Valutare ogni epoca su un insieme separato permette di
> scegliere con dati che il modello non ha visto, senza toccare il test finale.

### Comando `final-test`

```bash
python fine_tune_documents.py final-test [--output <file>]
```

Carica i dieci documenti del benchmark, attende che il deployment scelto sia
pronto e lo valuta con la stessa procedura. Scrive il report JSON (per default
`fine-tuning-final-results.json`) e registra un riepilogo nello stato. Stampa
l'accuratezza per campo.

> **Eseguilo una volta sola.** Scegliere ripetutamente un checkpoint guardando il
> test held-out lo trasformerebbe in un insieme di validazione, e il confronto
> con la baseline perderebbe significato.

## Argomenti e codici di uscita

| Comando | Argomenti specifici |
|---|---|
| `prepare` | `--force` |
| `submit` | `--environment` (obbligatorio) |
| `monitor` | `--poll-seconds`, `--timeout-seconds` |
| `evaluate-checkpoints` | `--deployment-name`, `--sku-name`, `--capacity` |
| `final-test` | `--output` |

`--state` è un argomento globale e va indicato **prima** del comando. Per
esempio: `python fine_tune_documents.py --state altro.json monitor`.

| Codice | Situazione |
|---|---|
| `0` | Comando completato |
| `1` | Errore di rete o API, errore di Azure CLI, job fallito o scaduto |
| `2` | Errore di configurazione (stato mancante, dati non validi, contesto assente) |

## La sequenza completa

Dalla directory `scenarios/00-foundry-core/app`, con la lane `00a` distribuita e
l'Azure CLI collegata come utente autorizzato:

```bash
python fine_tune_documents.py prepare

python benchmark_documents.py \
  --environment <ambiente-azd-00a> \
  --output fine-tuning-baseline-results.json

python fine_tune_documents.py submit --environment <ambiente-azd-00a>
python fine_tune_documents.py monitor
python fine_tune_documents.py evaluate-checkpoints \
  --deployment-name gpt-4.1-mini-docs-ft --sku-name GlobalStandard --capacity 10
python fine_tune_documents.py final-test
```

La baseline va registrata subito prima dell'addestramento, perché le risposte
del modello possono variare tra esecuzioni. Prerequisiti, ruoli e risultati
registrati sono nel
[README dell'applicazione](README.md#document-classification-fine-tuning-00a).

## Permessi

L'utente che esegue gli script riceve dalla lane `00a` il ruolo **Foundry
Owner** sul progetto e **Cognitive Services OpenAI User** sull'account.
`Foundry User` basterebbe per addestrare, ma non per distribuire il modello
risultante. Prima di riprovare su una distribuzione esistente, verifica quale
ruolo possiede il chiamante.

## Cosa verificano i test

I test in [`test_prepare_finetuning_data.py`](test_prepare_finetuning_data.py) e
[`test_fine_tune_documents.py`](test_fine_tune_documents.py) usano mock e non
chiamano Azure. Controllano l'allineamento tra sorgente e held-out, il formato
BOM-JSONL, il rifiuto di sovrascritture senza `--force`, la rilettura della
validazione, il rifiuto di una deriva del prompt, i criteri di spareggio, l'attesa
del deployment, la configurazione Developer a tre epoche, il blocco
dell'invio duplicato e gli errori espliciti di Azure CLI.

Non dimostrano: la disponibilità attuale del modello, la compatibilità dell'API
*preview*, il successo dell'addestramento, il deployment o l'accuratezza in
produzione.

## Costi, stato e pulizia

- Addestramento, deployment dei checkpoint, chiamate al modello e valutazioni
  possono comportare costi. Il deployment ottimizzato consuma quota finché non
  viene rimosso.
- Job, file caricati, modello personalizzato e deployment scelto restano in
  Foundry per esperimenti successivi.
- Dopo un errore durante la valutazione dei checkpoint, controlla
  `temporary_deployments` nel file di stato: potrebbe restare qualche
  deployment temporaneo da eliminare.
- Elimina solo job, modelli, file e deployment dell'esperimento, dopo aver
  confermato account e identificatori. Annulla un eventuale addestramento
  attivo prima di scartare lo stato.

## Limiti intenzionali

Questo è un esperimento controllato su dati sintetici, non una procedura di
produzione. Non include:

- un test indipendente ampio: dieci documenti, un solo `Critical`;
- ripetizioni per stimare la variabilità dell'addestramento;
- dati reali, multilingua o ambigui;
- misure di latenza o di costo per richiesta;
- retry per le richieste REST di fine-tuning;
- un agente, strumenti, retrieval o memoria.

I risultati registrati nel README dell'applicazione sono storici: il checkpoint
scelto ha classificato correttamente tutti i campi sui dieci documenti held-out,
ma questo non rende il flusso pronto per la produzione.
