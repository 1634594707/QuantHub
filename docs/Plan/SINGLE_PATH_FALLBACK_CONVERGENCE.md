# 单路径 Fallback 收敛路线图

## 目标

将产品运行路径收敛为明确、可审计的单路径：新接口、新存储或新策略一旦被指定为真源，失败必须显式返回错误或进入人工恢复状态，**不得自动回退到旧接口、旧路由、旧存储或旧算法**。

本路线图落实以下原则：

1. 每个业务动作只拥有一个正式写入/执行路径。
2. 迁移后的旧代码可保留用于历史只读，但不得成为新流程的运行时后备。
3. 失败应携带来源、原因和可执行的恢复动作；不以静默降级伪造成功。
4. 缓存恢复、同一端点的有限重试、以及 WebSocket 断线后的账户对账补偿是窄范围例外，不能扩展为旧路径回退。
5. 交易、风控与可执行信号采取 fail-closed；研究展示如允许降级，必须由调用方显式选择并暴露来源与质量状态。

## 当前状态

本收敛工作于 2026-08-25 完成 P0--P4 的代码整改、覆盖性测试和前端构建；保留行为已收束到本文的窄范围例外，不能作为切换旧路径、旧真源或替代算法的依据。全量验证数字以本轮实际运行结果为准；若执行环境缺少依赖或临时目录权限不足，必须单独记录，不得记作通过。

## 范围与完成顺序

### P0：切断旧 Demo 运行路径（已完成）

**问题**：`/simulation/demo/*` 已被定义为历史兼容读取，但新因子工厂仍通过它创建回测和 `data/demo_runs/*.json`。

**处理**：

- 删除新因子工厂对 `POST /simulation/demo/run` 的调用。
- 让因子工厂手动回测使用因子工厂自身的受控回测服务与响应契约。
- 将 `/simulation/demo/*` 收敛为历史只读接口；不再暴露创建新运行的 API。
- 移除 DemoLab 中遗留的新运行状态、表单和调用代码。
- 用 API、前端和服务层测试证明新流程不再访问旧路径、旧目录不再接收写入。

**验收**：新因子工厂运行不含 `/simulation/demo/` 调用；尝试写旧 Demo 路径得到明确的不可用响应；旧记录仍可读取。

**结果**：Demo 路由仅保留历史 `GET /simulation/demo/runs*`；因子工厂的受控回测不再写入 `data/demo_runs` 或调用 Demo 创建接口。

### P1：移除真源失败后的旧本地存储回退（已完成）

**问题**：策略运行、预设、持仓和自选把 SQLite/API 声明为真源，却在失败时呈现 `*.v1` localStorage 的旧数据。

**处理**：

- 删除策略运行和参数预设的 localStorage 持久化、读取和离线回退。
- 删除持仓/自选的 localStorage 真源替代；仅保留当前页面内未提交草稿与同一 API mutation 的错误回滚。
- API 读取或写入失败时显示/返回明确错误，不伪装为当前真源数据。
- 保留与业务真源无关的 UI 偏好（例如界面模式、收藏）作为本地偏好，不作为业务数据 fallback。

**验收**：网关不可达时业务列表不会显示旧 `v1` 数据；重新连接后只读取后端数据；本地草稿不跨刷新冒充已保存记录。

**结果**：策略运行、预设、持仓和自选均以 API/SQLite 为唯一业务真源；失败由调用方显示，页面内未提交草稿只用于当前交互。

### P2：收紧市场数据与风控边界（已完成）

**问题**：数据源代理在 primary 失败、空结果或构造失败时自动切换供应商/本地 Parquet；风险快照无法区分实时主源与历史降级数据。

**处理**：

