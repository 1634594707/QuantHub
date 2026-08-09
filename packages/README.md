# QuantHub Core packages

The packages in this directory are the only stable shared surface for the split products.
They follow semantic versioning and expose public names from each package's `__init__.py`.

| Package | Actual consumers | Stable responsibility |
| --- | --- | --- |
| `market_data` | Stock, Factor Lab, Runner | instrument identity, candles, market time |
| `financial_data` | Stock, Factor Lab | statement fields and normalization |
| `research_protocol` | Stock, Factor Lab, Runner | evidence, snapshots and immutable run references |
| `strategy_package` | Factor Lab, Runner | signed strategy release packages |
| `model_client` | Stock, Factor Lab | provider-neutral model calls and redaction |
| `data_quality` | Stock, Factor Lab, Runner | missing, stale, conflict and time-order gates |
| `product_auth` | Stock, Factor Lab, Runner | product-local bearer authentication |

Compatibility policy:

- Patch versions may fix implementation defects without changing serialized fields.
- Minor versions may add optional fields and public helpers.
- Major versions may remove or reinterpret fields and require a compatibility test update.
- Product orchestration, factor lifecycle state and order state machines are prohibited here.

Minimal examples are executable in `tests/split/test_core_contracts.py`.
