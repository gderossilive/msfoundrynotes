# Level 00, lane 00a tests

Esegue i controlli comuni di struttura, Bicep, contratto `azd` e i test unitari
del client Python Chat Completions:

```bash
./test/test-scenario.sh
```

Dopo un deployment azd, usa `--live` con l'ambiente corretto:

```bash
TEST_AZD_ENV=dev ./test/test-scenario.sh --live
```
