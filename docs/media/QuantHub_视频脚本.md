# QuantHub 开源项目介绍视频脚本

> 面向：B 站 / YouTube / 抖音技术号（可横屏 16:9 主发，竖屏裁剪发短视频）
> 建议时长：3 分 30 秒（主线版）
> 风格：屏幕录制 + 少量口播，开发者第一人称，诚实、不吹、讲边界
> 核心叙事：**市面上量化工具两极分化（回测玩具 / 实盘无防护），QuantHub 把"研究 → 验证 → 审核 → 模拟 → 账本"做成一条本地优先、默认安全、可复验的闭环。**

---

## 一、先想清楚"怎么讲"（叙事策略）

不要按功能清单念，按"痛点 → 解法 → 证明 → 上手"讲。三条记忆锚点：

1. **一个入口管四个市场**（A 股 / 美股 / 加密 OKX / MT5）——解决"工具割裂"。
2. **因子要过 7 天真实观察门禁，且不用占位曲线冒充结果**——解决"回测玩具"。
3. **默认只读影子模式、实盘开关默认关、凭据本地加密、无假数据**——解决"实盘无防护"。

结尾必须带一句免责声明（项目定位就是研究/模拟工具），这反而加分——显得诚实。

---

## 二、主线分镜脚本（3 分 30 秒）

| # | 时间 | 画面（B-roll 来源） | 配音稿 | 屏幕字幕 / 字卡 |
|---|------|----------------------|--------|------------------|
| 1 | 0:00–0:18 | 黑底 + 打字机效果出现项目名 `QuantHub`；背景快速闪过几张 K 线/账本截图 | 「做量化的人，大多卡在两头：要么用回测玩具，曲线漂亮，一上实盘就崩；要么直接连交易所，亏了都不知道为什么。工具还特别碎——行情一个软件、回测一个软件、下单又一个。」 | 量化人的两个死穴：回测玩具 / 实盘无防护 |
| 2 | 0:18–0:45 | 展示 `design/screenshots/quanthub-overview.png`（总览工作台），鼠标划过顶部导航 | 「我做了个东西叫 QuantHub——本地优先的多市场量化研究和模拟交易工作台。A 股、美股、加密资产 OKX、还有 MT5，全在一个网页入口里搞定。」 | 本地优先 · 多市场 · 一个入口 |
| 3 | 0:45–1:25 | 切到 `design/screenshots/quanthub-factor-research.png`，放大"候选列表 / DSL / 门禁结果"区域 | 「它的核心叫 Factor Factory。你提一个因子假设，它先做安全 DSL 白名单检查——不让你写未来函数；再去重、做相似性预检；然后用滚动样本外验证、回撤和交易次数门禁，外加双倍成本压力测试，筛出唯一优胜者。」 | Factor Factory：候选生成 → 安全 DSL → 样本外验证 |
| 4 | 1:25–1:55 | 同页向下滚，展示"7 天真实观察"区块；可叠加一张小字卡强调 | 「重点在这儿：优胜因子进 OKX 模拟或本地模拟后，必须累计至少 7 个真实自然日，过了收益、夏普、成交率、容量这些门禁才算数。而且只有真实数据够多才画曲线——它**不用占位曲线冒充结果**。这才是和玩具回测最大的区别。」 | 7 天真实观察门禁 · 拒绝占位曲线 |
| 5 | 1:55–2:20 | 切 `design/baselines/2026-07-27/research-1440x900.png`，圈出"新闻 AI / 价格结构 AI / 模型共识" | 「研究里可以接 AI，但定位很克制：AI 只负责提假设和表达式，**不改统计结论**；输出还要过两阶段质量闸门，没通过就不许发布信号。」 | AI 提假设，不替你下结论 · 质量闸门 |
| 6 | 2:20–2:45 | 连续切三张：`signals-1440x900.png` → `strategy-lab-1440x900.png` → `ledger-1440x900.png` | 「信号先进审核中心，再进模拟订单和账户账本。账本用 FIFO 配对算真实胜率、利润因子、盈亏比——一笔一笔都能追。」 | 信号 → 审核 → 模拟 → 账本（可追可查） |
| 7 | 2:45–3:05 | 切 `docs/Plan/evidence/M4-01-okx-settings/desktop-1440x900.png`，再切 `F9-.../desktop-1440x900-okx-live-kline.png` | 「安全是默认值，不是开关。Runner 默认 shadow 只读、不下单；OKX 凭据用系统加密存在仓库外面，界面不回显明文；实盘必须你手动开、还要单独批准。连真实行情也是只读 Demo 验证过的。」 | 默认只读 · 凭据本地加密 · 实盘需手动批准 |
| 8 | 3:05–3:25 | 终端录屏：跑 `powershell -ExecutionPolicy Bypass -File tools/start-quanthub.ps1`；或 Docker 一行命令 | 「技术上 React 加 FastAPI，uv workspace 管理，策略插件化。Windows 一条 PowerShell 就起三个进程；不想装环境就直接 Docker 跑镜像。」 | 一条命令启动 · 或 Docker |
| 9 | 3:25–3:35 | 回到项目总览图，淡出，留 GitHub 地址 + Star 动效 | 「它是 AGPL 开源的。研究、模拟、别拿去当实盘建议——但欢迎来 Star、提 Issue，一起把可信量化这件事做扎实。」 | github.com/1634594707/QuantHub · Star & 一起建 |

---

## 三、可直接复用的配音全文（连续版，方便提词器）

