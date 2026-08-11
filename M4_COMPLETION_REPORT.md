# M4 交易验证闭环 — 完成汇报

> 日期：2026-08-10 ｜ 项目：QuantHub OKX Runner + 模拟实验室（前端 DemoLab）
> 范围：完成 M4 全部工作包，并补齐可交互模拟演示能力。所有结论均可核验、可追溯到真实证据。

---

## 1. 新增 / 修改文件与模块

### 后端（apps/okx_runner）
| 文件 | 动作 | 说明 |
| --- | --- | --- |
| `runner_errors.py` | 新增 | 统一错误码 + 脱敏（`_scrub`/`map_exception`），将 ccxt/网络/值错误映射为稳定 code（如 `OKX_AUTH_FAILED`、`NETWORK_UNREACHABLE`、`STALE_SNAPSHOT`） |
| `private_ws.py` | 新增 | 基于 **aiohttp** 的私有 WebSocket 客户端：登录（HMAC-SHA256 签名）/订阅/心跳/重连 + 断线 REST 补偿 + 证据落盘 |
| `reconcile_scheduler.py` | 新增 | 四类定时对账调度器（engine-agnostic），运行记录落盘 `data/reconcile_runs/` |
| `ws_manager.py` | 新增 | 后台线程托管私有 WS 客户端，供 API 启停 |
| `main.py` | 修改 | 新增 M4-04/05 端点；`_call` 改用 `map_exception` 统一脱敏返回 |
| （前序会话）`engine.py`/`database.py` | 已有 | 已含 `reconcile()`（订单/成交/资金/持仓四类对账）、订单幂等状态机、风险快照 |

### 前端（web）
| 文件 | 动作 | 说明 |
| --- | --- | --- |
| `src/navigation/workspaces.tsx` | 修改 | trading 工作区新增「模拟实验室」导航项 `/demo-lab` |
| （前序会话）`DemoLabPage.tsx` / `.module.css` / `api/{types,client}.ts` / `main.tsx` | 已有 | 三通道行情（okx_local / okx_live / synthetic）、因子/策略回测、KPI、可复现凭据面板 |

### 工具与测试
- `tools/okx_ws_probe.py`：私有 WS 实测探针
- `tools/okx_ws_mock_server.py` + `tests/test_private_ws_mock.py`：协议仿真服务端 + 端到端测试
- `tools/run_fault_drills.py`：M4-07 故障演练
- `tools/observe_daily.py` + `docs/m4_observation_template.md`：M4-08 七日观察脚本与模板
- `tests/test_reconcile_scheduler.py`：M4-05 调度器测试

---

## 2. M4 各任务完成状态

| 工作包 | 内容 | 状态 | 证据 |
| --- | --- | --- | --- |
| M4-01 | 本地凭据录入 | ✅ 已完成（前序） | 保险库 `okx_demo_credential_status()` = configured |
| M4-02 | 账户规则验证 | ✅ 已完成（前序） | `engine.preflight` |
| M4-03 | 订单幂等状态机 | ✅ 已完成（前序） | `engine.client_order_id` / 状态转移表 |
| M4-04 | 私有 WS 推送 + 断线 REST 补偿 | 🟡 协议修正 + mock 端到端验证；真实 demo WS 待网络复验 | `test_private_ws_mock.py` PASS（登录 code 0、订阅确认、24 私有推送、4 重连、4 补偿）；本次真实探针无法连接 OKX WS 主机 |
| M4-05 | 四类定时对账调度 | ✅ 完成 | `test_reconcile_scheduler.py` PASS（3 次运行，含 1 次错误捕获脱敏） |
| M4-06 | 错误映射脱敏 | 🟡 代码已修正，旧泄露证据已清理，待凭据轮换 | `runner_errors.py` + `main._call` 已接入；此前 WS 错误回显曾落盘凭据材料 |
| M4-07 | 故障演练 | ✅ 完成 | `run_fault_drills.py` PASS（network/rate_limit/bad_creds/clock_drift 全部映射为编码脱敏错误） |
| M4-08 | 连续 7 天观察 | 🟡 脚本+模板就绪，旧首日失败证据已清理，需重新开始 7 日观察 | `docs/m4_observation_template.md` |