- `get_data_source()` 只构造并调用配置 primary；primary 构造、请求或数据质量失败时显式失败。
- 删除项目默认配置中的自动 fallback 链；备用源只能经明确的直接选择接口用于研究或诊断。
- 删除同一业务在失败后切到不同供应商/端点的隐式链路（包括估值与指数成分股）。
- 市场快照传递实际来源、市场 bar 时间和质量；风险校验基于行情时间而不是请求完成时间。
- 交易/风控拒绝历史、本地、未知或过期行情；不把已降级数据标记为 `available`。
- A/US realtime analyzer 默认要求至少 21 根 primary K 线；只有显式 `with_kline=False` 才允许 quote-only 展示，并在报告、行情证据和 Signal metadata 中标记 `display_only/degraded/execution_eligible=false`。
- selector、SuperTrend、OKX grid、AlphaMaster、AlphaGPT 对缺失/非有限行情或公式异常整批 fail-closed；不得跳过坏品种后发布部分信号。

**验收**：primary 失败不会请求第二个供应商；local parquet 不会作为在线失败后的隐式结果；风险测试证明过期或非实时数据被拒绝。

**结果**：数据源工厂只构造已配置 primary，旧 `data_sources.fallback` 配置被拒绝；实时分析、风险和可执行标的解析均要求可验证的来源、市场、价格与新鲜度。

### P3：移除兼容分支和旧契约自动重路由（已完成）

**问题**：订单查询、研究运行和 AI 复核仍存在“主接口失败后换实现”或“旧请求缺字段时重建新对象”的行为。

**处理**：

- 将 OKX 订单列表收敛到一个明确的 OKX/CCXT 正式实现；不再先试通用接口再换分支。
- 强制因子 AI 复核提供已保存的 `run_id`，只读该快照；不因缺少 ID 重新计算。
- 研究运行 ID 与标的/市场/周期不一致时直接拒绝，不新建替代 run。
- dispatcher/router 对未配置或未授权 source、crypto 多执行源、方向平票、hold、display-only/degraded 信号显式拒绝；未知 source 不再隐式赋予默认权重。
- 保留的历史记录兼容只能显式标记为只读、不完整或不可执行，不能升级为当前结论。

**验收**：测试覆盖主路径失败、上下文不一致和缺失 run ID，均没有第二条业务路径被调用。

**结果**：订单查询、因子 AI 复核与研究上下文均只接受正式契约；缺失或不匹配的运行标识直接失败，不重建替代运行。

### P4：收紧算法与模型降级（已完成）

**问题**：缺失训练产物、因子、模型或 API 时，部分策略会自动使用启发式、关键词或其他模型输出继续产出结果。

**处理**：

- AlphaMaster/AlphaGPT 缺少已验证策略产物时停止产生信号，而不是自动选择启发式公式。
- AlphaMaster/AlphaGPT 的 OHLCV 缺列、非数值、非有限值和 StackVM 公式执行/结果异常均整批拒绝；不以零值、空评分或剩余公式替代。
- 因子策略缺少明确因子时拒绝回测，不默认 `momentum`。
- 调度配置缺失时不使用示例标的启动实际分析。
- 对仍被保留的非执行性展示降级，明确标记 `degraded`，并确保不能转换为可执行信号或交易授权。

**验收**：缺少模型、公式或配置的策略返回显式不可用状态；不产生替代信号；允许的展示降级具有可观察标记和执行阻断。

**结果**：策略产物、公式、调度配置、FinBERT2 和配置 LLM 缺失时均 fail-closed；展示级诊断不会被转化为研究证据、Ensemble 输入或交易信号。

## 明确保留的窄范围例外

以下不是旧接口/旧路径 fallback，保留但必须维持边界：

