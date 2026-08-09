# OKX Runner Demo safety evidence

The deterministic Demo adapter in `tests/split/test_okx_runner_product.py` exercises the same
adapter contract and persisted order state machine used by deployment adapters. Evidence covers:

- normal submit, stable client-order id and duplicate request;
- timeout where the exchange accepted the order and timeout with unknown external state;
- query-before-retry, process restart and unknown-order recovery;
- partial fill, cancel and rejection;
- minimum quantity, quantity/price precision, leverage and package exposure limits;
- global/account halt and cancel-only controls;
- order, balance and position reconciliation with owned/resolved differences;
- deterministic replay and immutable runtime-result return records;
- credential redaction in raw request, response, event and error payloads.

This is local Demo contract evidence. A deployment must inject an OKX Demo adapter and secret
manager, then rerun the same drill against the external Demo endpoint before any live review.
Live mode remains gated by `QH_RUNNER_LIVE_APPROVED=1` and is not enabled by this roadmap.

## Real-time shadow evidence

`tools/run_runner_shadow_acceptance.py` consumes five actual local OKX bars through a timed
iterator. Runner processes each arrival in the shadow environment and persists signals, bounded
target positions, cost-adjusted theoretical fills, arrival latency and a canonical result hash.
The 2026-08-03 run took 1.25 seconds, produced three observations and created zero external
orders. Evidence is `docs/okx_runner/evidence/shadow_session.json`.

This closes the local real-time shadow contract only. `external_market_realtime=false` remains in
the evidence because the acceptance network reset OKX public API connections. It does not replace
the credentialed external Demo lifecycle or fault drill.
