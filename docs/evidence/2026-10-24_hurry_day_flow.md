# 白天流程验收记录

日期：2026-10-24

执行人：Hurry

基线提交：`27d9b9b`（`docs: document daytime engine and acceptance coverage`）

对应任务单：《10月24至25日 Hurry 验收与部署任务单》10 月 24 日三小时计划

## 1. 基线与测试数量

```text
git pull --ff-only origin main   → 27d9b9b，本地与远端一致
python -m unittest discover -s tests
Ran 87 tests in 0.010s  OK       ← 拉取后基线
新增 5 条验收测试后 → Ran 92 tests  OK
```

订书机当日提交：

| 提交 | 内容 |
| --- | --- |
| `1509182` | `feat: implement daytime rules and hunter flow` |
| `27d9b9b` | `docs: document daytime engine and acceptance coverage` |

同时确认：前一日预检提出的 **P1（狼队长死亡后第二夜死锁）已修复**——`start_night` 现在会检查队长存活状态，自动重选并写入 `WOLF_CAPTAIN_ELECTED` 事件。复跑探针确认：队长被毒死后，第二夜队长变为存活者 `p3`，狼人发言后正常进入 `NIGHT_WOLF_KILL`。

## 2. 验收结果

| 用例 | 规则 | 结果 | 依据 |
| --- | --- | --- | --- |
| TC-08 自爆取消投票与窗口 | DESTRUCT-001 至 008 | 通过 | 自爆后阶段转 `SELF_DESTRUCT`，投票入口关闭，窗口内提交投票被拒绝 |
| TC-10 平票与零票 | VOTE-005、VOTE-006 | 通过 | 零票与平票均不放逐，阶段正常推进 |
| TC-13 解药免疫本次狼刀 | WITCH-007、WITCH-008 | 通过 | 夜间既有测试覆盖，复跑无回归 |
| TC-14 同目标双死因 | WITCH-011 | 通过 | 同一目标只生成一次死亡事件并记录两个死因 |
| TC-15 遗言长度限制 | 规则表第 7 章 | 通过（补充边界） | 30 字允许、31 字拒绝，边界成对验证 |
| 猎人开枪后胜负检查时机 | VOTE-008、WIN-001 | 通过（补充顺序） | 被带走者先留遗言，之后才进入 `END` |

未实现故记为阻塞：完整 Web 接口、房间与观战密码（属 10 月 25 日范围）。

## 3. 新增验收测试（5 条）

文件：`tests/test_day_flow_acceptance.py`

| 测试 | 对应规则 | 验证内容 |
| --- | --- | --- |
| `test_exactly_thirty_characters_is_allowed` | 规则表第 7 章 | 遗言正好 30 字被接受（**上限已改为 100 汉字，待代码落地后改为 100/101**） |
| `test_thirty_one_characters_is_rejected` | 规则表第 7 章 | 31 字被拒绝且不进入已完成队列（**同上，改为 101 字**） |
| `test_vote_is_rejected_while_self_destruct_window_is_open` | DESTRUCT-003 | 自爆窗口内投票被拒绝 |
| `test_second_self_destruct_after_deadline_is_rejected` | DESTRUCT-004 | 超过 110.0 秒再自爆被拒绝 |
| `test_hunter_shot_killing_last_wolf_gives_target_last_words_then_ends` | VOTE-008、WIN-001 | 猎人打死最后一狼后，被带走者先留遗言，再进入 `END` 并写入 `WINNER_DECIDED` |

全部 5 条通过，未修改任何业务代码。

## 4. 三视角可见性证据

方法：使用**真实对局**（`create_game(seed=901)`，不覆写角色），跑完整一夜后按四种视角分别调用 `get_visible_events`，统计各事件可见条数。

真实角色分布：`p1` 猎人、`p2`/`p5`/`p7` 狼人、`p3`/`p4`/`p8` 村民、`p6` 女巫、`p9` 预言家。

| 事件类型 | 普通玩家 p3 | 狼人 p2 | 预言家 p9 | 观战者 |
| --- | ---: | ---: | ---: | ---: |
| `GAME_CREATED` | 0 | 0 | 0 | 1 |
| `ROLE_ASSIGNED` | 1（仅自己） | 3（三只狼） | 1（仅自己） | 9 |
| `WOLF_CAPTAIN_ELECTED` | 0 | 1 | 0 | 1 |
| `WOLF_SPEECH` | 0 | 6 | 0 | 6 |
| `WOLF_KILL_SELECTED` | 0 | 1 | 0 | 1 |
| `SEER_CHECKED` | 0 | 0 | 1 | 1 |
| `PLAYER_DIED` | 1 | 1 | 1 | 1 |
| `NIGHT_STARTED` | 1 | 1 | 1 | 1 |

