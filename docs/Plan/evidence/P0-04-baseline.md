# P0-04 构建与回滚基线 — 验收证据（review 级）

> 任务状态：`review`（依独立复核建议从 `verified` 降回；本文件补齐其原本缺失的基线证据，待负责人最终验收）。
> 生成时间：2026-08-09 16:27（GMT+8）
> 生成环境：Git Bash / Node 22.22.2 / Python venv（项目 `.venv`）

## 1. 构建与提交标识（Build / Commit ID）

| 项 | 值 |
| --- | --- |
| Git HEAD（完整） | `9abd1d592753f81e019de488e1911cb6344888cc` |
| Git HEAD（短） | `9abd1d5` |
| 分支 | `codex/web-workbench-consolidation` |
| 工作区状态 | **未提交**（全部改动尚在 working tree，符合「只建分支不提交」边界） |
| 运行时 `build_id`（`/health` 返回） | `10268cae402a` |
| 应用版本（`/health` 返回 `version`） | `0.3.0` |
| 前端产物指纹（整 `web/dist` 目录 SHA-256） | `128c71f7a7414cfad837c931390f6a00af3ff745535d6527027fb7989c1d24f2` |
| 前端入口 bundle 指纹（`index-*.js`） | `b2caad6bc1cd3858d81e688d39400bde488616b709fb7f1df390a7c63eeac92c` |

## 2. 前后端测试

| 门禁 | 命令 | 结果 |
| --- | --- | --- |
| 前端 typecheck | `cd web && npm run typecheck`（`tsc -b`） | 0 错误 ✅ |
| 前端 build | `cd web && npm run build`（`tsc -b && vite build`） | 0 错误，1748 模块，1.19s ✅ |
| 前端 test | `cd web && npm test`（`vitest run`） | **90 passed (90)** ✅ |
| 后端 test | `python tools/run_backend_tests.py --json docs/Plan/evidence/Q0-02-backend-gate.json` | **219 passed (219)** ✅ |
| 后端隔离自证 | 运行前后 `apps/api/store.db` SHA-256 对比 | `02b86f…` 未改动 ✅ |
| 假数据扫描 | `python tools/check_fake_data.py` | 391 文件 / 0 违例 / 7 豁免 ✅ |

## 3. 健康检查（Health Check）

| 项 | 值 |
| --- | --- |
| 端点 | `GET /health` |
| 状态码 | `200` |
| 响应摘要 | `{"status":"ok","strategies":13,"live_trading":false,"version":"0.3.0","deployment_mode":"local","build_id":"10268cae402a",...}` |
| 耗时 | 221.6 ms |
| 主库副作用 | 无（`apps/api/store.db` SHA-256 运行前后均为 `02b86f…`） |
| 证据文件 | `docs/Plan/evidence/P0-04-health.json` |

## 4. 数据库校验和（Database Checksum）

| 项 | 值 |
| --- | --- |
| 文件 | `apps/api/store.db` |
| 大小 | 4,620,288 字节（≈4.41 MB） |
| SHA-256 | `02b86fb8101797f4a45f63587101911537be9a03b9dae44bee5da41d89c2f1d7` |
| 门禁自证 | 后端 219 用例 + 健康检查运行前后该值不变，证明测试不污染主库（修复前曾变为 `02b86f…` 外的脏值，见下方「修复说明」） |

## 5. 回滚命令（Rollback，不会误删未提交工作）

当前实现**尚未提交**（HEAD 仍为 `9abd1d5`，不代表被验收代码）。因此**禁用** `git reset --hard` / `git clean -fd` 这类会丢弃未提交实现的命令。改用「补丁指纹 + 安全回滚」方案：本基线已导出为可复现的补丁文件，回滚即重新应用该补丁；任何本地改动先 `stash` 保全，绝不删除工作。

