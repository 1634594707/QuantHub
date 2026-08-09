# QuantHub OKX Runner operations

Start shadow mode with `uv run uvicorn apps.okx_runner.main:app --host 127.0.0.1 --port 8103`.
Use `QH_RUNNER_` and `configs/okx-runner.env.example`; shadow, Demo and live use different
database paths, logs and secret scopes. Credentials come only from deployment secret storage.
Never place them in env files, databases, packages, requests or logs.

Operators can access account connection state, deployments, orders/fills, positions/risk,
reconciliation and stop controls. They cannot edit formulas or published parameters. On startup,
query every unfinished client order before allowing new work, then reconcile orders, fills,
balances and positions. During uncertainty select cancel-only or halted mode; never resubmit an
unknown order.

Back up and verify the Runner database before upgrade. Restore only while all writers are stopped,
then run open-order recovery and full reconciliation before normal mode. Keep financial/audit
records for seven years by policy; backup pruning must match the deployment retention schedule.
Demo fault evidence is in `docs/okx_runner/DEMO_SAFETY_EVIDENCE.md`. Live mode additionally
requires an independent safety approval and `QH_RUNNER_LIVE_APPROVED=1`; this repository does not
enable live trading.
