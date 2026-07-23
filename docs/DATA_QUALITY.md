# 数据质量核查与修复方案（P-C）

> 状态：只读调研完成（2026-07-15）。**本报告不修改任何数据**；修复脚本 `tools/repair_indices_parquet.py` 默认 dry-run，需显式 `--apply` 才落盘，且先备份。
> 结论先行：**股票（stocks）数据干净；指数（indices）大面积损坏；ordinal 时间为设计取舍；`A股数据.zip` 留作源存档。**

---

## 1. 核查方法（只读）

脚本 `C:/Users/Administrator/AppData/Local/Temp/scan_parquet.py` 仅 `pd.read_parquet` + 统计，**未写入任何文件**。指标：
- `OHLC异常行`：`open/high/low/close` 任一 `<= 0`
- `volume哨兵`：`tick_volume == -9223372036854775808`（即 `int64.min`，缺失值哨兵）

---

## 2. 核查结果

| 数据集 | 文件数 | OHLC 异常行 | volume 哨兵 | 结论 |
|---|---|---|---|---|
| `data/parquet/stocks/*` | 17,091 | **0** | **0** | ✅ 干净（仅 ordinal 时间问题，见 §4） |
| `data/parquet/indices/*` | 860 | **385,616** | **83,612** | ❌ 大面积损坏 |
| `data/A股数据.zip` | 1 | 1.71 GB | — | 源存档（见 §5） |

### 2.1 指数损坏样例（`idx_000010_60min.parquet` 第 3 行）
```
      time    open        high       low        close       tick_volume
3   1073178 -187312.21 -187312.53 -187320.84 -187287.34  -9223372036854775808
```
- 价格出现**负数**（价格不可能为负）→ 该行无效。
- `tick_volume = int64.min` → 缺失哨兵，非真实成交量。
- 损坏**非仅头部**：860 个指数文件累计 38.5 万异常行，属系统性导出/采集缺陷。

### 2.2 股票为何干净
`000001_60min.parquet` 的 OHLC 均为正浮点（如 10.06/10.13...），无哨兵体积。股票数据可放心使用。

---

## 3. 修复方案（`tools/repair_indices_parquet.py`）

**策略**：
1. 对每个 `idx_*.parquet`：
   - 删除 `OHLC 任一 <=0` 或 `high < low` 的整行（价格非法，无可挽救）；
   - `tick_volume == int64.min` 置为 `pd.NA`（保留 OHLC 合法的行，仅清空缺失成交量）。
2. **先备份**：原文件复制到 `data/parquet/indices/_backup_<时间戳>/` 后再覆盖。
3. **默认 dry-run**：只打印每文件计数；`--apply` 才落盘。

**取舍与风险**（重要，执行前必读）：
- **符号翻转假设**：若损坏实为「某数据块整体符号写反」，正确修复是翻转符号而非删行。抽样看 `-187312` 与相邻正常行（26万级 / 47万级）无干净对应关系，**更可能是非法值而非单纯翻转**，故默认「删行」。如需翻转方案，改脚本 `fix_mode=flip` 并人工抽验。
- **删行会缩短序列**：385k 行移除后，部分指数 K 线在缺失处断开。指标（MA/ATR）在断点处会有空窗——`core/indicators` 需对 `NaN` 稳健（已在 supertrend/pa_agent 用 `dropna`/暖机，风险可控）。
- **备份可回滚**：`_backup_*` 目录保留原文件，发现误删可整体还原。

**运行（需你确认后执行）**：
```powershell
# 1) 先 dry-run 看计数（不改文件）
uv run python tools/repair_indices_parquet.py

# 2) 确认无误后真正修复（自动备份原文件）
uv run python tools/repair_indices_parquet.py --apply
```

---

## 4. ordinal 时间编码（设计取舍，非 bug）

`configs/a_shares.yaml` 中 `a_stocks`/`a_indices` 的 `time_mode: "ordinal"`：
- `time` 列为 `int64` 顺序整数（如 `1719397`），**非 unix 时间戳**，无真实日期。
- 这是**有意为之**（YAML 注释：「time 为非 unix 顺序整数，datetime 置 NaT 保序」），用于保序、避开源数据时间字段脏的问题。
- **代价**：无法做「星期几 / 是否交易日 / 跨日」等基于日期的特征。
- **建议**（低优先级，非阻塞）：若需日期特征，按 `{symbol}_{tf}` 的已知 bar 间隔 + 一个起始 epoch 反推真实时间，写回 `datetime` 列；stocks 与 indices 同样处理。当前不影响信号产出。

---

## 5. `A股数据.zip`（1.71 GB）取舍

- 位置：`data/A股数据.zip`，已被 `.gitignore` 的 `*.zip` 排除，**不入库**。
- 性质：parquet 的**源导出包**，与当前 `data/parquet/*` 同源。
- **建议：保留作源存档**，不删除。
  - 若磁盘紧张，可移到 `vendored/_archive/A股数据.zip` 或外置冷存储，而非删。
  - 注意：损坏源于导出过程，重新解压**不会**得到干净 indices，故它不能作为「一键修复」来源。

---

## 6. 统一回测框架（现状与建议，非本次修复）

`core/backtest/` 已具备：`engine.EventEngine`（事件驱动）、`grid.GridBacktester`、`metrics.compute_metrics`。
但各策略回测仍**各自为政**：
- `okx_grid` → 用 `grid.GridBacktester`
- `alphamaster` → 模块内独立回测
- `sentiment` → 独立 `backtest`
- `pa_agent` → 无回测入口

**建议（后续 Phase）**：以 `core/backtest/engine + metrics` 为统一接口，各策略实现 `backtest(**kwargs) -> MetricsDict`，由 `apps/api` 的 `/strategies/{name}/backtest` 统一调度。本次不改动（避免波及在跑策略）。

---

## 7. 行动清单（待你拍板）

| 项 | 动作 | 风险 | 建议 |
|---|---|---|---|
| 指数 385k 损坏行 | 跑 `repair_indices_parquet.py --apply`（先备份） | 中（序列断开） | ✅ 建议执行 |
| ordinal 时间 | 反推真实 datetime | 低 | 可选，低优先级 |
| `A股数据.zip` | 保留 / 外置 | 无 | ✅ 保留 |
| 统一回测 | 后续 Phase 重构 | 中（波及在跑策略） | 暂缓 |
