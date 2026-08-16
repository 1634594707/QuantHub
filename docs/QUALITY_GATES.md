# 质量门禁与发布检查

## 自动化门禁

CI 当前执行：

- React 前端 TypeScript 类型检查与生产构建。
- Python 后端字节码编译。
- FastAPI 应用导入检查。

本地执行：

```powershell
uv sync
uv run python -m compileall -q apps/api apps/dispatcher apps/scheduler core strategies
uv run python -c "from apps.api.main import app; assert app.title"
Set-Location web
npm.cmd ci
npm.cmd run typecheck
npm.cmd run build
```

涉及研究、风控、执行或归因契约时，还必须运行：

```powershell
uv run --frozen python -m pytest -q
Set-Location web
npm.cmd run test -- --run
npm.cmd run typecheck
npm.cmd run build
```

2026-08-16 闭环基线：后端 `392` 项、前端 `152` 项通过；Chromium 在 `390x844`、`768x1024`、`1440x900` 三个视口完成阻断态、冲突与历史差异、归因筛选与守恒验收。

## 当前基线

`tools.quality_baseline` 使用隔离临时 SQLite 数据库，不读取或修改业务库。默认门限：

- 10,000 条信号批量写入不超过 15,000 ms。
- 查询最新 200 条信号的 20 次采样 P95 不超过 250 ms。
- 输出实际记录数、数据库字节数、schema 初始化耗时、写入耗时、中位数和 P95。

性能基线属于按需运维检查，不再作为精简网页项目的 CI 门禁。

## 故障演练

`tools.run_recovery_drill` 在隔离临时目录中执行：

1. 初始化完整业务 schema 并写入恢复探针。
2. 创建事务一致的 SQLite 备份。
3. 篡改探针后执行带安全备份的恢复。
4. 校验恢复值和 `PRAGMA integrity_check`。
5. 把持久化任务置为 `running`，模拟进程中断后执行 `recover_pending_runs()`。
6. 校验任务回到 `queued` 且只提交一次执行器。

## 发布检查清单

- [ ] `live_trading` 保持 `false`，除非本次发布单独通过真实执行评审。
- [ ] Alembic `current` 与 `head` 一致。
- [ ] 前端类型检查、生产构建和 FastAPI 导入检查全部通过。
- [ ] 涉及数据库结构时，Alembic `current` 与 `head` 一致。
- [ ] 涉及数据恢复时，手工执行恢复演练并记录安全备份路径。
- [ ] 局域网或 PostgreSQL 模式的 CORS 不含 `*`。
- [ ] 管理令牌不少于 32 个字符，业务用户使用独立 token。
- [ ] `/governance` 中没有过期但仍有效的无人使用令牌。
- [ ] 发布说明列出 schema revision、回滚步骤和已知限制。
