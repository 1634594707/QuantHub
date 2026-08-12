# QuantHub OKX Runner 运维

OKX Runner 是无界面的本地执行服务。浏览器不直接访问 Runner，所有 Web 请求都通过
统一 API 的 `/trading/*` 转发。

## 推荐启动与停止

从仓库根目录使用统一脚本，确保 Web、API 与 Runner 使用一致的环境和认证配置：

```powershell
# 默认 shadow 只读模式
powershell -ExecutionPolicy Bypass -File tools/start-quanthub.ps1 -SkipSync

# OKX 模拟盘模式
powershell -ExecutionPolicy Bypass -File tools/start-quanthub.ps1 -SkipSync -Demo

# 停止 Web、API 和 Runner
powershell -ExecutionPolicy Bypass -File tools/stop-quanthub.ps1
```

切换 `shadow`、`demo` 或 `-SkipRunner` 前必须先停止旧进程。启动器会复用已监听端口
的 QuantHub 进程，不会修改旧进程的环境。

仅调试 Runner 时可手动启动只读模式：

```powershell
uv run uvicorn apps.okx_runner.main:app --host 127.0.0.1 --port 8103
```

## 健康与日志

- Runner 健康检查：`http://127.0.0.1:8103/health`
- 统一 API 健康检查：`http://127.0.0.1:8001/health`
- 启动日志：`logs/launcher/runner.out.log` 与 `logs/launcher/runner.err.log`
- 进程记录：`logs/launcher/processes.json`

## 环境与凭据

- `shadow`、`demo` 和 `live` 使用独立数据库、日志和凭据范围。
- Demo 凭据应通过“系统设置 -> OKX 连接”保存到本地凭据仓库，或由部署密钥存储
  注入；不得写入 env 文件、数据库、策略包、请求或日志。
- 非本机绑定或非 shadow 模式必须配置 `QH_RUNNER_AUTH_TOKEN`，并与统一 API 一致。
- live 还需要独立安全审批和 `QH_RUNNER_LIVE_APPROVED=1`；仓库默认不启用实盘。

## 恢复与对账

启动后先查询所有未完成客户端订单，再允许新工作，并对订单、成交、余额和持仓进行
对账。结果不确定时切换为 `cancel_only` 或 `halted`；未知订单必须先查询外部状态，
禁止直接重新提交。

升级前备份并验证 Runner 数据库。只有全部写入进程停止后才能恢复；恢复后先执行
未完成订单恢复和完整对账，再回到正常模式。Demo 故障证据见
`docs/okx_runner/DEMO_SAFETY_EVIDENCE.md`。
