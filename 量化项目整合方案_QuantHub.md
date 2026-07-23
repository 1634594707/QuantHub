# QuantHub 量化项目整合方案（v2 · 落地稿）

> 版本：v2（2026-07-15）。v1 为早期评审稿，本版反映**已落地现状**。
> 状态：**脚手架 + 底座 + 7 个源项目收口 + 11 策略 + 统一 API 网关 已完成**；数据质量（P-C）已完成只读调研并给出修复方案，待执行。
> 一句话：把 `finance` 下 7 个分散量化项目，收口为分层单体仓库 **QuantHub**（统一底座 + 插件式策略 + 单端口 API 网关）。

---

## 0. 相对 v1 的变化

| 维度 | v1（评审稿） | v2（现状） |
|---|---|---|
| 源项目处理 | 仅 6 个，讨论是否合并 | **7 个全部 vendored 只读归档**（见 §2） |
| 市场覆盖 | A股 + 加密 | **+ MT5（外汇/贵金属/股指）**，AlphaMaster 因子引擎零拷贝接入 |
| 策略数 | 10 | **11**（新增 `alphamaster` + `realtime_analyzer`） |
| 服务形态 | 各自 FastAPI/Flask 分散 | **单端口 `apps/api` 网关 front 全部策略**（见 §3.3） |
| 可视化 | 仅 Streamlit 组件 | **+ `core/viz` 自包含 HTML 报告生成器** |
| 调度 | 仅 4 个 A股任务 | **覆盖全部已启用市场/策略**（见 §9） |
| 数据质量 | 未涉及 | **只读调研完成**：指数 38.5 万损坏行，给出修复脚本（见 §7 / `docs/DATA_QUALITY.md`） |

---

## 1. 整合目标与原则

**目标**：把分散的 A股研究、加密交易、MT5、AI 分析项目，整合为一个**可维护的分层单体仓库（QuantHub）**：
- 市场覆盖 **A股 + 加密 + MT5**（各自成模块，共享底座）
- 支持**实盘但默认研究模式**，可一键开关
- 前端统一为 **Streamlit 看板**；对外能力统一收口为 **单端口 API 网关**

**原则**：
1. **单一底座**：数据 / 信号 / 告警 / LLM / 回测 / 可视化只实现一次。
2. **插件式策略**：每个原项目下沉为一个策略模块，通过统一接口挂载，互不污染。
3. **实盘安全优先**：涉及下单的代码默认关闭，必须显式配置 + 二次确认。
4. **vendored 只读归档**：7 个源项目移入 `vendored/`（gitignore，只读参考副本），仓库根只留 `strategies/` 的统一实现，消除重复逻辑。
5. **渐进迁移**：先底座后业务、先 A股后加密/MT5，逐模块验证不破坏原功能。

---

## 2. 现状盘点与收口决策

**7 个源项目已全部移入 `vendored/`（只读归档，gitignore）：**
`agent/`（PA_Agent）、`AlphaGPT/`、`AlphaMaster-main/`、`Python撸大A羊毛：量化监控系统`、`trading-master/`、`用Python写了一套市场情绪系统`、`高级网格策略+可视化实战课源码/`。

| 项目 | 市场 | 可复用核心 | 整合去向 |
|---|---|---|---|
| 高级网格策略+可视化（OKX Grid Master） | 加密 | `selector` 多因子选币、`backtest/engine` 网格回测、`okx_api` | `strategies/crypto/okx_grid` |
| 市场情绪系统（SentimentQuant） | A股 | `SentimentAnalyzer`、`data_fetcher`、`backtest` | `strategies/a_shares/sentiment` |
| agent（PA_Agent） | 多源 | `data/indicators/two_stage` LLM 编排 | `strategies/ai_analysis/pa_agent` |
| AlphaGPT | 加密 | `StackVM` 公式 DSL、`factors`、`risk` | `strategies/crypto/alphagpt` |
| 量化监控系统（羊毛） | A股 | 东财公告爬虫、`WeChatPusher`、股票池 | `strategies/a_shares/perks_monitor` |
| trading-master | A股 | `scanner`、`SuperTrend`、`pivot` 评分 | `strategies/a_shares/{news_scanner,selector,supertrend,morning_brief}` |
| **AlphaMaster-main** | **MT5** | Transformer 自动写因子 → `StackVM` → `MT5FeatureEngineer`（65 维特征） | **零拷贝接入**：`strategies/mt5/alphamaster` 经 `sys.path` 注入 `vendored/AlphaMaster-main`，复用其 `model_core.*`，**不复制 152 文件** |

