# 本机多 Worktree 开发约定

## 目标

同一台 Windows 电脑可以同时运行多个 Feature Worktree，但每个 Worktree 必须作为独立本机实例管理。固定隔离端口、持久化目录、浏览器状态和进程所有权，避免分支间串数据或误停进程。所有实例直接在本机运行，不使用 Docker。

## 固定实例分配

| 实例 | Worktree | 后端端口 | Vite 端口 | 数据目录 | 桌面协调端口 |
| --- | --- | ---: | ---: | --- | ---: |
| `main` | `D:\projects\dfm-main` | 5567 | 5173 | `D:\projects\dfm-runtime\main` | 49731 |
| `analysis` | `D:\projects\dfm-wt-analysis` | 5568 | 5174 | `D:\projects\dfm-runtime\analysis` | 49732 |
| `recipe` | `D:\projects\dfm-wt-recipe` | 5569 | 5175 | `D:\projects\dfm-runtime\recipe` | 49733 |
| `automation` | `D:\projects\dfm-wt-automation` | 5570 | 5176 | `D:\projects\dfm-runtime\automation` | 49734 |

端口采用固定槽位，不在每次启动时随机选择。新增长期运行的 Worktree 时再分配下一组端口，并同步修改本表和对应 Feature 工程记录。

## 启动示例

以 Analysis Integrations 为例，先检查固定端口是否已被占用：

```powershell
Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalPort -in 5568, 5174 } |
    Select-Object LocalAddress, LocalPort, OwningProcess
```

后端终端：

```powershell
Set-Location D:\projects\dfm-wt-analysis
$env:DATA_FORMULATOR_HOME = "D:\projects\dfm-runtime\analysis"
$env:DF_DESKTOP_COORDINATION_PORT = "49732"
uv run data_formulator --dev --host 127.0.0.1 --port 5568 --sandbox local
```

前端终端：

```powershell
Set-Location D:\projects\dfm-wt-analysis
$env:API_PORT = "5568"
yarn run start --host 127.0.0.1 --port 5174 --strictPort
```

`--strictPort` 让 Vite 在端口被占用时直接失败，避免静默切换端口后连接到错误分支。后端也固定绑定 `127.0.0.1`，除非测试目标明确要求局域网访问。

Automation 分支还需要独立 Worker 终端。Web 与 Worker 必须使用同一个 automation 实例数据目录；稳定的 `DF_CODE_SIGNING_SECRET` 或 `FLASK_SECRET_KEY` 放在该 Worktree 未跟踪的 `.env` 中，让两个入口加载同一值：

```powershell
Set-Location D:\projects\dfm-wt-automation
$env:DATA_FORMULATOR_HOME = "D:\projects\dfm-runtime\automation"
$env:AUTOMATION_ENABLED = "true"
$env:WORKSPACE_BACKEND = "local"
uv run data_formulator_worker --worker-id "automation-worker-1"
```

Worker 不监听端口。`Ctrl+C` / SIGTERM 会在当前同步周期后正常停止；只检查一个周期时使用 `uv run data_formulator_worker --once --worker-id "automation-worker-probe"`。不要同时启动两个使用相同 `worker-id` 的进程，也不要让其他 Worktree 指向 automation 数据目录。

## 必须隔离的资源

| 资源 | 约定 | 原因 |
| --- | --- | --- |
| 后端和 Vite 端口 | 使用实例表中的固定端口 | 防止监听冲突和前端代理串线 |
| `DATA_FORMULATOR_HOME` | 每个实例使用独立绝对目录，并在进程启动前设置 | 其中包含 Workspace、Session、日志、凭据库、Vault 密钥等可写状态 |
| `.env` 和 Flask 密钥 | 每个 Worktree 使用自己的未跟踪 `.env` 和稳定的 `FLASK_SECRET_KEY` | 防止配置串用和重启后 Session、代码签名失效 |
| Python 与前端依赖 | 每个 Worktree 使用自己的 `.venv` 和 `node_modules` | 防止 editable install 或分支依赖版本互相覆盖；下载缓存可以共享 |
| SQLite、artifact 和任务状态 | 不同实例使用不同数据根目录；同一实例的 Web 与 Worker 使用相同绝对路径 | 防止跨分支抢锁、误消费任务或污染运行记录 |
| PID 和临时写目录 | 必须带实例名，只停止本实例明确拥有的进程 | 防止误杀其他分支或用户进程 |
| 桌面协调端口 | 仅在并行测试桌面应用时设置表中的 `DF_DESKTOP_COORDINATION_PORT` | 默认固定端口 49731 不能被多个桌面实例同时监听 |

当前后端在模块导入阶段就依据 `DATA_FORMULATOR_HOME` 创建 Session 目录，早于 `--data-dir` 的完整应用，因此并行开发必须预先设置环境变量，不能只传 CLI 参数。参见 [`app.py`](../../py-src/data_formulator/app.py)。

## 浏览器与认证状态

- `localStorage` 和 IndexedDB 按 Origin 隔离，不同 Vite 端口天然分开。
- Cookie 不按端口隔离。当前 Flask Session Cookie 使用同一默认名称，多个 `localhost` 端口可能互相覆盖。
- 在代码支持按实例设置 Cookie 名之前，每个并行实例使用独立浏览器 Profile；仅开多个标签页或普通窗口不构成隔离。
- OIDC、GitHub 或 Kusto OAuth 测试必须使用当前实例对应的 callback URL；需要并行验证时，为各实例分别登记允许的回调地址。
- 后续只增加一个轻量 `DF_INSTANCE_ID` 配置，用它派生 Session Cookie、Worker 和任务命名空间；不引入额外进程管理框架。

## 外部服务与测试

- TrustGraph、数据库和其他共享外部服务优先只读；需要写入时使用 `analysis_`、`recipe_`、`automation_` 等实例前缀隔离 workspace、schema、collection 或测试数据。
- 缺少外部服务时使用测试替身，不启动容器。
- 单元测试使用临时目录；需要监听端口的自动化测试优先让操作系统分配空闲端口，不复用开发服务器固定端口。
- 并行运行集成测试前先确认外部资源具有独立命名空间，否则串行执行。

## 进程管理

1. 启动前检查固定端口；被占用时先确认 `OwningProcess`，不自动换端口。
2. 开发服务器由各自终端管理，优先用 `Ctrl+C` 正常停止。
3. 不根据端口盲目执行 `Stop-Process` 或 `taskkill`。
4. 将来如果增加启动脚本，只保留一个轻量 PowerShell 入口，负责实例映射、端口预检、环境变量和本实例 PID；不在正式 `data_formulator_worker` 之外再建立常驻进程管理服务。
