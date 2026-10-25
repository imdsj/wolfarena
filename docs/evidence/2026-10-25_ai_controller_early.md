# AI 自动回合执行证据

实际执行日期：2026-10-25

对应任务：10 月 26 日计划中的 AI 自动回合。

代码提交：`067b7c2`

浏览器 seed 收口提交：`a71380c`

## 1. 设计

新增 `backend/ai_controller.py`：

- 每个房间持有独立 `L0Policy`，使用房间 seed 初始化。
- AI 只能从服务端 `available_actions` 中选择动作。
- AI 动作仍调用统一 `execute_room_action` 服务入口。
- 控制器不读取文件、不启动终端、不调用网络工具。
- 无人工选择的系统动作自动推进。
- 轮到真人时立即停止。
- 单次控制循环上限为 300 步。

动作目标、药物选项和文本内容由房间 seed、策略版本、事件序号与行动者共同
决定，不使用浏览器时间或前端随机数。

## 2. 回合边界

自动执行：

- AI 狼人发言、狼刀、预言家查验、女巫行动。
- AI 猎人开枪。
- AI 遗言和公开发言。
- AI 投票。
- `resolve_night`、`begin_day`、`resolve_vote`、
  `begin_banishment_last_words`。
- 已到期自爆窗口的系统关闭。

在以下位置停止：

- 轮到真人角色行动。
- 轮到真人公开发言或遗言。
- 真人需要投票、截止投票。
- 未到 10 秒自爆窗口截止时间。

## 3. 失败处理

调用引擎前保存状态副本。AI 动作失败时：

- 恢复动作前的 GameState。
- 不改变阶段、玩家、票箱或夜间结果。
- 写入仅房主可见的 `AI_ACTION_FAILED` 事件。
- 停止本轮 AI 推进。

超过单次 300 步上限时同样停止并写入失败事件。

## 4. 自动化验证

新增 `tests/test_ai_controller.py`，覆盖：

- AI 从首夜自动推进到真人白天发言。
- 真人发言后 AI 继续推进到投票或自爆窗口。
- 相同 seed 与相同动作序列产生相同事件序列。
- 单次步数上限阻止无限循环。
- AI 动作异常时核心阶段不变，并记录拒绝原因。

全量结果：

```text
Ran 161 tests
OK
```

## 5. 真实服务验证

固定 `seed=1`、1 名真人的房间执行 `start_night` 后，真实 API 返回：

```text
Phase: DAY_DISCUSSION
Day: 1
AvailableActions: speech
```

说明服务端自动完成了 AI 狼队发言、狼刀、预言家、女巫、夜晚结算和白天初始化，
最后停在真人公开发言。

前端 DOM/HTTP/WebSocket 冒烟继续通过：

```text
connectionText: 已连接
hasServerStartAction: true
hostUpdatedAfterJoin: true
hasNightStartedEvent: true
```

## 6. 当前边界

- 未实现服务层 10 秒/30 秒定时器。
- 因此 AI 在自爆窗口或真人超时时不会按真实时间自动推进。
- 浏览器刷新后的凭证恢复仍未实现。
- 浏览器实时建房不再传 `Date.now()`；seed 由服务端生成，固定 seed 只用于显式脚本或训练。