**重叠点**（底座统一的最大收益）：A股数据层、企微告警、DeepSeek LLM 客户端、回测框架、可视化均被重复实现 → 统一到 `core/`。
**差异点**：市场（A股/加密/MT5）、是否实盘、前端技术栈各不相同 → 用模块 + 配置隔离。

---

## 3. 目标架构（已落地）

```
应用层 Apps
 ├─ dashboard   (Streamlit 统一看板)
 ├─ dispatcher  (信号中枢：汇聚 → 风控 → 下单路由，默认 dry-run)
 ├─ scheduler   (APScheduler 定时任务：覆盖全部已启用策略/市场)
 └─ api         (统一 API 网关：单端口 front 全部 11 策略 + 信号总线读写)

策略模块 Strategies（插件式挂载，11 个）
 ├─ a_shares/   sentiment · news_scanner · selector · supertrend · morning_brief · perks_monitor · realtime_analyzer
 ├─ crypto/     okx_grid · alphagpt
 ├─ mt5/        alphamaster          （AlphaMaster 因子引擎零拷贝）
 └─ ai_analysis/ pa_agent

统一底座 Core
 ├─ data_feed  (多源行情/公告：akshare/东财/OKX-ccxt/本地 parquet + SQLite 缓存)
 ├─ signals    (统一 Signal 对象 + 轻量总线)
 ├─ alert      (企微/Webhook/Telegram)
 ├─ llm        (DeepSeek/OpenAI 兼容，支持本地模型)
 ├─ backtest   (网格回测 + 事件驱动引擎 + 统一指标)
 └─ viz        (Streamlit 组件库 + Plotly helper + 自包含 HTML 报告生成器)
```

### 3.1 统一底座 `core/`
- **data_feed**：聚合 akshare、东方财富 push2、腾讯/新浪、OKX(ccxt)、本地 parquet；统一 `Kline/News/Announcement`；SQLite 缓存 + 退避重试。
- **signals**：统一 `Signal` 数据类（`symbol, market, timeframe, direction, score, confidence, source, tags, ts`）+ 轻量总线，模块间传递信号；dispatcher 按 `base.yaml` 的 `signals.weights` 加权聚合。
- **alert**：企微/Webhook/Telegram 统一通知。
- **llm**：DeepSeek/OpenAI 兼容客户端，`get_llm()` 自动按环境变量解析后端。
- **backtest**：`grid.GridBacktester` + `engine.EventEngine`（事件驱动）+ `metrics.compute_metrics`（统一绩效）。各策略回测接口尚待统一（见 §10）。
- **viz**：Streamlit 组件 + Plotly helper + **`HTMLReport` 自包含 HTML 报告生成器**（暗/亮双主题，默认暗色；`add_heading/paragraph/markdown/card/table/chart`；Plotly 缺失时优雅跳过；可落盘/邮件/企微）。

### 3.2 策略模块 `strategies/`（插件式，11 个）
- **A股组（7）**：`sentiment`、`news_scanner`、`selector`、`supertrend`、`morning_brief`、`perks_monitor`、`realtime_analyzer`（东财盘口+腾讯日K+指数宽度 → GPT/DeepSeek 深度研报，无 LLM 时降级快照）。
- **加密组（2）**：`okx_grid`（selector 多因子选币 + 网格回测 + 下单，默认关）、`alphagpt`（StackVM 因子 DSL + 链上执行，默认关）。
- **MT5 组（1）**：`alphamaster`（AlphaMaster 因子引擎零拷贝接入，tanh 连续仓位，默认关）。
- **AI 分析组（1）**：`pa_agent`（价格行为两阶段 LLM 分析，只分析不下单）。

