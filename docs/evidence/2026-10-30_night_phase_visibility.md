# 村民夜晚阶段可见性修复 · 2026-10-30

## 现象

真人被分到村民时，`start_night` 后整夜在瞬间跑完，直接跳到白天发言。
村民看不到狼队讨论、预言家查验、女巫行动等阶段，也没有倒计时。

## 根因

`AIController.advance()` 在一次调用里连续执行最多 300 步，AI 的整个夜晚
在单个 HTTP 请求内完成，中间阶段从不广播给客户端。

## 修复

夜晚改为“每阶段推进一次”：`advance()` 在夜晚行动阶段完成后立即停下，
服务端为下一个阶段设置 4 秒倒计时（`phase_pace`），由 `RoomTimerService`
到期后推进下一阶段。非夜晚角色因此能看到每个夜晚阶段的名称与倒计时：

狼队讨论 → 狼刀 → 预言家查验 → 女巫行动 → 夜间结算 → 天亮公告。

真人仍需操作时沿用 20 秒 `human_action` 倒计时；白天发言/遗言/自爆
倒计时不变。前端倒计时新增“夜间推进”标签。

## 验证

- 全量测试 233 项 OK，更新了受影响的 6 处断言并新增
  `test_ai_paces_night_phases_one_at_a_time`。
- 前端 `vue-tsc + 静态构建` 通过。
- 本地 HTTP 实测（seed=1，真人=村民）：`start_night` 后按 4 秒间隔依次
  返回 `NIGHT_WOLF_DISCUSSION_R2 → NIGHT_WOLF_KILL → NIGHT_SEER_CHECK →
  NIGHT_WITCH_ACTION → NIGHT_RESOLUTION → DAY_ANNOUNCEMENT → DAY_LAST_WORDS`，
  每阶段 `deadline_kind=phase_pace`。

## 边界

- 每个夜晚阶段的固定 4 秒用于展示推进节奏，不改变胜负判定或动作合法性。
- 狼队讨论第一轮（R1）在 `start_night` 后立即完成，首个可见的讨论阶段是
  第二轮；如需连第一轮也逐段展示，需额外拆分 `start_night` 之后的首次推进。
