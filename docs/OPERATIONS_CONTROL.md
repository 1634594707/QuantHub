# 运营控制台维护说明

本文档记录当前源码已经接通的运营板块：系统配置、自动化中心、数据库备份和故障状态中心。接口字段以对应路由和 Pydantic 模型为准。

系统配置页通过 `GET /config/status` 汇总运行模式、实盘二次确认、模型密钥状态、通知通道状态、调度器状态和备份状态。响应只返回配置状态和环境变量名称，不返回密钥或通知凭据。

## 自动化中心

前端入口为 `/automation`，后端前缀为 `/automation`。

- `GET /automation/status`：返回任务总数、启用数、活动运行数、失败数和未确认告警数。
- `GET /automation/jobs`：返回配置文件任务与 SQLite 覆盖值合并后的任务清单。
- `PATCH /automation/jobs/{name}`：保存 `enabled`、`cron` 和 `actor`。Cron 必须是五字段表达式，并会计算下次执行时间。
- `POST /automation/jobs/{name}/run`：提交立即运行；停用任务返回 409。
- `GET /automation/runs`、`GET /automation/runs/{run_id}`：读取持久化运行状态和日志。
- `POST /automation/runs/{run_id}/retry`：失败运行生成新的运行编号，并保存 `parent_run_id`。
- `POST /automation/runs/{run_id}/acknowledge`：确认失败告警。
- `GET /automation/alerts`、`GET /automation/audit`：读取未确认告警和审计记录。

任务执行在 API 进程的持久化运行表中记录 `queued`、`running`、`succeeded` 或 `failed`。调度配置文件本身不会被前端覆盖。

## 数据库备份

前端入口为 `/config` 的“数据库备份”区块，后端前缀为 `/backups`。备份目录由 `QUANTHUB_BACKUP_DIR` 明确指定；未设置时使用当前业务数据库所在目录下的 `backups` 子目录。

- `GET /backups/status`、`GET /backups`：显示源数据库、受控目录和备份文件的精确路径。
- `POST /backups`：创建事务一致的 SQLite 备份并立即完整性校验。
- `POST /backups/{name}/verify`：验证指定文件。
- `POST /backups/{name}/restore`：必须提交与文件名完全一致的 `confirm_name`；恢复前会在受控目录生成 `store-pre-restore-*.db` 安全备份。
- `POST /backups/retention/preview`：只预览待删除文件。
- `POST /backups/retention/apply`：只有 `confirm_files` 与预览结果完全一致时才删除，并返回删除结果。

API 只接受受控目录内的 `.db` 文件名，不接受目录穿越路径。底层实现复用 `tools/backup_store.py` 的一致性校验和原子替换逻辑。

## 故障状态中心

前端入口为 `/incidents`，后端为 `GET /incidents`。聚合来源和动作如下：

- `analysis_task`：分析任务 `failed` 或 `timeout`，动作是重试分析任务。
- `automation_run`：自动化失败运行，动作是重试或确认告警。
- `ledger_sync`：模拟成交到账本同步失败，动作是重试指定订单和成交。
- `data_source`：数据源遥测存在 `last_error`，动作是打开数据源状态页。

每条异常都包含来源、实体编号、状态、发生时间、错误信息、上下文和动作类型。没有后端动作的来源不会伪造重试按钮。

## 验收

```powershell
uv run python -m compileall -q apps/api apps/dispatcher apps/scheduler core strategies
uv run python -c "from apps.api.main import app; assert app.title"
Set-Location web
npm.cmd run typecheck
npm.cmd run build
```