### 3.3 应用层 `apps/`
- **dashboard**：Streamlit 统一看板，聚合所有模块结果/回测/信号/监控。
- **dispatcher**：信号中枢——汇聚 `signals` → 风控（`RiskChecker`）→ 路由到 OKX/链上/条件单（默认 dry-run，仅输出拟下单 JSON，实盘需 CLI `CONFIRM` 二次确认）。
- **scheduler**：APScheduler 定时任务；从各市场 yaml 的 `modules.<name>.cron` 读取并注册，自定义 runner 走模块级 `run_*` 函数，其余走通用 `_run_strategy`。**当前注册 7 个任务**：6 个 A股（含原缺 cron 的 `news_scanner`/`supertrend`）+ `ai_analysis/pa_agent`；crypto/mt5 模块默认 `enabled:false`，启用即进调度。
- **api**（**统一网关，本版核心**）：单进程单端口 `uvicorn apps.api.main:app --port 8000`，front 全部 11 策略：
  - `GET /health · /strategies · /strategies/{name} · /signals`
  - `POST /strategies/{name}/run · /signals/publish`
  - `_call_produce` 用 `inspect` 反射过滤参数，兼容各策略异构 `produce()` 签名；单策略失败不影响网关；CORS 放开供看板直连。
  - **取代**源项目里各自绑端口的 FastAPI/Flask 服务。

---

## 4. 实盘开关与安全设计
- 全局开关 `configs/base.yaml`：`live_trading: false`（默认研究模式）。
- 每实盘模块自带 `enable` + `live` 标志，需显式 `true` 且环境变量存在才激活（OKX/链上/MT5 密钥）。
- 下单前 `dispatcher` 强制风控（`RiskChecker`：仓位/流动性/蜜罐）+ CLI 二次确认。
- 密钥仅存环境变量（`.env` 已被 gitignore），禁止入库。
- **dry-run 模式**：输出拟下单 JSON 供人工复核，不直接报单。

---

## 5. 目录结构（已落地）
```
QuantHub/
├── pyproject.toml          # uv workspace + [a_shares]/[crypto]/[ai]/[dashboard]/[backtest]/[api] 可选依赖
├── README.md
├── configs/                # base / a_shares / crypto / mt5 / ai_analysis（各市场 modules + cron）
├── core/                   # data_feed / signals / alert / llm / backtest / viz(含 html_report)
├── strategies/             # a_shares(7) / crypto(2) / mt5(1) / ai_analysis(1)
├── apps/                   # dashboard / dispatcher / scheduler / api
├── tools/                  # repair_indices_parquet.py（数据修复，dry-run 默认）
├── docs/                   # ARCHITECTURE / UPGRADE / DATA_QUALITY
├── models/                 # 大模型权重（FinBERT2 等，gitignore）
├── data/                   # parquet(stocks 干净 / indices 待修复) + A股数据.zip(源存档,gitignore)
├── vendored/               # 7 个源项目只读归档（gitignore）
└── tests/                 # 49 测试（34 底座 + 10 集成 + 5 api）
```

---

## 6. 依赖与版本统一
- **Python 3.11（<3.13）**：避开 torch/solana 在 3.13 的滞后。
- 单一 `pyproject.toml` + uv workspace；按模块可选依赖：`[a_shares]`/`[crypto]`/`[ai]`/`[dashboard]`/`[backtest]`/`[api]`/`[heavy-torch]`/`[heavy-solana]`。
- 统一基础库：`requests / pandas / numpy / pydantic / tenacity / loguru`。
- 重依赖（torch、solana/solders）放可选组，按需安装。
- **踩坑**：`.venv` 内 `cffi` 的 `.pyd` 偶发文件锁导致 `uv sync` 清理阶段失败 → 改用 `uv pip install <pkg>` 绕过（不动锁文件）。

---

## 7. 数据层统一要点与质量现状
- 抽象 `DataSource` 接口：`get_kline(symbol, market, interval)` / `get_news` / `get_announcements`；本地 parquet 优先，在线源回退；SQLite 缓存。
- **时间编码（设计取舍，非 bug）**：A股 parquet 的 `time` 列为 `int64` **ordinal 顺序整数**（非 unix 时间戳），`datetime` 置 NaT 保序。代价：无法做基于真实日期的特征（星期几/交易日）。如需，按 `{symbol}_{tf}` 已知 bar 间隔 + 起始 epoch 反推（低优先级，见 `docs/DATA_QUALITY.md` §4）。
- **指数数据损坏（真实问题，已调研）**：`data/parquet/indices/` 共 860 文件，累计 **385,616 行 OHLC 非法（负值）** + **83,612 行 volume=int64.min 哨兵**。股票（`stocks/`，17,091 文件）**零损坏**。修复脚本 `tools/repair_indices_parquet.py` 默认 dry-run，显式 `--apply` 才落盘且先自动备份；详见 `docs/DATA_QUALITY.md`。**当前未执行修复**，待确认。
- **`A股数据.zip`（1.71 GB）**：源导出包，已被 `*.zip` gitignore；与现有 parquet 同源（损坏源于导出过程，重解压无济于事）。**建议保留作源存档**，磁盘紧张时外置冷存储，不删除。

