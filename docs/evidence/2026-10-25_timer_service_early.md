# 服务层房间计时器执行证据

实际执行日期：2026-10-25

对应任务：10 月 26 日计划中的真实服务层计时。

代码提交：`debc3db`

## 1. 架构

新增 `backend/timers.py` 中的 `RoomTimerService`：

- FastAPI 启动时创建后台异步扫描任务。
- 每 0.1 秒扫描所有内存房间。
- 只检查已有截止时间的遗言、公开发言和自爆窗口。
- 到期动作在房间锁内执行。
- 执行后继续调用 AI 控制器，直到下一次真人决策。
- 每个已提交变化立即通过 WebSocket 广播。
- 应用关闭时取消后台任务。

## 2. 到期处理

| 阶段 | 截止字段 | 服务动作 |
| --- | --- | --- |
| `DAY_LAST_WORDS` | `last_words_deadline` | `timeout_last_words` |
| `DAY_DISCUSSION` | `speech_deadline` | `timeout_public_speech` |
| `SELF_DESTRUCT` | `self_destruct_deadline` | `close_self_destruct_window` |

阶段或截止字段变化后，下一次扫描不会再次执行旧动作。

## 3. 自动化验证

新增 `tests/test_timers.py`，覆盖：

- 30 秒前不触发。
- 到达公开发言截止点只产生一次 `PUBLIC_SPEECH_TIMEOUT`。
- 到达遗言截止点只产生一次 `LAST_WORDS_TIMEOUT`。
- 10 秒自爆窗口到期只关闭一次。
- 重复扫描不重复写事件。

全量结果：

```text
Ran 165 tests
OK
```

## 4. 真实 WebSocket 验证

固定 `seed=1`、1 名真人房：

1. 真人点击开始首夜。
2. AI 自动推进到真人公开发言。
3. 测试不提交人类发言。
4. WebSocket 在 `30030 ms` 收到 `PUBLIC_SPEECH_TIMEOUT`。
5. AI 自动继续行动并进入 `SELF_DESTRUCT`。
6. 不操作自爆窗口。
7. WebSocket 在 `10085 ms` 收到窗口关闭后的新阶段。
8. AI 继续推进，最终到达 `END`。

实际结果：

```json
{
  "public_speech_timeout": true,
  "speech_timeout_elapsed_ms": 30030,
  "self_destruct_window_elapsed_ms": 10085,
  "final_phase": "END",
  "event_count": 18
}
```

## 5. 当前边界

- 服务端截止时间已经真实生效。
- Vue 页面尚未显示倒计时数字，下一步需要把截止时间和服务器时间纳入快照。
- 刷新后的玩家凭证恢复和完整观战/死亡页面仍未完成。
