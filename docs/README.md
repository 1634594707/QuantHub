# QuantHub 文档索引

项目行为以源码、测试和配置为准；本文档列出当前维护的入口。

## 使用与交付

- [项目说明](../README.md)：功能、安装、启动、配置和验证命令。
- [用户功能路线图](../USER_FUNCTIONAL_ROADMAP.md)：当前用户视角的功能完成状态、源码依据与实施顺序。
- [上一轮功能路线图](../FUNCTIONAL_ROADMAP.md)：已经交付的执行、账本和运行控制基线记录。
- [升级与扩展](UPGRADE.md)：版本、配置迁移、扩展接口、备份恢复和回滚。
- [运营控制台维护说明](OPERATIONS_CONTROL.md)：自动化、备份和故障状态中心的接口与验收边界。
- [部署与数据库迁移](DEPLOYMENT.md)：本机、局域网、PostgreSQL、CORS、认证和 Alembic 操作边界。

## 架构与质量

- [架构文档](ARCHITECTURE.md)：分层、数据流、策略插件、信号与实盘安全边界。
- [代码质量规范](CODE_QUALITY.md)：模块边界、测试要求、危险操作和评审清单。
- [数据质量](DATA_QUALITY.md)：现有数据核查结果、修复工具和待确认事项。
- [质量门禁与发布检查](QUALITY_GATES.md)：性能基线、数据量门禁、恢复演练和发布清单。
- [真实券商与交易所适配评估](LIVE_TRADING_ADAPTER_EVALUATION.md)：当前执行通道缺口、接入门槛和 `live_trading=false` 边界。

## 前端与专业工具

- [前端重新设计规划](../design/FRONTEND_REDESIGN_PLAN.md)：目标信息架构、视觉系统、页面模板和分阶段实施路线图。
- [前端细节优化路线图](../design/FRONTEND_DETAIL_ROADMAP.md)：全局检索、URL 状态、异步请求四态、键盘、移动端和高频业务页面的勾选式实施状态。
- [前端布局优化路线图](../design/FRONTEND_LAYOUT_ROADMAP.md)：chrome 信息归属、统一页面骨架、布局原语、断点四档收敛和 CSS 资产收敛的勾选式实施状态。
- [Phase 0 视觉验收记录](../design/PHASE_0_VISUAL_ACCEPTANCE.md)：关键页面四视口基线、Phase 1 验收项和 2026-07-27 前端细节验收结果。
- [Web UI 控制文档](../design/UI_CONTROL_PANEL.md)：当前路由板块、样式真值源和组件入口。
- [PA Agent](../apps/pa_agent/README.md)：桌面工具安装、启动与配置入口。
- [PA Agent 数据获取](../apps/pa_agent/docs/获取数据功能说明.md)：桌面工具的数据获取行为。
- [PA Agent K 线与快照](../apps/pa_agent/docs/图表K线与分析快照说明.md)：图表、收盘 K 线和分析快照行为。

## 维护规则

- 完整浏览器回归使用 `cd web; npm run e2e:isolated`，由脚本启动隔离的 API 与 Vite 服务并在结束后关闭；2026-07-27 验收结果为 52/52，包含 5 项 axe 检查和 2 项稳定截图比较。
- 2026-07-27 四视口截图位于 `design/baselines/2026-07-27/`，覆盖 6 个关键页面和 `1440x900`、`1024x768`、`768x1024`、`390x844`，共 24 张 PNG。

- 新增文档必须进入本索引，或在所属模块 README 中建立入口。
- 当前产品功能状态只维护 `USER_FUNCTIONAL_ROADMAP.md`；`FUNCTIONAL_ROADMAP.md` 保留为上一轮交付记录；前端方向维护在 `design/FRONTEND_REDESIGN_PLAN.md`，细节实施状态维护在 `design/FRONTEND_DETAIL_ROADMAP.md`。
- 阶段性联调记录、一次性设计原型和生成报告不进入长期文档目录。
- 删除或移动 Markdown/HTML 文档前，先执行本地引用检查。
