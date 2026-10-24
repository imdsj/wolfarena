# 10 月 25 日 WebSocket 任务步骤 2 提前执行证据

实际执行日期：2026-10-24

执行范围：WebSocket 认证、事件过滤、观战视角、重连和房间级串行化。

## 1. 协议

连接地址：

```text
/ws/rooms/{room_id}
```

玩家连接后的第一条消息：

```json
{"type":"authenticate","token":"玩家凭证"}
```

观战者连接后的第一条消息：

```json
{"type":"authenticate","spectator_password":"本局观战密码"}
```

认证成功后依次发送：

```text
authenticated
snapshot
phase
```

状态变化后，对每个连接分别调用 `get_visible_events`，发送该视角可见的
`event`，再发送新的 `phase`。每条游戏事件保留引擎生成的连续
`event_seq`。

Token 和观战密码不进入 URL 查询参数，也不写入应用日志。

## 2. 自动化验证

命令：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

结果：

```text
Ran 136 tests
OK
```

新增测试覆盖：

- 第一条消息认证，以及认证成功后的初始阶段消息。
- 非法玩家 Token、错误观战密码和不存在房间使用独立关闭码。
- 同一连接重复认证被拒绝。
- 每局观战密码不同。
- 普通玩家看不到狼人私聊、他人身份和夜间死因。
- 存活狼人能看到狼队长事件。
- 死亡狼人重连后不能获得狼队视角。
- 持密码观战者能看到完整事件和死亡原因。
- 使用同一 Token 重连后保留原座位和当前阶段。
- 阶段外动作返回 `OUT_OF_PHASE`，不改变状态。
- 观战者不能执行游戏动作。
- 游戏开始后关闭新玩家加入。
- 两个并发 `start_night` 请求只有一个成功，另一个被阶段校验拒绝。
- 原有超员和重复昵称测试继续通过。

## 3. 真实 Uvicorn 验证

启动：

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.api:app --host 127.0.0.1 --port 8766
```

使用 Node.js 26.8.1 原生 WebSocket 客户端连接，实际消息顺序：

```text
authenticated
snapshot
phase
event
event
phase
action_result
```

初始阶段为 `INIT`，执行 `start_night` 后进入
`NIGHT_WOLF_DISCUSSION_R1`。

Uvicorn 访问日志只记录：

```text
WebSocket /ws/rooms/{room_id} [accepted]
```

没有记录 Token、观战密码或查询串。

## 4. W 组结论

| 编号 | 状态 | 依据 |
| --- | --- | --- |
| W-01 | 通过 | Uvicorn 可启动并持续响应 |
| W-02 | 通过 | `/health` 返回 200 和版本 0.2.0 |
| W-03 | 通过 | 创建 9 人房间，1 真人、8 AI |
| W-04 | 通过 | 认证后 5 秒内收到含 `phase` 的事件 |
| W-05 | WebSocket 层通过 | 普通玩家无他人身份或狼人事件；死亡重连无上帝视角 |

W-05 保留正式游戏规则：存活狼人可以查看狼队身份和狼队事件；普通好人只能
查看自身角色，死亡玩家失去狼队视角。

## 5. 当前边界

- 游戏动作目前只实现 `start_night`。
- 观战密码保存在内存房间中，服务重启后房间和密码均失效。
- 尚未实现持久化、完整服务层计时器、前端页面和模型兜底。
