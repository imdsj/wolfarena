# WolfArena

WolfArena（狼域）是第九届传智杯 AI Web 网页开发挑战赛 B 组项目，目标是把九人狼人杀、可解释的 AI Agent 行为和可复现的策略训练放在同一个 Web 平台中。

当前仓库已完成服务端九人局规则引擎、最小 FastAPI 房间入口和按玩家视角过滤的 WebSocket 通道。规则引擎可从首夜推进到天亮、发言、自爆、投票、放逐、夜间或白天猎人开枪和最终胜负。浏览器房间页面、完整动作接口、真实计时器、DeepSeek、RAG 和训练场仍在后续阶段实现。

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

## 技术方向

| 部分 | 计划技术 |
| --- | --- |
| 前端 | Vue 3、TypeScript、Vite（未实现） |
| 后端 | Python、FastAPI、WebSocket（最小事件通道已实现） |
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

## 启动 Web API

在项目根目录打开 PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn backend.api:app --reload
```

服务启动后访问：

- 健康检查：`GET http://127.0.0.1:8000/health`
- 接口文档：`http://127.0.0.1:8000/docs`
- 创建房间：`POST /api/rooms`
- 加入房间：`POST /api/rooms/{room_id}/join`
- 读取当前玩家视角：`GET /api/rooms/{room_id}`
- WebSocket：`/ws/rooms/{room_id}`

读取房间时必须把创建或加入时返回的 `player_token` 放入
`X-Player-Token` 请求头。房间数据当前保存在进程内存中，服务重启后清空。

WebSocket URL 只包含房间号。连接后的第一条消息必须完成认证：

```json
{"type":"authenticate","token":"玩家凭证"}
```

观战者使用创建房间时返回的 `spectator_password`：

```json
{"type":"authenticate","spectator_password":"本局观战密码"}
```

认证成功后依次收到 `authenticated`、`snapshot` 和 `phase`。当前只实现了
`start_night` 动作：

```json
{"type":"action","action":"start_night"}
```

状态变化会发送经过 `get_visible_events` 过滤的 `event`，随后发送新的
`phase`。Token 和观战密码不得放入 URL 查询参数或公开日志。

## 运行测试

在项目根目录运行：

```powershell
python -m unittest discover -s tests -v
```

当前基线应显示 **136 个测试**全部通过，并输出 `OK`。

## 当前未完成

- 除 `start_night` 外的完整游戏动作接口和中文错误码文案。
- Vue 前端、移动端页面和真实倒计时。
- DeepSeek、RAG 与 Function Calling 集成。
- 训练场、策略版本切换、200局批量模拟和指标导出。
- 在线部署和公网联调。

完整白天与夜间引擎说明分别位于 `docs/10_day_engine.md` 和 `docs/08_night_engine.md`。

## 规则与数据安全

完整九人局规则位于 `docs/01_game_rules_v1.md`。

真实 API Key 只能写入本地 `.env`，不得写入源码、文档、截图或 Git 历史。`.env.example` 只允许保存变量名。发布前应再次运行 `git status` 和密钥扫描。

## 重要声明

旧终端项目只作为规则、提示词和技术思路参考。本仓库的 Web 实现、数据结构、测试和后续训练代码由团队重新实现，并通过真实 Git 提交记录开发过程。