| 例外 | 边界 |
| --- | --- |
| 数据源绑定缓存 | K 线和文档缓存带 market/source 身份，只服务同一 primary；不命中或 primary 失败时不查找其他供应商。 |
| 实时行情 | 实时 quote 不进入缓存；来源、报价时间、市场和价格任一不合格即拒绝发布可执行结论。 |
| 因子工厂闭合 K 线模拟 | 仅在 `account_id=factor-factory:<id>` 且 trusted snapshot 同时满足 `source=factor_factory.closed_bar`、`quality_status=closed_bar` 和有效 `event_time` 时，构造规范化的内部 OKX USDT 永续身份并走隔离成交；普通 crypto 订单仍必须通过当前 OKX 公共目录验证。 |
| 同一端点的有限网络重试 | 不改变 URL、供应商、请求 schema 或数据语义。 |
| 本地快照损坏后的同一实时端点重新拉取 | 仅恢复缓存，不读取旧业务路径。 |
| OKX 私有 WebSocket 断线后的 REST 对账补偿 | 只重建账户/订单状态并记录证据，不作为旧交易 API 或下单路径。 |
| 历史记录只读展示 | 明确标记历史/不完整，禁止作为当前交易或研究真源。 |
| 标的名称元数据补全 | `tencent_quote_detail` 仅用于 A/美股展示名称；价格、涨跌幅和时间字段被丢弃，不进入 NAV、风控、研究证据或订单身份；请求失败时保留空名。 |
| UI 偏好本地保存 | 仅保存界面偏好，不保存业务真源或待执行交易状态。 |

## 验证矩阵

1. 后端单元测试：旧 Demo 写接口、数据源 primary 失败、市场快照新鲜度、订单查询、AI review `run_id`、研究上下文不匹配、模型/公式缺失、dispatcher source/tie/执行资格边界、factor-factory 闭合 bar 例外。
2. 前端测试：策略运行/预设/持仓/自选在 API 失败时展示错误而非旧缓存；因子工厂不调用 Demo API；quote-only realtime 信号保持展示但不可执行。
3. 静态检查：搜索生产代码中的 `fallback`、`legacy`、`localStorage`、`simulation/demo`，逐项归类为删除、显式只读或上述窄范围例外。
4. 构建验证：后端测试、Web 类型检查、Web 测试和生产构建。

## 变更记录

- 本文创建时，尚未把历史 fallback 行为视为可接受的默认兼容策略；后续每个保留例外必须在对应代码与测试中有清晰原因。
- 2026-08-25：补齐 dispatcher/router 的 source、crypto 执行源、方向平票及 execution metadata 门禁；补齐 realtime analyzer 的 primary K-line gate 与 quote-only display-only 标记；补齐 selector、SuperTrend、OKX grid、AlphaMaster、AlphaGPT 的整批 fail-closed 行为。
- 2026-08-25：修复 factor-factory 隔离闭合 bar 在严格 crypto instrument 解析下的窄范围例外；普通订单不绕过 `_verified_okx_swap_contract`。对应旧测试改为显式传递受信闭合 bar 快照。
- 2026-08-25：最终复验使用项目 `.venv` 与工作区隔离 basetemp：后端全量 `575 passed, 2 skipped in 73.01s`（无失败）；前端 `npm.cmd run typecheck` 通过，`npm.cmd test` 为 `174 passed`（41 files），`npm.cmd run build` 通过。使用系统 Python 的尝试因缺少 `apscheduler`/`pa_agent` 仅作环境诊断，不计入代码失败。
- 2026-08-25：任务文件 Ruff 与 `git diff --check` 通过；全仓 Ruff 仍报告既有上游问题，未在本次收敛范围内修改。
- 2026-08-25：公告监控移除运行时示例股票池回退，`configs/a_shares.yaml` 改为显式配置 47 只标的；缺失配置时 `PerksMonitorStrategy` fail-closed 并标记为不可执行展示。scheduler 通用入口统一通过 `configured_strategy_config()` 传递模块配置，删除 `TypeError` 后用默认 timeframe 重试的隐式兼容分支。
- 2026-08-25：补齐 selector 调度的显式 `modules.selector.universe`（当前为 `hs300`）；配置缺失时不解析指数成分或构造行情源。组合估值仅接受已标记的 primary `closed_bar` 或同源缓存快照，未验证/本地/未知正数行情保持不可用并保留 provenance。
