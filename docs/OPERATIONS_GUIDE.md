# QuantHub 部署、升级与运营手册

> 适用范围：主 Web 工作台、统一 API，以及无 UI 的 OKX Runner 执行服务。

## 1. 版本与配置

- 仓库版本来自 `pyproject.toml`，遵守语义化版本。
- 配置 schema 来自 `configs/base.yaml: schema_version`。
- 策略版本由 `StrategyInfo.version` 独立维护。
- 数据库结构由 Alembic revision 管理。
- 配置新增字段提供默认值；不兼容变更必须递增 schema 并提供逐版本迁移。
- 废弃公共接口至少保留一个 MINOR 版本，并在发布说明中标记删除版本。

## 2. 部署模式

QuantHub 支持 `local`、`lan` 和 `postgresql` 三种模式，启动约束由 `apps/api/deployment.py` 与 `apps/api/database.py` 校验。

### 2.1 本机模式

模板：`configs/deployment.local.env`。

- `QUANTHUB_DEPLOYMENT_MODE=local`
- 默认监听 `127.0.0.1`。
- 默认 CORS 只允许 `http://localhost:5173` 和 `http://127.0.0.1:5173`。
- `QUANTHUB_STORE_PATH` 指定 SQLite；未设置时使用 `apps/api/store.db`。
- 可使用 `QUANTHUB_AUTH_REQUIRED=1` 强制 Bearer token。

### 2.2 局域网模式

模板：`configs/deployment.lan.env.example`。

- `QUANTHUB_CORS_ORIGINS` 必须列出完整来源，禁止 `*`。
- `QUANTHUB_BOOTSTRAP_ADMIN_TOKEN` 至少 32 个字符。
- `/health` 之外的请求要求 Bearer token。
- 恢复、保留策略和备份写操作要求 `backups.manage`。
- 创建独立业务用户和令牌后，应撤销不再使用的引导令牌。

### 2.3 PostgreSQL 模式

模板：`configs/deployment.postgresql.env.example`。

- 必须设置 `QUANTHUB_DATABASE_URL=postgresql+psycopg://...`。
- 认证、CORS 和令牌约束与局域网模式相同。
- `/backups` 只支持 SQLite，在 PostgreSQL 模式拒绝执行。
- PostgreSQL 使用 `pg_dump`、存储快照或托管恢复点完成备份。

## 3. 数据库迁移

```powershell
$env:UV_CACHE_DIR=(Resolve-Path '.uv-cache').Path
uv run alembic upgrade head
uv run alembic current
```

规则：

- 结构变更必须新增 revision。
- 升级前在旧库副本和空库上分别执行 `upgrade head`。
- 迁移不得读取网络或依赖运行中后台任务。
- 删除或不可逆转换需要单独的数据备份和回滚方案。
- PostgreSQL 与 SQLite 支持范围不同的变更必须在发布说明中明确。

## 4. 启动与健康检查

Windows 本地推荐使用统一脚本。默认启动 Web、API 和 shadow 只读 Runner：

```powershell
powershell -ExecutionPolicy Bypass -File tools/start-quanthub.ps1 -SkipSync

# OKX 模拟盘联调
powershell -ExecutionPolicy Bypass -File tools/start-quanthub.ps1 -SkipSync -Demo

# 停止全部本地服务
powershell -ExecutionPolicy Bypass -File tools/stop-quanthub.ps1
```