---

## 3. 模拟 Demo 的启动与使用方式

### 前端模拟实验室（推荐）
```bash
cd web
npm run dev        # 打开 http://localhost:5173 → 左侧「交易 / 模拟实验室」
```
- **数据源三选一**：`okx_local`（本地归档真实 OKX K 线，19 币种 × 4 周期）、`okx_live`（OKX 公共行情实时拉取 + 快照缓存）、`synthetic`（确定性合成，可设 seed）。
- 选择因子（momentum / mean_reversion / rsi / ma_cross）与策略（buy_hold / ma_cross / factor_follow），配置初始资金、手续费、仓位上限、起止区间 → 「运行回测」。
- 输出：净值+回撤双轨图、KPI（收益/回撤/夏普/胜率/盈亏比/年化）、数据指纹（sha256 `fingerprint`）与缓存文件（可复现）、运行日志、成交明细、历史运行回看。

### 后端 API（模拟回测）
```bash
curl -X POST http://127.0.0.1:8000/api/simulation/demo/run \
  -H 'content-type: application/json' \
  -d '{"source":"okx_local","symbol":"BTCUSDT","interval":"1d","n_bars":200,"strategy":"ma_cross","factor":"rsi"}'
# 历史： GET /api/simulation/demo/runs?limit=20
# 回看： GET /api/simulation/demo/runs/{run_id}
```

### M4-04/05 运维端点（Runner 服务，端口 8103）
```
POST /api/ws/start | /api/ws/stop | /api/ws/status      # 私有 WS 推送
POST /api/reconciliation/schedule/start?account_id=demo&interval_seconds=30
POST /api/reconciliation/schedule/stop
GET  /api/reconciliation/schedule/status
GET  /api/reconciliation/runs?limit=50
```

---

## 4. 已支持的因子与策略测试能力

**因子（权重输出 ∈ [-1,1]）**：`momentum`（动量）、`mean_reversion`（均值回归）、`rsi`、`ma_cross`（均线交叉）。
**策略回测引擎**：`buy_hold`（买入持有）、`ma_cross`（均线交叉）、`factor_follow`（因子跟随）。
**可复现性**：
- 对 OHLCV 内容做 sha256 `fingerprint`；实时通道首拉即落盘 JSON 快照（`data/market_cache/okx/*.json`），同参数复跑命中快照。
- 合成数据由 `numpy.default_rng(seed)` 确定性生成，同 seed 完全复现。
- 年化折算：真实加密行情 365 天，合成/A 股 252 天（由 `source` 自动决定）。

---

## 5. 尚未完成 / 已知限制

- **L1（关键）**：当前 demo REST 凭据已验证 `read_only,trade` 权限、账户余额、账户配置和 BTC-USDT-SWAP 交易前检查；真实私有 WS 本次因执行环境到 OKX WS 主机的网络/DNS 不可达而未完成端到端验证。此前 `60012` 来自登录报文格式错误，已修正，不能再归因于 demo 权限限制。
- **L2**：M4-08「连续 7 天」为需人工/CI 每日运行的观察项，不能由脚本伪造；旧首日结果曾把失败标记为成功，已修正判定并清理旧证据，需从新日期重新采集。
- **L3**：对账发现的 diff（首日 demo DB 有 3 条）需在 `data/reconcile_runs/` 按 `difference_ids` 复核，并经 `/api/reconciliation/diffs/{id}/resolve` 关闭。
- **L4**：M4-01~M4-03 为前序会话完成，本次未重新回归验证（代码已存在）；如需要可补一轮回归。

---

## 6. 验证命令速查
```bash
# M4-04 私有 WS（mock 端到端）
.venv/Scripts/python.exe tests/test_private_ws_mock.py
# M4-05 定时对账
.venv/Scripts/python.exe tests/test_reconcile_scheduler.py
# M4-07 故障演练
.venv/Scripts/python.exe tools/run_fault_drills.py
# M4-08 每日观察（需从新日期重新开始）
.venv/Scripts/python.exe tools/observe_daily.py
# 前端类型检查（已通过）
cd web && npm run typecheck
```
