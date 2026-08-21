# QuantHub 文档索引

本目录包含当前长期文档，以及 `Plan/`、`releases/`、`posts/` 下的历史记录。
当前操作以根 README、部署/运维文档、源码、测试和配置为准；路线图与阶段报告不得
替代当前启动或安全说明。

## 使用与部署

- [项目说明](../README.md)：功能介绍、环境要求、安装、启动和验证命令。
- [v0.4.0 发布说明](releases/v0.4.0.md)：Web 工作台收口、Factor Factory、OKX Demo、真实行情与发布边界。
- [v0.3.0 发布说明](releases/v0.3.0.md)：AI 因子发现、安全 DSL、试验治理、真实基线、模拟审计和升级说明。
- [AI 因子发现路线图](../AI_FACTOR_DISCOVERY_ROADMAP.md)：任务状态、真实证据快照和剩余数据边界。
- [v0.2.0 发布说明](releases/v0.2.0.md)：上一版本的多窗口、跨标的、成本执行和持续复验说明。
- [v0.2.0 社区更新帖子](posts/2026-07-31-quanthub-v0.2.0.md)：可直接用于“工具与项目”板块的发布内容。
- [交易成本来源与录入边界](TRADING_COST_SOURCES.md)：A 股、中国结算、SEC、FINRA、OKX 与 MT5 来源及禁止推断的参数边界。
- [部署与数据库迁移](DEPLOYMENT.md)：本机、局域网、PostgreSQL、认证、CORS 和 Alembic。
- [部署、升级与运营手册](OPERATIONS_GUIDE.md)：统一启停、健康检查、备份恢复和故障处置。
- [OKX Runner 运维](okx_runner/OPERATIONS.md)：Runner 模式、日志、凭据、恢复与对账。
- [升级与扩展](UPGRADE.md)：版本升级、配置迁移、扩展接口、备份恢复和回滚。
- [PA Agent 能力审计与适配](PA_AGENT_ADAPTATION.md)：上游参考范围、输出质量闸门、交易质量分析和未迁移能力。

## 架构与质量

- [架构设计](ARCHITECTURE.md)：系统分层、数据流、策略插件、信号和执行安全边界。
- [功能边界](FUNCTION_BOUNDARIES.md)：产品能力归属、AI 模块边界和防重复准入规则。
- [代码质量规范](CODE_QUALITY.md)：模块边界、测试要求、危险操作和评审清单。
- [数据质量](DATA_QUALITY.md)：数据核查、修复工具和质量边界。
- [质量门禁](QUALITY_GATES.md)：性能基线、数据量门禁、恢复演练和发布检查。
- [实盘适配评估](LIVE_TRADING_ADAPTER_EVALUATION.md)：真实券商与交易所接入条件及当前限制。

## 运维与界面

- [运营控制台](OPERATIONS_CONTROL.md)：自动化、备份、故障状态和相关验收边界。
- [Web UI 控制文档](../design/UI_CONTROL_PANEL.md)：当前路由、样式真值源和组件入口。

## 产品需求与用户体验

- [用户体验、分类与分析报告改进需求](PRODUCT_USABILITY_AND_REPORT_REQUIREMENTS.md)：基于当前源码的高频用户审查、市场能力矩阵、报告改进、多用户隔离和后续验收要求。

## 历史归档

- `releases/`：各版本发布时的能力与验证记录。
- `posts/`：历史社区发布材料。
- `Plan/`：阶段路线图、任务状态和验收证据，只反映对应日期的上下文。
- `archive/`：已被新需求文档替代但保留原始内容的历史文档。
- [历史归档说明](archive/README.md)：归档目录结构和当前文档真值源。
- `archive/roadmaps/`：已完成或明确归档的专项路线图与阶段需求。
- `archive/reports/`：阶段完成报告与验证汇报。
- `archive/releases/`：旧版本因子治理与研究基线材料。
- `archive/notes/`：个人研究笔记和过程性材料。
- 根目录 `AI_FACTOR_DISCOVERY_ROADMAP.md`：当前仍在维护的因子发现路线图。
- `archive/roadmaps/` 与 `archive/reports/`：专项实施记录；阅读时以文首日期和归档声明为准。

## 维护规则

- 新增长期文档时，应在本索引中提供入口。
- 路线图、阶段计划和验收记录需要明确日期与归档状态，不得作为当前启动说明。
- 删除或移动文档前，应检查 README、代码注释和其他文档中的引用。
- 文档中不得包含 API Key、访问令牌、数据库密码或真实交易凭据。
