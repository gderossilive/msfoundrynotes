# Level 00, lane 00a tests

Run the shared structure, Bicep and `azd` contract checks from the lane directory:

```bash
./test/test-scenario.sh
```

After provisioning, use `--live` with the exact deployed environment:

```bash
TEST_AZD_ENV=dev ./test/test-scenario.sh --live
```

Core does not require a scenario-local blog and does not implement automated
`--e2e` tests. Follow the [testing guide](../../../../docs/testing.md) for caller
permissions and manual keyless inference. Live resource checks alone do not
prove inference.
