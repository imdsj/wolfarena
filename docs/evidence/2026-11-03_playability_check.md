# 11 月 3 日可玩性验收（按最终版任务单）

日期：2026-11-03

执行人：Hurry

代码：远端 main `172080b`（本地 `9417049`，网络受限时用 API 快照核对）

公网：`http://106.14.113.216:8080`

## 一、结论先行

```text
可玩性：不通过 —— 公网环境一局都推不动
```

**公网房间在 `1/NIGHT_WOLF_DISCUSSION_R1` 停滞，100 秒零推进、事件数停在 5 条。**

本地同一份代码（`172080b`）推进正常。因此这是**部署侧问题**，不是代码问题。

任务单「三天总目标：让九人局真正能玩」，当前公网状态**达不到**。

## 二、公网卡死的实测证据

### 2.1 三次独立测试，结果一致

| 方式 | 操作 | 结果 |
| --- | --- | --- |
| HTTP 轮询 60 秒 | `start_night` 后每秒查快照 | 停在 `NIGHT_WOLF_DISCUSSION_R1`，事件 5 条 |
| WebSocket 40 秒 | 连 WS、`start_night`、收推送 | 只收到 `INIT` 与 `NIGHT_WOLF_DISCUSSION_R1` 两个阶段，再无新帧 |
| HTTP 轮询 100 秒 | 新建房，2 秒一次查询 | **100 秒后仍是 `NIGHT_WOLF_DISCUSSION_R1`** |

三次都只产生 5 条事件：

```text
ROLE_ASSIGNED ×3（狼队三人）、NIGHT_STARTED、WOLF_CAPTAIN_ELECTED
```

即：首夜开始、队长选出之后，**再没有任何推进**。

### 2.2 对照：本地同版本代码正常

本地 `172080b` + 同一 `.venv`，只点一次 `start_night`，之后完全不操作：

```text
0s    1/NIGHT_WOLF_DISCUSSION_R2
5s    1/NIGHT_WOLF_KILL
9s    1/NIGHT_SEER_CHECK
13s   1/NIGHT_WITCH_ACTION
17s   1/NIGHT_RESOLUTION
21s   1/DAY_ANNOUNCEMENT
25s   1/DAY_LAST_WORDS
55s   1/DAY_DISCUSSION
85s   1/VOTE
105s  2/NIGHT_WOLF_DISCUSSION_R1
...
150s  2/DAY_DISCUSSION
```

18 次阶段切换，全部自动完成，无人工操作。

**同一份代码，本地推进、公网停滞 → 差异在部署环境。**

### 2.3 可能原因（需订书机排查）

1. 公网进程运行的不是 `172080b`，而是缺少「真人闲置自动接管」（`91a8819`，10-30 11:57）的旧版本；
2. 或计时器服务 `RoomTimerService` 未随 lifespan 启动，或后台任务已异常退出（`_run` 内异常会被吞掉并继续，但任务本身若被取消则不再推进）；
3. 或部署进程近期重启过，未加载新代码。

**`/health` 无法区分版本**——本地与公网都返回 `version: "0.6.0"`，无法判断部署的是哪个 commit。建议增加构建信息或直接在服务器上核对。

## 三、AI 发言

### 3.1 事件层：有内容，但内容为模板

本地实测 6 条 `PUBLIC_SPEECH`，每条都有 `content`：

```text
#25 PUBLIC_SPEECH actor=p7 content=我是7号，先听后续发言。
#26 PUBLIC_SPEECH actor=p8 content=我是8号，先听后续发言。
#27 PUBLIC_SPEECH actor=p9 content=我是9号，先听后续发言。
```

**全部是同一句式。** 源码确认内容来自硬编码模板：

```python
# backend/ai_controller.py:481
content = f"我是{actor.seat}号，先听后续发言。"
```

原因：本机与公网均未配置 `DEEPSEEK_API_KEY` / `OPENAI_API_KEY`，走的是无模型兜底分支。

判定：**「AI 会发言」成立，「AI 发言有实质内容」不成立**。演示时如果全是同一句，观感很差。

### 3.2 接口层缺字段（影响气泡显示）

`PUBLIC_SPEECH` 的 `data` 只有一个键：

```json
{ "event_seq": 25, "event_type": "PUBLIC_SPEECH", "actor_id": "p7",
  "data": { "content": "我是7号，先听后续发言。" } }
```

**没有 `seat`、没有 `name`。** 任务单要求「发言气泡显示座位、名字、内容」——前端必须自己用 `actor_id` 去 `players` 列表里查座位和名字。

本身不算缺陷（信息可从 `players` 取到），但属接口不够自足，需要前端保证映射正确。**气泡是否真的显示座位与名字，必须到浏览器里逐条看**，本轮未验证（见第五节）。

## 四、其余项

| 项 | 结果 | 依据 |
| --- | --- | --- |
| 公网 smoke | **通过** | `ALL CHECKS PASSED`（health / home / create_room / ws_player / ws_spectator / ws_bad_token） |
| 视角隔离（HTTP 层） | **通过** | 无 `X-Player-Token` 读取房间 → 401 |
| 完整对局（本地） | **通过** | 234 项测试含 `test_web_game_e2e`；实测 18 次阶段自动切换 |
| 完整对局（公网） | **阻塞** | 见第二节，100 秒零推进 |
| 自由选座 | **阻塞（未实现）** | 见下 |

### 4.1 自由选座：功能不存在

任务单要求「指定 seat、占座、非法 seat 都要有拒绝逻辑」。核查结果：

```text
JoinRoomRequest 字段     ：仅 nickname，无 seat
backend/api.py 出现 seat ：0 处
seat_taken / invalid_seat ：无此类错误
rooms.join_room()        ：调用 choose_join_seat() 自动分配座位
frontend LobbyPanel.vue  ：无选座界面
```

**加入房间只能自动分配座位，无法指定、无法占座、也不存在「非法 seat」的拒绝路径**（因为没有入口）。

判定：**阻塞**。接口未上线，不能写「不通过」——按任务单要求，接口没实现应记阻塞。

## 五、需要真人完成的项

| 项 | 原因 |
| --- | --- |
| AI 发言气泡是否显示座位/名字/内容 | 必须真实浏览器逐条看，脚本只能证明事件里有 `content` |
| 好人/狼人/观战者三视角的狼聊不泄漏 | 抓帧可脚本化，但「气泡不显示狼聊」是渲染层判断 |
| 刷新恢复对局 | 需要浏览器刷新 |

## 六、给订书机的两条

**1. 公网必须先能玩。** 这是三天目标的唯一指标，现在公网一局都推不动。本地代码是好的，问题在部署——请核对服务器上运行的 commit，以及 `RoomTimerService` 是否真的在跑。建议加一个能自证的接口（例如 `/health` 返回 commit），否则以后还会出现「本地好、公网坏」的扯皮。

**2. 没有 Key 时 AI 发言是同一句模板。** 如果演示要用真实模型发言，需要配 Key；如果不配，得接受「所有人说同一句话」，或者改成多样化的规则文案。这件事越早定越好，因为它直接决定 3-5 分钟成片能不能看。

## 七、本次未做的事

- 未登录服务器排查部署（无访问权限，只做外部探测）。
- 未验证浏览器层的发言气泡与刷新恢复。
- 未修改任何业务代码。
- 未在公网写入持久数据（测试房间随后过期）。
