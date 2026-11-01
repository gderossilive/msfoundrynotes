# Level 00, lane 00a tests

From this lane directory, the static suite runs the common structure, Bicep and
`azd` contract checks, then the four Python unit-test modules for the Chat
Completions client, the benchmark, and the fine-tuning preparation and job
contracts. Azure access is mocked. It also checks that the template assigns
**Foundry Owner** on the project and no longer assigns **Foundry User**.

```bash
./test/test-scenario.sh
```

After an `azd` deployment, use `--live` with the correct environment:

```bash
TEST_AZD_ENV=dev ./test/test-scenario.sh --live
```

Live checks inspect the deployed resources and do not send an inference request.
See the [testing guide](../../../../docs/testing.md) for manual inference.