---

## 8. 信号总线设计
```python
@dataclass
class Signal:
    symbol: str
    market: str            # "a_shares" | "crypto" | "mt5" | "ai_analysis"
    timeframe: str
    direction: str         # "buy" | "sell" | "hold"
    score: float           # 0~1
    confidence: float      # 0~1
    source: str            # 策略名
    tags: list[str]
    ts: datetime
```
- 各策略 `produce()` → `Signal` 推入总线；`dashboard`/`dispatcher` 消费。
- dispatcher 按 `base.yaml` 的 `signals.weights` 加权聚合多源打分。

---

## 9. 迁移路线图（执行状态）
| 阶段 | 内容 | 状态 |
|---|---|---|
| Phase 0 | 脚手架：uv workspace + configs + 目录骨架 | ✅ |
| Phase 1 | 底座 `core/`（data_feed/signals/alert/llm/backtest/viz） | ✅ |
| Phase 2 | A股流水线（sentiment/selector/supertrend/perks_monitor/morning_brief/news_scanner） | ✅ |
| Phase 3 | 加密模块（okx_grid/alphagpt） | ✅ |
| Phase 4 | AI 分析（pa_agent 两阶段 LLM） | ✅ |
| Phase 5 | 信号中枢 + 实盘开关 + 风控 + 看板联调 | ✅ |
| Phase 6 | MT5 市场（alphamaster：AlphaMaster 因子引擎零拷贝接入） | ✅ |
| Phase 7 | A股实时分析器（realtime_analyzer）+ core/viz 自包含 HTML 报告 | ✅ |
| Phase 8 | 统一 API 网关（apps/api：单端口 front 全部 11 策略） | ✅ |
| **P-C** | 数据质量：指数 38.5 万损坏行修复（脚本就绪，待执行） | ⏳ 调研完成，待 `--apply` |
| **调度** | 调度器覆盖全部已启用市场/策略（含 news_scanner/supertrend/pa_agent） | ✅ |

---

## 10. 风险与注意
- **多 Python 库兼容**（torch / transformers / solana）→ 虚拟环境 + 可选依赖隔离。
- **数据源限流**（东财 / akshare）→ 统一缓存与退避。
- **实盘资金安全** → 默认关闭 + 风控 + dry-run，绝不直接报单。
- **合规**：A股与加密/MT5 监管差异，实盘需用户自行评估风险。
- **模型权重体积**（FinBERT2）→ `models/` 并 gitignore。
- **数据质量（P-C）**：指数 parquet 38.5 万损坏行；修复脚本 dry-run 默认、先备份，执行前需人工确认（符号翻转 vs 删行取舍见 `docs/DATA_QUALITY.md`）。
- **统一回测框架**：`core/backtest` 已具备 engine/metrics，但各策略回测仍各自为政（okx_grid 用 grid、alphamaster 独立、pa_agent 无），后续以 `core/backtest` 为统一接口重构（非阻塞）。

---

## 11. 待办（按优先级）
1. **P-C 数据修复（中优先级）**：确认 `tools/repair_indices_parquet.py --apply` 的执行（先自动备份）；建议默认 drop 模式。
2. **统一回测框架（低优先级）**：各策略实现 `backtest()` 返回统一 `MetricsDict`，由 `apps/api` 的 `/strategies/{name}/backtest` 调度。
3. **可选**：A股 ordinal 时间反推真实 datetime（启用日期类特征）。
4. **可选**：把 `vendored/AlphaMaster-main` 训练产出 `best_mt5_strategy.json` 放入 `strategies/mt5/alphamaster/`，替换 fallback 启发式公式。