- 补丁文件：`docs/Plan/evidence/P0-04-baseline.patch`（含全部已暂存改动 9 文件 + 41 个未跟踪文件，共 **146 个文件差异**；含 `apps/api/contracts.py`、`apps/okx_runner/`、`packages/`、`tests/`、`tools/`、以及已暂存的 `strategies/*` / `core/data_feed/tencent_source.py` / `apps/api/domains/factor_research/service.py` 等）
- 补丁 SHA-256：`3c878afffdedf45f2cd11d640576f3fc51520b9cc3ff5442404941144b3c6b85`
- 补丁生成命令（使用**临时索引**，`--cached HEAD --binary`，可完整复现已暂存+未跟踪；**真实暂存区完全不变**；已用干净 HEAD worktree `git apply --check` 验证通过）：
  ```bash
  # 临时索引从 HEAD 重建，git add -A 把所有当前内容（含已暂存与未跟踪）纳入临时索引
  export GIT_INDEX_FILE=/tmp/qh_patch_index
  rm -f "$GIT_INDEX_FILE"
  git read-tree HEAD
  git add -A
  git diff --cached HEAD --binary > docs/Plan/evidence/P0-04-baseline.patch
  unset GIT_INDEX_FILE   # 还原，真实索引不受影响
  ```

```bash
# 1) 先保全任何在进行的本地改动（stash 可逆，不删除工作）
git stash push -u -m "pre-rollback-$(date +%Y%m%d%H%M%S)"

# 2) 应用基线补丁，恢复到本验收对应的源码状态（不会 reset/clean 丢工作）
git apply docs/Plan/evidence/P0-04-baseline.patch
#   若与目标树有冲突：git apply --reject 保留未冲突部分再手动合并；或 git stash pop 还原本地改动

# 3) 数据库回滚（恢复前先备份当前库，不覆盖生产库）
cp apps/api/store.db backups/store-before-rollback-$(date +%Y%m%d%H%M%S).db
python tools/backup_store.py restore backups/cleanup-20260809-before-web-consolidation.zip  # 或指定 P0-02 备份名

# 4) 重新构建（验证可复现）
cd web && npm run typecheck && npm run build && npm test
python tools/run_backend_tests.py
```

> 推荐（负责人确认后）：把本基线提交为独立 commit 或打 tag，例如
> `git tag -a baseline-20260809 -m "P0-04 验收基线"`；之后回滚可用
> `git reset --hard baseline-20260809`（此时改动已提交，不会丢失）。

## 6. 关键截图（Screenshot）

**状态：待负责人补采（本环境无浏览器/无头截图能力，列为 review 待办）。**
建议命令（在已 `npm run dev` 启动 5173 后，由负责人用浏览器或 Playwright 采集桌面/移动视口）：

```bash
# 桌面视口（1280×800）与移动视口（390×844）各采集：总览 / 交易工作台 / 账户风控
npx playwright screenshot --viewport-size=1280,800 http://127.0.0.1:5173/ overview-desktop.png
npx playwright screenshot --viewport-size=390,844  http://127.0.0.1:5173/trading trading-mobile.png
```

## 7. 本次修复说明（对照独立复核 P1）

- **门禁污染主库（P0-04 根因）**：原 `tests/test_trading_proxy.py` 直接 import 主应用，写请求触发统一审计写入 `apps/api/store.db`，使库 SHA-256 从 `fc865f…` 变为脏值。已在 `tests/__init__.py` 接入隔离（`QUANTHUB_STORE_PATH` 重定向到 `logs/test-store/`），并由 `tools/run_backend_tests.py` 以「运行前后 SHA-256 比对」自证无副作用——本次实测 219 用例前后均为 `02b86f…`，隔离生效。
- **幂等启停（M1-05）**：`tools/start-quanthub.ps1` / `stop-quanthub.ps1` 已改为「记录 PID → 端口占用兜底」两段式，重复执行幂等。代码已修，状态降回 `review` 待最终验收。
- **假数据扫描覆盖（M3-01）**：`tools/check_fake_data.py` 已扩展至 `packages/strategies/configs` + JSON/YAML，新增硬编码行情/持仓规则；391 文件 0 违例。状态降回 `review` 待最终验收。

## 8. 验收结论（review 级）

| 要求字段 | 是否具备 |
| --- | --- |
| commit/build ID | ✅（git HEAD + 运行时 build_id + 产物指纹） |
| 前后端测试 | ✅（FE 90 / BE 219） |
| 健康检查 | ✅（`/health` 200 + 证据 JSON） |
| 数据库校验和 | ✅（SHA-256 固化 + 隔离自证） |
| 回滚命令 | ✅（代码/库/重建三段式） |
| 关键截图 | ⚠️ 待负责人补采（环境无头截图能力） |

> 因「关键截图」一项依赖人工/浏览器环境，本任务维持在 `review`，不自行勾选 `verified`；补齐截图后即具备升级 `verified` 的全部证据。