死亡原因可见性：

| 视角 | 死亡事件是否含 `causes` |
| --- | --- |
| 普通玩家 | 否 |
| 狼人 | 否 |
| 预言家 | 否 |
| 观战者 | 是（`['wolf_kill']`） |

死亡后权限收缩：死亡狼人可见的 `WOLF_SPEECH` 为 **0 条**，符合 VIEW-002「玩家死亡后仍只能保留玩家视角」。

结论：信息隔离符合规则 2.1，玩家、狼队、预言家、观战者四类视角的可见范围互不相同且边界正确。

## 5. 本次发现的三项问题

### 5.1 测试辅助函数会让事件表与角色不一致（重要，非引擎缺陷）

`tests/test_day_engine.py` 的 `controlled_game()` 是先用 `create_game()` 生成对局，再直接覆写 `player.role`。`ROLE_ASSIGNED` 事件是在 `create_game` 阶段写入的，覆写角色后**没有重建事件**，因此事件表里的角色与实际 `player.role` 不一致。

实测（seed=901）：`player.role` 显示 p1 是狼，而事件表里 p1 的 `ROLE_ASSIGNED` 记的是 `hunter`；从 p1 视角读事件会得到 4 条身份事件，看起来像信息泄漏，实际是两侧数据源不同步。

影响：

- 该辅助函数用于**规则动作**测试完全没问题。
- 但**不能用来做可见性证据**。任何基于它导出的"某视角能看到什么"都可能得出错误结论，包括误报泄漏或漏报真实泄漏。
- 本记录第 4 节因此改用真实对局重做。

建议：在 `controlled_game` 的 docstring 里注明「覆写角色后事件表不同步，勿用于可见性测试」，或改为覆写后重建 `ROLE_ASSIGNED` 事件。

### 5.2 自爆窗口在 110.0 秒处存在边界歧义（规则已明确，待代码对齐）

实测结果：

```text
窗口截止 110.0
now=109.9 第二狼自爆 → 允许
now=110.0 第二狼自爆 → 允许
now=110.1 第二狼自爆 → 被拒绝：自爆窗口已经关闭
```

而既有测试 `test_other_wolves_can_continue_until_window_closes` 中，`close_self_destruct_window(now=110.0)` 也能成功关闭窗口。

也就是说，在 `now=110.0` 这一时刻，**自爆与关闭窗口同时合法**，最终行为取决于调用顺序。

**2026-10-24 更新**：订书机已确认规则——自爆窗口到达 10 秒边界**立即关闭**，`now >= deadline` 时自爆应被拒绝。本文记录的问题得到规则层面的确认，代码对齐后需新增 `now=110.0` 自爆被拒的断言。变更影响与执行顺序见 `docs/evidence/2026-10-24_rule-change-impact.md`。

### 5.3 死亡玩家的自我身份事件也消失了（待确认）

死亡狼人视角下 `ROLE_ASSIGNED` 为 0 条，包括**自己**那一条。规则 2.1 规定「玩家真实身份」对本人可见，VIEW-002 规定死亡后保留玩家视角。按字面理解，玩家应当始终能看到自己的身份事件。

如果这是有意的设计（前端在开始时已缓存自己的角色，事件流不再重复提供），建议在规则文档或 `get_visible_events` 的注释中写明；否则属于过滤过度。

## 6. 超时兜底的进展（前一日 P4）

前一日预检的 **P4（超时兜底）已部分解决**。订书机在 `d00f140`（`feat: enforce public speech timeout and stable state`）中新增了 `timeout_public_speech`，公共发言不再能无限等待。

仍未覆盖的超时点：

| 阶段 | 规则要求 | 现状 |
| --- | --- | --- |
| 公共发言 | DAY-003 只能在本人回合发言 | 已实现 |
| 狼队长提交刀人 | WOLF-011 超时按空刀 | 未实现 |
| 预言家查验 | 夜晚顺序第 4 步，超时为未查验 | 未实现 |
| 女巫用药 | 同夜至多一种，超时为不用药 | 未实现 |
| 投票 | VOTE-003 以截止前最后一次为准 | 未实现 |

其中**狼刀与投票**的超时最关键：真人房主挂机或真人玩家掉线时，这两个阶段会永久等待，直接违反「一局约 5 分钟」的目标。建议 10 月 26 日前后补齐。

## 7. 下一步

- 10 月 25 日：等最小 Web 入口可用后，按任务单做联机、观战密码、手机 390px 与模型失败兜底验收，结果写入 `docs/evidence/2026-10-25_hurry_web_acceptance.md`。
- 若 Web 入口未就绪，则继续在引擎层补充 `resolve_vote` 与 `DAY_ANNOUNCEMENT` 之间的衔接用例，并把 Web 相关项记为阻塞。
