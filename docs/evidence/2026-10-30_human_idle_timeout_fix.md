# 真人回合超时自动补位修复 · 2026-10-30

## 现象

真人被分到夜晚角色（狼人/预言家/女巫）或轮到白天投票时，如果本人不动，
游戏就停在当前阶段无法推进。表现是“狼人阶段之后无法持续”。

## 根因

服务端只有白天发言、遗言、自爆窗口有截止时间；夜晚动作（狼队发言、狼刀、
预言家查验、女巫用药）和白天投票都没有截止时间。AI 座位由 `AIController`
立即代打，但真人座位一旦不操作就永久等待，卡死整局。

## 修复

- `GameState` 增加通用阶段截止时间 `phase_deadline_at` / `phase_deadline_kind`。
- 当 `AIController.advance()` 停在“真人待行动”的夜晚阶段或投票阶段时，
  写入 20 秒截止时间（`human_action`）。
- 定时器到期后 `auto_play_human_turn()` 用房间 AI 策略（L0）替该真人
  执行一步合法动作，再继续推进；失败会回滚状态并记录日志。
- `RoomSnapshot.deadline_kind` 新增 `human_action`，前端倒计时显示
  “行动倒计时”。

覆盖阶段：`NIGHT_WOLF_DISCUSSION_R1/R2`、`NIGHT_WOLF_KILL`、
`NIGHT_SEER_CHECK`、`NIGHT_WITCH_ACTION`、`NIGHT_HUNTER_SHOT`、`VOTE`、
`DAY_HUNTER_SHOT`。

## 验证

- 全量测试：233 项 OK（新增 `test_idle_human_night_role_reaches_end_via_autoplay`，
  模拟真人狼人 600 次超时推进，断言到达 `END`）。
- 前端 `vue-tsc + 静态构建` 通过。
- 本地 HTTP 实测：seed=3 真人=狼人，`start_night` 后快照返回
  `deadline_kind=human_action`、`remaining_ms=20000`；22 秒后阶段自动从
  `NIGHT_WOLF_DISCUSSION_R1` 推进到 `NIGHT_WOLF_DISCUSSION_R2`。

## 边界

- 该补位只发生在真人 20 秒未操作时；真人正常操作不受影响。
- 自动补位使用 L0 随机策略，动作必须经过服务端合法动作校验，不会伪造。
- 相关提交见 `git log --oneline -- backend/ai_controller.py`。
