# 10 月 27 日模拟器步骤 1 至 2 验收

日期：2026-10-25

代码提交：`4bf7e77`

死锁与边界测试提交：`d0ca976`

后端版本：`0.5.0`

## 完成范围

新增 `backend/simulator.py`，复用：

- `create_game`
- `AIController.plan_next_step`
- `available_actions_for_state`
- `execute_engine_action`
- `check_winner`

模拟器不复制角色规则、阶段规则或胜负规则。

支持参数：

```text
--games
--seed-start
--policy l0
--out
--max-steps
--max-days
--no-self-destruct
```

每局默认最多 600 个动作步、20 天。无合法动作、动作异常、截断或状态未推进时
都会终止当前局并记录结构化错误。

## 日志

输出目录包含：

```text
run.json
games.jsonl
actions.jsonl
```

`games.jsonl` 每局一行，包含 seed、状态、终局阶段、胜者、动作步数、天数、
九人角色、存活玩家、错误和耗时。

`actions.jsonl` 每个动作一行，包含：

```text
game_id
seed
policy
step
day
phase
event_seq_before
event_seq_after
actor_id
actor_role
is_system
legal_actions
action
target_id
choice
content
succeeded
error
simulated_time
phase_after
```

文本动作的实际生成内容也写入日志，但后续统计应明确不把文本当作战术标签。

## 运行结果

10 局：

```text
命令：
python -m backend.simulator --games 10 --seed-start 1000 --policy l0 --out training_runs/smoke-l0

完成局：10
失败局：0
动作步：521
耗时：161.667 ms
```

200 局：

```text
命令：
python -m backend.simulator --games 200 --seed-start 1000 --policy l0 --out training_runs/l0-200

完成局：200
失败局：0
动作步：8719
耗时：2414.984 ms
games.jsonl：200 行
actions.jsonl：8719 行
成功动作：8719
失败动作：0
缺失 phase_after：0
文本动作包含内容：4285
```

17 类动作均实际出现：

```text
wolf_speech                    2264
speech                         1715
vote                           615
wolf_kill                      570
resolve_night                  570
begin_day                      504
seer_check                     475
witch_action                   471
self_destruct                  337
last_words                     306
close_self_destruct_window     221
close_vote                     167
resolve_vote                   167
begin_banishment_last_words     67
night_hunter_shot               60
day_hunter_shot                 10
start_night                    200
```

原始终局分布：

```text
好人胜：168
狼人胜：32
总局数：200
```

这只是固定 seed 1000 至 1199、L0 随机策略的原始结果，不能写成训练提升、
策略优劣或比赛预测。

## 固定 seed 复现

同一 seed `1033` 独立运行两次：

```text
动作记录是否逐字段一致：是
终局摘要是否一致：是
动作数：74
阶段：END
胜者：good
天数：4
```

## 女巫刀口

`RoomSnapshot` 新增：

```text
witch_kill_target_visible
witch_kill_target_id
```

仅在存活女巫、`NIGHT_WITCH_ACTION`、仍有解药时可见。覆盖：

- 有解药且有刀口：返回准确玩家 ID。
- 有解药且狼人空刀：`visible=true`、目标为空，页面显示没有刀口。
- 解药已经消耗：不可见。
- 非女巫：不可见。
- 前端私密信息卡只在可见时渲染。

## 测试与构建

```text
Python：189 tests OK
前端：TypeScript 检查通过
前端静态构建：通过
健康检查：wolfarena-api 0.5.0
```

## 当前边界

步骤 1 和步骤 2 已完成。

尚未实现：

- 指标计算脚本和浏览器指标面板。
- 训练版策略及策略版本切换。
- 固定 seed 新手版/训练版对比。
- 模型卡。

`training_runs/` 中的 10 局和 200 局原始输出按仓库规则不提交 Git，但保留在
本地 E 盘，可用于下一步指标复算。
