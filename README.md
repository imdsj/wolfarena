# WolfArena

WolfArena（狼域）是第九届传智杯 AI Web 网页开发挑战赛 B 组项目，目标是把九人狼人杀、可解释的 AI Agent 行为和可复现的策略训练放在同一个 Web 平台中。

新 AI 或团队成员接手时，先阅读
`docs/14_AI完整交接说明书_2026-10-25.md`。

需要按原有附件说明继续交接时，直接使用：
`docs/handoff/2026-10-25/00_开始新对话请复制这段.md`。

当前仓库已完成服务端九人局规则引擎、FastAPI 房间入口、按玩家视角过滤的 WebSocket、受控 DeepSeek 候选适配器、统一动作路由、Vue 动态动作面板、AI 自动回合、服务端截止时间计时器、浏览器倒计时、观战密码入口、刷新恢复、死亡玩家视角和赛后身份揭示。页面可以创建或加入房间，按服务器返回的合法动作参与昼夜流程，AI 会自动行动到下一次真人决策。L0 全 AI 对局模拟器和结构化日志已经接入，RAG 和训练版策略仍待后续实现。

## 当前完成内容

- 九人局第一版规则，使用稳定规则编号供代码和测试引用。
- 可复现的九人游戏创建与角色分配。
- `Player`、`GameState`、`Event` 和 `NightResult` 基础数据结构。
- 从 `INIT` 进入首夜的最小阶段切换。
- 规则要求的 15 个细分阶段和稳定事件类型。
- 普通玩家、狼人和观战者的事件可见性过滤。
- 狼队长选择、两轮狼人发言、狼刀、预言家查验和女巫用药。
- 夜间死亡合并、死因保护、基础猎人开枪资格和胜负检查。
- 可审计决策记录、策略记录、四阶段成长模型和无外部模型调用的 L0 策略。
- 白天死亡公告、遗言、座次发言、自爆、投票、放逐和猎人开枪。
- 投票截止锁票、最终票型公开和放逐遗言独立推进。
- 被放逐猎人遗言、开枪、被带走者遗言及最终胜负结算。
- 自爆窗口和遗言/公开发言30秒规则的确定性服务端入口。
- 基于存活狼人和好人数量判断最小胜负结果。
- 自动化测试覆盖角色数量、真人/AI 标记、可复现随机分配、事件记录和阶段切换。
- FastAPI 健康检查、内存房间创建、加入、玩家凭证和身份过滤。
- WebSocket 首消息认证、玩家/观战者身份确认、阶段事件和重连。
- 每局独立观战密码，以及普通玩家、存活狼人、死亡玩家和观战者的不同事件流。
- 同一房间的状态变更使用房间级锁串行执行。
- DeepSeek JSON 候选、Pydantic 校验、一次格式修复和无 Key/超时兜底。
- 非法 AI 动作或目标不会进入规则引擎，并记录拒绝原因。
- Vue 3 最小大厅、房间状态、WebSocket 生命周期和服务器事件列表。
- 严格 `ActionRequest`、统一 `execute_room_action` 入口和引擎失败回滚。
- 按阶段、角色、座次和存活状态生成 `available_actions` 与合法目标。
- Vue 根据服务器动作目录动态渲染目标、选项、文本和提交按钮。
- `AIController` 复用房间级 L0 策略，自动执行 AI 角色动作和无人工选择的系统结算。
- AI 每轮最多推进 300 步，动作失败会回滚核心状态并记录 `AI_ACTION_FAILED`。
- 相同 seed 和相同动作序列产生相同 AI 事件序列。
- 浏览器不再用 `Date.now()` 生成房间 seed；实时房由服务端生成，固定 seed 仅由脚本或训练入口显式传入。
- 后台 `RoomTimerService` 每 0.1 秒扫描遗言、发言和自爆截止时间，并立即广播变化。
- 房间快照公开服务端时间、活动截止时间、截止类型和剩余毫秒；Vue 只做本地递减显示，归零后等待服务端推进。
- 大厅支持观战密码入口，观战者通过 WebSocket 认证并使用只读上帝视角。
- 玩家会话和观战会话保存在浏览器本地，刷新后重新认证并恢复到当前阶段。
- 九人席位按服务端可见事件显示身份；死亡玩家不会被自动转换为观战者。
- 动作表单只提供存活目标，文本动作使用输入框，服务器拒绝原因显示在页面中。
- 赛后面板显示胜方、九名玩家身份和当前视角可见的死因。
- 解药未消耗时，女巫快照返回当夜准确刀口；空刀显示为没有刀口，解药耗尽后不再返回。
- `backend.simulator` 可运行固定 seed 的 AI-only 对局，输出每局与每动作 JSONL。

## 技术方向

| 部分 | 计划技术 |
| --- | --- |
| 前端 | Vue 3、TypeScript、Vite（最小入口已实现） |
| 后端 | Python、FastAPI、WebSocket、DeepSeek 适配器 |
| 数据 | SQLite |
| 模型 | DeepSeek OpenAI 兼容接口 |
| 策略训练 | 共享表格型 Q-learning |

## 目录