首次启动或依赖变化时去掉 `-SkipSync`。切换 Runner 模式前先停止旧进程。完整说明见
[项目快速开始](../README.md#2-windows-一键启动推荐) 与
[OKX Runner 运维](okx_runner/OPERATIONS.md)。

启动后至少确认：

- `/health` 返回当前版本、构建标识和 `live_trading=false`。
- `/config/status` 只返回配置状态和环境变量名称，不返回凭据。
- `/market-data/status` 没有阻塞目标流程的数据源错误。
- Web、API 和 Runner 使用同一代码版本与匹配的环境配置。

## 5. 备份与恢复

升级前创建并验证 SQLite 备份：

```powershell
uv run python -m tools.backup_store backup --output backups/store-pre-upgrade.db
uv run python -m tools.backup_store verify backups/store-pre-upgrade.db
```

保留策略默认先预览：

```powershell
uv run python -m tools.backup_store prune backups --keep 14
uv run python -m tools.backup_store prune backups --keep 14 --apply
```

Web 备份接口位于 `/backups`：

- `GET /backups/status`、`GET /backups`：源库、受控目录和备份列表。
- `POST /backups`：创建事务一致备份并立即校验。
- `POST /backups/{name}/verify`：验证备份。
- `POST /backups/{name}/restore`：要求文件名确认，恢复前生成安全备份。
- `POST /backups/retention/preview`：预览候选文件。
- `POST /backups/retention/apply`：确认列表完全一致后删除。

API 只接受受控目录内的 `.db` 文件名，不接受路径穿越。恢复期间应先使用
`tools/stop-quanthub.ps1` 停止 Web、API 和 Runner，并停止 scheduler、dispatcher
等其他写入进程，避免继续写入。

## 6. 升级流程

1. 停止写入进程并记录当前代码版本、配置 schema 和数据库 revision。
2. 创建、验证升级前备份。
3. 切换代码并同步锁定依赖。
4. 执行 Alembic 升级。
5. 运行工程质量门禁。
6. 启动服务，核对 `/health`、数据源状态和关键业务流程。
7. 保留升级前备份直到观察期结束。

验证命令见 [工程质量与发布门禁](ENGINEERING_GUIDE.md)。

## 7. 回滚流程

1. 使用 `tools/stop-quanthub.ps1` 停止 Web、API 和 Runner，并停止其他写入进程。
2. 切回已验证的旧代码版本并同步对应依赖。
3. 验证升级前备份。
4. 执行：

```powershell
uv run python -m tools.backup_store restore backups/store-pre-upgrade.db --yes
```

5. 保存恢复命令输出中的 `safety_backup` 路径。
6. 启动旧版本，检查 `/health`、数据源状态和关键流程。

不要手工降低配置 schema 或数据库 revision。数据库回滚必须使用与旧代码匹配的备份。

## 8. 自动化中心

前端入口 `/automation`，后端前缀 `/automation`。

- `GET /automation/status`：任务、活动运行、失败和未确认告警汇总。
- `GET /automation/jobs`：配置与 SQLite 覆盖合并后的任务清单。
- `PATCH /automation/jobs/{name}`：保存启用状态、五字段 Cron 和操作者。
- `POST /automation/jobs/{name}/run`：立即运行；停用任务返回 409。
- `GET /automation/runs`、`GET /automation/runs/{run_id}`：运行状态和日志。
- `POST /automation/runs/{run_id}/retry`：创建带 `parent_run_id` 的新运行。
- `POST /automation/runs/{run_id}/acknowledge`：确认失败告警。
- `GET /automation/alerts`、`GET /automation/audit`：告警和审计。

运行状态只使用 `queued`、`running`、`succeeded` 和 `failed`。前端覆盖值不得改写原始调度配置文件。

## 9. 故障状态中心

前端入口 `/incidents`，后端 `GET /incidents`。当前聚合：

| 来源 | 条件 | 恢复动作 |
| --- | --- | --- |
| `analysis_task` | 分析失败或超时 | 重试分析任务 |
| `automation_run` | 自动化失败 | 重试或确认告警 |
| `ledger_sync` | 模拟成交同步失败 | 重试指定订单成交同步 |
| `data_source` | 数据源存在 `last_error` | 打开数据源状态页 |

故障记录包含来源、实体 ID、状态、发生时间、错误、上下文和动作类型。没有后端恢复动作的来源不得显示虚假重试按钮。

## 10. 扩展接口

- 新策略：使用 `tools/scaffold_strategy.py`，实现 `StrategyBase` 并注册。
- 新数据源：实现 `DataSource`，使用 `register_source(name, cls)` 注册。
- 新告警通道：扩展 `core.alert.Notifier` 并在配置中启用。
- 新回测引擎：放入 `core/backtest/`，返回统一 `BacktestResult`。

新能力优先进入主 API 的明确领域；只有 API 与 Runner 都稳定复用的协议才进入 `packages/`。

## 11. 运行检查清单

- [ ] 版本、构建标识、配置 schema 和数据库 revision 已记录。
- [ ] `live_trading=false`。
- [ ] 数据库备份已创建、验证并在受控目录内。
- [ ] 健康检查、数据源状态和调度器状态正常。
- [ ] 无长期停留在 `running` 的任务或未知订单。
- [ ] 未确认告警、同步失败和数据源错误已有负责人。
- [ ] 日志不包含密钥、令牌、账户敏感信息或原始交易所凭据。
- [ ] 回滚版本、备份和操作步骤可用。
