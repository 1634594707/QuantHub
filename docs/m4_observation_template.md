# M4-08 连续 7 天观察 — 证据模板

> 目标：对 OKX 交易验证闭环（M4-04 私有 WebSocket / M4-05 四类定时对账 / M4-06 错误脱敏 / M4-07 故障演练）进行连续 7 个自然日的运行观察，确认稳定性与可恢复性。
>
> **状态说明（诚实标注）：** 本模板与 `tools/observe_daily.py` 已就绪，但「连续 7 天」观察**尚未完成**——它需要每日自动运行 7 天并由人工/CI 持续采集，不能由一次性脚本伪造。下方第 2 节为自动采集结果，第 3 节为人工填写栏。

## 1. 如何运行

```bash
# 每日一次（建议放入 cron / Windows 任务计划程序）
.venv/Scripts/python.exe tools/observe_daily.py --account-id demo

# 强制当天重采
.venv/Scripts/python.exe tools/observe_daily.py --account-id demo --force
```

- 证据目录：`data/observation/YYYY-MM-DD.json`（每日一个文件）
- 私有 WS 证据：`data/observation/ws_evidence/obs-YYYYMMDD.json`
- 四类对账证据：通过 `apps/okx_runner` 的 `/api/reconciliation/runs` 或 `data/reconcile_runs/*.json` 查询

## 2. 自动采集结果（脚本生成，勿手改）

| 日期 | REST | 公开 WS | 私有 WS 登录 | 一次对账(passed/diffs) | 备注 |
| --- | --- | --- | --- | --- | --- |
| 2026-08-10 | ✅ | ✅ (BTC-USDT 65017.6) | ⚠️ 60012 未授权(见限制) | ❌ / 3 diffs | 首日基线 |

> 首日已采；其余 6 天待补齐。

## 3. 人工/CI 观察栏（每日填写）

| 天数 | 日期 | 私有 WS 是否持续推送 | 断线重连次数 | 对账是否全部 passed | 发现 diff 数 | 处理结论 | 观察人 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| D1 | 2026-08-10 | 否(登录未授权) | 0 | 否 | 3 | 见已知限制 L1 | — |
| D2 | | | | | | | |
| D3 | | | | | | | |
| D4 | | | | | | | |
| D5 | | | | | | | |
| D6 | | | | | | | |
| D7 | | | | | | | |

## 4. 已知限制（L）

- **L1（关键，已验证）：** 当前本地保险库中的 OKX demo 凭据**未开通私有 WebSocket 登录权限**。实测：公开频道可正常连接并接收行情（BTC-USDT tickers 已验证）；私有频道登录被 OKX 返回 `60012 Illegal request / 60011 Please log in`。这是 OKX demo 凭据的常见限制，并非代码缺陷。`apps/okx_runner/private_ws.py` 的登录/签名逻辑严格按 OKX 官方规范实现，并已通过 `tests/test_private_ws_mock.py`（协议仿真服务端校验 HMAC）端到端验证。
- **L2：** `observe_daily.py` 的私有 WS 段每次都会如实记录登录失败（login_response=null），不会伪造成功。
- **L3：** 对账出现的 diff 需在 `data/reconcile_runs/` 中按 `difference_ids` 复核，并通过 `/api/reconciliation/diffs/{id}/resolve` 关闭。

## 5. 验收口径

- ✅ 脚本可每日无人工干预运行一次并落盘证据。
- ⬜ 连续 7 天证据齐全且 diff 均已复核关闭（待人工/CI 持续 7 天）。
- ⬜ 若后续获得具备私有 WS 权限的凭据，需补一轮私有 WS 持续推送 ≥ 24h 的观察。