> 做量化的人，大多卡在两头：要么用回测玩具，曲线漂亮，一上实盘就崩；要么直接连交易所，亏了都不知道为什么。工具还特别碎——行情一个软件、回测一个软件、下单又一个。
>
> 我做了个东西叫 QuantHub——本地优先的多市场量化研究和模拟交易工作台。A 股、美股、加密资产 OKX、还有 MT5，全在一个网页入口里搞定。
>
> 它的核心叫 Factor Factory。你提一个因子假设，它先做安全 DSL 白名单检查——不让你写未来函数；再去重、做相似性预检；然后用滚动样本外验证、回撤和交易次数门禁，外加双倍成本压力测试，筛出唯一优胜者。
>
> 重点在这儿：优胜因子进 OKX 模拟或本地模拟后，必须累计至少 7 个真实自然日，过了收益、夏普、成交率、容量这些门禁才算数。而且只有真实数据够多才画曲线——它不用占位曲线冒充结果。这才是和玩具回测最大的区别。
>
> 研究里可以接 AI，但定位很克制：AI 只负责提假设和表达式，不改统计结论；输出还要过两阶段质量闸门，没通过就不许发布信号。
>
> 信号先进审核中心，再进模拟订单和账户账本。账本用 FIFO 配对算真实胜率、利润因子、盈亏比——一笔一笔都能追。
>
> 安全是默认值，不是开关。Runner 默认 shadow 只读、不下单；OKX 凭据用系统加密存在仓库外面，界面不回显明文；实盘必须你手动开、还要单独批准。连真实行情也是只读 Demo 验证过的。
>
> 技术上 React 加 FastAPI，uv workspace 管理，策略插件化。Windows 一条 PowerShell 就起三个进程；不想装环境就直接 Docker 跑镜像。
>
> 它是 AGPL 开源的。研究、模拟、别拿去当实盘建议——但欢迎来 Star、提 Issue，一起把可信量化这件事做扎实。

---

## 四、B-roll 素材清单（项目内真实截图，可直接用）

| 用途 | 文件绝对路径 |
|------|--------------|
| 总览工作台 | `D:\Administrator\Desktop\finance\design\screenshots\quanthub-overview.png` |
| 因子研究（README 同款） | `D:\Administrator\Desktop\finance\design\screenshots\quanthub-factor-research.png` |
| 研究页（含 AI 模块） | `D:\Administrator\Desktop\finance\design\baselines\2026-07-27\research-1440x900.png` |
| 信号 / 审核 | `D:\Administrator\Desktop\finance\design\baselines\2026-07-27\signals-1440x900.png` |
| 策略实验室 | `D:\Administrator\Desktop\finance\design\baselines\2026-07-27\strategy-lab-1440x900.png` |
| 账户账本 | `D:\Administrator\Desktop\finance\design\baselines\2026-07-27\ledger-1440x900.png` |
| 模拟交易 | `D:\Administrator\Desktop\finance\design\baselines\2026-07-27\simulation-1440x900.png` |
| OKX 连接设置 | `D:\Administrator\Desktop\finance\docs\Plan\evidence\M4-01-okx-settings\desktop-1440x900.png` |
| OKX 实时 K 线（只读验证） | `D:\Administrator\Desktop\finance\docs\Plan\evidence\F9-okx-catalog-live-kline-web-2026-08-11\desktop-1440x900-okx-live-kline.png` |
| 移动端验收（如需竖屏） | `D:\Administrator\Desktop\finance\design\baselines\2026-07-27\*-390x844.png` 系列 |

> 提示：录屏比用静态图更可信。建议场景 2–7 尽量用「真实运行界面录屏 + 鼠标圈选」，只在转场用上面的截图。

---

## 五、两种变体

### A. 60 秒短视频版（抖音 / YouTube Shorts / B 站竖屏）
保留锚点 1+2+3，砍掉细节：
- 0:00–0:10 痛点一句话 + 项目名
- 0:10–0:25 总览图：四个市场一个入口
- 0:25–0:45 Factor Factory + 7 天门禁 + "不用占位曲线"（最强差异点，必须留）
- 0:45–0:55 默认安全 + GitHub 地址 + Star

### B. 8 分钟深度版（适合"项目巡览 / 架构讲解"）
在主线基础上补：
- 架构图（`../ARCHITECTURE.md` 里有）→ 讲 `apps/api` 网关、`dispatcher` 风控路由、`okx_runner` 无界面执行三进程模型
- Factor Factory 完整链路演示：从手动 JSON 批次 → AI 提案 → 表达式检查器 → 相似性预检（0.985 相关性阈值）→ 锁定确认集
- AI 因子发现路线图（`../../AI_FACTOR_DISCOVERY_ROADMAP.md`）讲未来截面数据层
- 实盘适配评估边界（`../LIVE_TRADING_ADAPTER_EVALUATION.md`）——诚实讲"现在不能干什么"
- 一键启动脚本拆解 + 可选 extra（`a_shares` / `crypto` / `ai` / `backtest`）

---

## 六、拍摄 / 剪辑提醒

- **节奏**：每屏停留 4–7 秒，配轻量 BGM（音量压到 15% 以下，别盖过人声）。
- **字幕**：中文硬字幕必加（技术视频完播率靠它）；关键数字（7 天、0.985、AGPL）单独做字卡高亮。
- **免责声明**：片尾那句"研究、模拟、不构成投资建议"建议做成常驻 3 秒字卡，合规也显专业。
- **封面标题**：建议「我把量化工具做成了'默认不亏钱'的样子」或「一个本地优先、拒绝玩具回测的量化工作台」。
- **GitHub 链接**：口播念全 `github.com/1634594707/QuantHub`，画面同时放大二维码/链接便于截图。
