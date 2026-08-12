# 部署与数据库迁移

QuantHub 支持 `local`、`lan` 和 `postgresql` 三种部署模式。配置项由 `apps/api/deployment.py` 与 `apps/api/database.py` 校验，值不满足约束时 API 拒绝启动。

## 本机模式

配置模板：`configs/deployment.local.env`。

- `QUANTHUB_DEPLOYMENT_MODE=local`
- 默认监听 `127.0.0.1`。
- 默认 CORS 仅允许 `http://localhost:5173` 和 `http://127.0.0.1:5173`。
- SQLite 文件路径由 `QUANTHUB_STORE_PATH` 指定，未设置时使用 `apps/api/store.db`。
- 可通过 `QUANTHUB_AUTH_REQUIRED=1` 强制启用 Bearer token。

推荐启动命令：

```powershell
# 默认 shadow 只读 Runner
powershell -ExecutionPolicy Bypass -File tools/start-quanthub.ps1 -SkipSync

# OKX 模拟盘
powershell -ExecutionPolicy Bypass -File tools/start-quanthub.ps1 -SkipSync -Demo

# 停止全部本地服务
powershell -ExecutionPolicy Bypass -File tools/stop-quanthub.ps1
```

首次启动或依赖变化时去掉 `-SkipSync`。Runner 默认监听 `127.0.0.1:8103`，浏览器
只访问 Web `5173`，并经统一 API `8001` 转发交易请求。

## 局域网模式

配置模板：`configs/deployment.lan.env.example`。

- `QUANTHUB_CORS_ORIGINS` 必须列出完整来源，禁止 `*`。
- `QUANTHUB_BOOTSTRAP_ADMIN_TOKEN` 至少 32 个字符。
- 所有 `/health` 之外的请求要求 Bearer token。
- 恢复、保留策略应用和备份写操作要求 `backups.manage`。

首次进入 `/governance` 时，在“Bearer token”中填写 `QUANTHUB_BOOTSTRAP_ADMIN_TOKEN`。随后创建用户与独立 API token，并撤销不再使用的 token。

## PostgreSQL 模式

配置模板：`configs/deployment.postgresql.env.example`。

- 必须设置 `QUANTHUB_DATABASE_URL`，格式使用 `postgresql+psycopg://`。
- 认证、CORS 和管理令牌约束与局域网模式相同。
- `/backups` 是 SQLite 文件备份接口，在 PostgreSQL 模式明确拒绝执行。PostgreSQL 备份应由部署环境使用 `pg_dump`、快照或托管数据库恢复点完成。

## Alembic

```powershell
$env:UV_CACHE_DIR=(Resolve-Path '.uv-cache').Path
uv run alembic upgrade head
uv run alembic current
```

`0001` 迁移接管当前 33 张业务表；后续结构变更必须新增 revision，不再通过未记录的手工 SQL 修改生产库。SQLite 迁移回归位于 `tests/test_database_migrations.py`，CI 使用 PostgreSQL 16 服务运行同一份 schema 与治理读写回归。