```text
wolfarena/
  backend/            游戏引擎、FastAPI 路由和内存房间
  frontend/           Vue 前端
  docs/               规则、决策与比赛材料记录
  training_runs/      本地训练输出，不直接提交原始结果
  tests/              自动化测试
  .env.example        环境变量名称模板
  .gitignore          敏感文件与生成文件忽略规则
  README.md           项目说明
```

## 启动完整页面

先构建前端：

```powershell
Set-Location frontend
npm install
npm run build
Set-Location ..
```

构建完成后，FastAPI 会直接托管 `frontend/dist`。再启动服务：

在项目根目录打开 PowerShell：

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn backend.api:app --host 127.0.0.1 --port 8000
```

服务启动后访问：

- 页面入口：`http://127.0.0.1:8000/`
- 健康检查：`GET http://127.0.0.1:8000/health`
- 接口文档：`http://127.0.0.1:8000/docs`
- 创建房间：`POST /api/rooms`
- 加入房间：`POST /api/rooms/{room_id}/join`
- 读取当前玩家视角：`GET /api/rooms/{room_id}`
- 执行游戏动作：`POST /api/rooms/{room_id}/actions`
- WebSocket：`/ws/rooms/{room_id}`

读取房间时必须把创建或加入时返回的 `player_token` 放入
`X-Player-Token` 请求头。房间数据当前保存在进程内存中，服务重启后清空。

房间号区分大小写。页面会原样显示混合大小写的房间号，并提供“复制房间号”
按钮；不要手动转成全大写或全小写。

WebSocket URL 只包含房间号。连接后的第一条消息必须完成认证：

```json
{"type":"authenticate","token":"玩家凭证"}
```

观战者使用创建房间时返回的 `spectator_password`：

```json
{"type":"authenticate","spectator_password":"本局观战密码"}
```

认证成功后依次收到 `authenticated`、`snapshot` 和 `phase`。`snapshot.room`
中的 `available_actions` 是当前凭证可以执行的动作和合法目标。动作通过统一
入口执行，例如：

```json
{"type":"action","action":"vote","target_id":"p2","content":null,"choice":null}
```

状态变化会发送经过 `get_visible_events` 过滤的 `event`，随后发送新的
`phase` 和最新 `snapshot`。Token 和观战密码不得放入 URL 查询参数或公开日志。

开发模式下也可以进入 `frontend` 执行 `npm run dev`，Vite 会把 API 和
WebSocket 代理到 `127.0.0.1:8000`。

## DeepSeek 配置与兜底

复制 `.env.example` 为 `.env`，在本机填写：

```text
DEEPSEEK_API_KEY=你的私有密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_TIMEOUT_SECONDS=8
```

`.env` 已被 Git 忽略。模型没有配置或调用失败时，服务器会使用本地
`start_night` 兜底并记录 `AI_FALLBACK_USED`。页面请求：

```text
POST /api/rooms/{room_id}/ai-action
X-Player-Token: 玩家凭证
```

模型只生成候选，服务端验证合法动作和合法目标后才调用规则引擎。日志不会
打印请求头、Token 或 API Key。

## 运行测试

在项目根目录运行：

```powershell
python -m unittest discover -s tests -v
```

当前基线应显示 **189 个测试**全部通过，并输出 `OK`。

服务运行时，可执行前端 DOM 冒烟测试：

```powershell
Set-Location frontend
npm run smoke:client
npm run smoke:sync
npm run smoke:viewer
npm run smoke:acceptance
```

`smoke:acceptance` 会驱动一名真人从 `INIT` 到 `END`，验证刷新恢复、错误
观战密码、只读观战和 390×844 DOM 状态，并把可重新打开的状态快照写到
`docs/evidence/browser-2026-10-26/`。

## L0 全 AI 模拟器

```powershell
python -m backend.simulator `
  --games 10 `
  --seed-start 1000 `
  --policy l0 `
  --out training_runs/smoke-l0
```

输出：

```text
run.json        批次配置、耗时和完成/失败统计
games.jsonl     每局 seed、角色、胜者、结束阶段和错误
actions.jsonl   每步阶段、行动者、合法动作、选择、目标、文本和真实结果
```

模拟器复用现有 `create_game`、`AIController`、`available_actions_for_state` 和
`execute_engine_action`，不复制规则。每局同时受最大动作步数和最大天数限制；
无合法动作、动作异常或状态未推进都会终止当前局并写入错误。

## 当前未完成

- RAG 与 Function Calling 的完整策略闭环。
- 训练版策略、策略版本切换和指标面板。
- 对局日志的可视化指标页面；当前 JSONL 已可供后续脚本复算。
- 在线部署和公网联调。
- 真实 Chrome 双窗口录屏和 390px 最终截图仍需在允许启动浏览器进程的桌面环境
  复核；`happy-dom` 不能替代真实布局。

完整白天与夜间引擎说明分别位于 `docs/10_day_engine.md` 和 `docs/08_night_engine.md`。

## 规则与数据安全

完整九人局规则位于 `docs/01_game_rules_v1.md`。

真实 API Key 只能写入本地 `.env`，不得写入源码、文档、截图或 Git 历史。`.env.example` 只允许保存变量名。发布前应再次运行 `git status` 和密钥扫描。

## 重要声明

旧终端项目只作为规则、提示词和技术思路参考。本仓库的 Web 实现、数据结构、测试和后续训练代码由团队重新实现，并通过真实 Git 提交记录开发过程。
