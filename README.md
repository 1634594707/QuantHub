# QuantHub

> 分层单体仓库，整合 A股研究 + 加密交易 + AI 分析。统一底座 + 插件式策略 + Streamlit 看板。

## 架构

```
应用层 apps/
 ├─ dashboard   Streamlit 统一看板（无鉴权，本地使用）
 ├─ dispatcher  信号中枢：汇聚 → 风控 → 下单路由（默认 dry-run，实盘 CLI 二次确认）
 ├─ scheduler   APScheduler 定时任务
 └─ api        统一 API 网关（单端口 front 全部策略，看板/企微/调度器共用）

策略层 strategies/（插件式挂载）
 ├─ a_shares/   sentiment · news_scanner · selector · supertrend · morning_brief · perks_monitor · realtime_analyzer
 ├─ crypto/     okx_grid · alphagpt
 ├─ mt5/        alphamaster
 └─ ai_analysis/ pa_agent

统一底座 core/
 ├─ data_feed  多源行情/公告（akshare/东财/OKX-ccxt）+ SQLite 缓存 + 退避重试
 ├─ signals    统一 Signal 数据类 + 轻量总线
 ├─ alert      企微/Webhook/Telegram
 ├─ llm        DeepSeek/OpenAI 兼容客户端
 ├─ backtest   网格回测 + backtrader + 事件驱动框架
 └─ viz        Streamlit 组件库 + Plotly helper

configs/  base.yaml + a_shares.yaml + crypto.yaml
tests/    底座单测
```

## 安装

需要 Python 3.11（<3.13，避开 torch/solana 在 3.13 的滞后）。

```powershell
# 安装 uv（如未安装）
pip install uv

# 同步 workspace 全部依赖（含可选组）
uv sync --all-extras

# 或按需安装
uv sync --extra a_shares --extra dashboard
uv sync --extra crypto --extra heavy-solana
```

## 快速开始

```powershell
# 0. 安装依赖（含 API 网关）
uv sync --extra a_shares --extra dashboard --extra api

# 1. 运行全部测试
uv run pytest tests/ -q

# 2. 启动统一 API 网关（单端口 front 全部策略）
uv run uvicorn apps.api.main:app --host 0.0.0.0 --port 8000
#    接口：GET /health · /strategies · /strategies/{name} · /signals
#          POST /strategies/{name}/run · /signals/publish

# 3. 启动看板（默认研究模式）
uv run streamlit run apps/dashboard/app.py

# 4. 启动调度器
uv run python -m apps.scheduler.jobs

# 5. 启动信号中枢（常驻）
uv run python -m apps.dispatcher.main
```

## 配置

- `configs/base.yaml`：全局配置，**实盘总开关 `live_trading: false`（默认研究模式）**
- `configs/a_shares.yaml`：A股市场专属
- `configs/crypto.yaml`：加密市场专属（实盘模块默认关闭）

### 实盘启用

实盘需三层开关全部打开：

1. `configs/base.yaml`: `live_trading: true`
2. `configs/crypto.yaml`: `modules.okx_grid.live: true`（或对应模块）
3. 环境变量存在：`OKX_API_KEY` / `OKX_API_SECRET` / `OKX_PASSPHRASE`

下单前 dispatcher 强制 CLI 二次确认（输入 `CONFIRM`）。

### 密钥管理

密钥仅从环境变量读取，禁止写入仓库（`.gitignore` 已排除 `.env`）：

```powershell
$env:DEEPSEEK_API_KEY = "sk-..."
$env:OKX_API_KEY = "..."
$env:OKX_API_SECRET = "..."
$env:OKX_PASSPHRASE = "..."
$env:WECOM_WEBHOOK_URL = "https://qyapi.weixin.qq.com/..."
```

## 策略插件开发

实现 `strategies.base.StrategyBase` 并用 `@register_strategy` 注册：

```python
from strategies import StrategyBase, StrategyInfo, register_strategy
from core.signals import Signal

@register_strategy(StrategyInfo(name="my_strategy", market="a_shares", live_capable=False))
class MyStrategy(StrategyBase):
    def produce(self, **kwargs):
        sig = Signal(symbol="000001", market="a_shares", timeframe="daily",
                     direction="buy", score=0.8, confidence=0.7, source="my_strategy")
        self.publish(sig)
        return [sig]
```

## 版本与升级

- 仓库版本见 `pyproject.toml: version`
- 配置 schema 版本见 `configs/base.yaml: schema_version`
- 升级钩子在 `core/config.py: _migrate_schema`，逐版本向上迁移
- 详见 `docs/ARCHITECTURE.md`（架构）与 `docs/UPGRADE.md`（升级路径）

## 迁移状态

| 阶段 | 内容 | 状态 |
|---|---|---|
| Phase 0 | 脚手架（uv workspace + configs + 目录骨架） | ✅ 完成 |
| Phase 1 | core/ 底座（data_feed/signals/alert/llm/backtest/viz） | ✅ 完成 |
| Phase 2 | A股模块下沉（6 个策略） | ✅ 完成 |
| Phase 3 | 加密模块（okx_grid/alphagpt，实盘默认关） | ✅ 完成 |
| Phase 4 | AI 分析（pa_agent 两阶段 LLM） | ✅ 完成 |
| Phase 5 | 信号中枢 + 风控 + 看板联调 + 调度器 | ✅ 完成 |
| Phase 6 | MT5 市场模块（alphamaster：AlphaMaster 因子引擎零拷贝接入） | ✅ 完成 |
| Phase 7 | A股实时分析器下沉（realtime_analyzer：东财盘口+腾讯日K+指数宽度，LLM 研报降级）+ core/viz 自包含 HTML 报告生成器 | ✅ 完成 |
| Phase 8 | 统一 API 网关（apps/api：单端口 front 全部 11 策略 + 信号总线读写，替代分散的多个 FastAPI 服务） | ✅ 完成 |

**测试**：44 个测试全过（34 底座单测 + 10 集成测试）
**已注册策略**：11 个（7 A股 + 2 加密 + 1 MT5 + 1 AI分析）

## 许可证

AGPL-3.0-or-later
