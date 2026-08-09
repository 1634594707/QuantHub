# OKX Runner small-capital review package

Status: **not approved**. Prepared: 2026-08-03. This document prepares a future review; it does
not authorize Demo or live trading.

## Preconditions

External OKX Demo normal and fault drills must pass with immutable evidence, at least one OKX
factor must pass the complete preregistered research and simulation gate, open reconciliation
differences must be zero, backups must be verified, and a reviewer independent of implementation
must sign the decision record. API credentials must have trade-only permission and no withdrawal
permission.

## Maximum pilot risk budget

- scheduled, attended windows only; no unattended or overnight pilot;
- isolated sub-account and at most 10,000 USDT or 5% of approved capital, whichever is lower;
- leverage at most 1x, per-symbol exposure at most 1% of approved capital and total exposure at
  most 5%; the imported strategy package may impose stricter limits and always wins;
- stop on 0.5% daily loss, 2% peak-to-trough drawdown, any unknown order, unresolved
  reconciliation difference, credential anomaly or stale market data;
- start in `cancel_only` after a fault and return to normal only after external-state query,
  reconciliation and a recorded operator decision.

## Staffing and evidence

Name a primary operator, backup operator and independent safety reviewer before scheduling a
window. Both operators must be able to revoke the key, halt the account, cancel open orders and
restore the database. Preserve strategy-package hash, image digest, config fingerprint, account
snapshot, every order event, fill, fee, balance/position reconciliation, incident timeline and
review signatures.

## Decision record

Decision: **deferred**. Reason: no external OKX Demo drill and no passing target-market factor.
Live mode remains disabled; setting `QH_RUNNER_LIVE_APPROVED=1` before independent approval is a
policy violation.
