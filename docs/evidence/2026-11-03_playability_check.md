# 11 月 3 日可玩性验收（按最终版任务单）

日期：2026-11-03

执行人：Hurry

代码：`196dc4e`（部署后公网与本地一致）

公网：`http://106.14.113.216:8080`

## 一、结论

```text
公网部署完成（20:39 之后），本轮可玩性通过。
完整对局：INIT → END，273.2 秒，全程只点一次开始，无卡死。
```

## 二、部署前的问题（已解决，保留作记录）

部署前公网跑的是旧版本，我用「自由选座」参数做探针确认：

| 环境 | `POST /api/rooms/{id}/join` 带 `seat: 5` | 结论 |
| --- | --- | --- |
| 部署前公网 | `422 extra_forbidden` | 旧版，无选座 |
| 部署前本地 | `200`，座位 5 | 新版 |

同时部署前公网**夜间无超时兜底**：真人拿狼人身份不操作，60–100 秒零推进（预言家身份 75 秒、狼人身份 100 秒，三次独立房间一致）。白天的 30 秒发言超时是正常的，说明缺的是夜间 deadline。

部署后上述两项均恢复正常，详见下节。

## 二之二、部署记录核对（订书机提供，Hurry 复核）

订书机说明：20:34 左右完成部署，服务器 HEAD `25adc0d`，工作区干净，部署前备份在 `/www/backup/wolfarena-dist-predeploy-196dc4e.tgz`；使用 `merge --ff-only` 而非 `reset --mixed`；`requirements.txt` 在 `0881724..196dc4e` 之间未变化，故未执行 `pip install`。

逐条复核结果：

| 说法 | 复核方式 | 结论 |
| --- | --- | --- |
| `requirements.txt` 未变 | 本地 `git diff --stat 0881724 196dc4e -- requirements.txt` | **无输出，属实** |
| `25adc0d` 只多一条部署记录文档 | `git log -1 25adc0d` | `docs: record public deployment update to 196dc4e`，属实 |
| 记录字段 `deadline_kind` | 公网快照 | 存在，值为 `human_action`，另有 `deadline_at`、`remaining_ms` |

> 关于我此前提出的三点提醒：`reset --mixed` 与 `pip install` 两项针对的是截图里那段通用命令，实际采用的是 `merge --ff-only` 且依赖未变，因此两项均不适用；第三点「验证太弱」订书机称已跑四类验证。**提醒本身不必照做，但保留在文档里，供下次部署时对照。**

本轮快照新增可见字段（此前未记录）：

```text
deadline_at, deadline_kind, remaining_ms
available_seats, witch_kill_target_id, witch_kill_target_visible
```

## 三、部署后验证（本轮正式结论）

### 3.1 版本与接口

```text
GET /health  → 200 {"status":"ok","service":"wolfarena-api","version":"0.6.0"}
接口总数     → 12 个（部署前 6 个）
```

完整接口清单：

```text
/api/rooms                              /api/strategy/search
/api/rooms/{room_id}                    /api/training/metrics
/api/rooms/{room_id}/actions            /api/training/models
/api/rooms/{room_id}/ai-action          /api/training/models/{model_id}
/api/rooms/{room_id}/join               /api/training/rollout
/api/rooms/{room_id}/seats              /health
```

新增的 `/api/rooms/{room_id}/seats`、`/api/strategy/search` 与四个训练场接口全部上线。

### 3.2 自由选座

```text
POST /api/rooms/{id}/join {"nickname":"选座者","seat":5}
→ 200，viewer.seat = 5                 通过

GET /api/rooms/{id}/seats
→ 200，{"available_seats":[2,3,4,5,6,7,8,9]}   通过
```

任务单要求的「指定 seat」成立。还剩两项未验（占座冲突、非法 seat 拒绝），见第六节。

### 3.3 夜间超时兜底

真人身份狼人，点一次 `start_night` 后完全不操作：

```text
1 秒后   NIGHT_WOLF_DISCUSSION_R1
20 秒后  → NIGHT_WOLF_DISCUSSION_R2       通过
```

完整对局中另一处佐证：真人身份预言家时，`NIGHT_SEER_CHECK` 停留 20.4 秒后自动跳过进入 `NIGHT_RESOLUTION`，说明真人的夜间待办到点会被代打/跳过。

### 3.4 完整对局（本轮最关键一项）

1 真人 + 8 AI，seed 2468，真人身份预言家，**只点一次「开始首夜」，之后不再操作**：

```text
  0.0s  1/NIGHT_WOLF_DISCUSSION_R2   事件 2
  4.1s  1/NIGHT_WOLF_KILL            事件 2
  8.2s  1/NIGHT_SEER_CHECK           事件 2
 28.6s  1/NIGHT_RESOLUTION           事件 3
 32.6s  1/DAY_ANNOUNCEMENT           事件 5
 36.7s  1/DAY_LAST_WORDS             事件 5
 66.3s  1/DAY_DISCUSSION             事件 12
 96.8s  1/VOTE                       事件 14
117.2s  2/NIGHT_WOLF_DISCUSSION_R1   事件 17
...
269.2s  3/NIGHT_RESOLUTION           事件 32
273.2s  3/END                        事件 79
```

**到达 END，总耗时 273.2 秒（约 4.5 分钟），事件 79 条，全程无人工干预。**

任务单「从 INIT 打到 END，无卡死」**通过**。

各阶段耗时符合设计：狼人讨论/刀人约 4 秒，预言家查验 20 秒，结算约 4 秒，白天公告/遗言约 4 秒，发言 30 秒，投票 20 秒。

### 3.5 公网冒烟

```text
health: ok    home: ok    create_room: ok
ws_player: ok    ws_spectator: ok    ws_bad_token: ok (rejected)
ALL CHECKS PASSED
```

### 3.6 训练场模型（属 11-05 内容，顺带验证）

```text
GET /api/training/models → 200，4 个模型
  l0.random.v1
  l1.rules.v1
  l2.qtable.v1
  l2.qtable.v2
```

任务单 11-05 要求「四个模型可列出」**已满足**。指标复算与胜率文档未验，留到 11-05。

## 四、逐项对照任务单

| 11-03 任务 | 结果 |
| --- | --- |
| AI 发言（气泡显示座位/名字/内容） | **未验**（见第五节） |
| 视角隔离（三视角） | **部分通过**：HTTP 层无 token → 401；气泡层未验 |
| 完整对局 INIT→END | **通过**：273.2 秒，79 事件，无卡死 |
| 自由选座（指定 seat） | **通过** |
| 自由选座（占座、非法 seat） | **未验** |
| 公网 smoke | **通过** |

## 五、需要真人完成的项

| 项 | 原因 |
| --- | --- |
| 发言气泡是否显示座位/名字/内容 | `PUBLIC_SPEECH` 事件只有 `content` 与 `actor_id`，无 `seat`/`name`，前端需自行映射；必须真实浏览器逐条看 |
| 三视角下狼聊是否泄漏到气泡 | 抓帧可脚本化，渲染层判断需人看 |
| 刷新恢复对局 | 需浏览器按 F5 |

## 六、剩余风险

1. **占座冲突与非法 seat 拒绝未测**：只验了「指定空座成功」，没验「指定已占座」和「seat=0 / seat=10 / seat 非数字」。建议补测，这是权限类缺陷的高发点。
2. **无 Key 时 AI 发言质量**：本轮未抓取发言内容。若仍走模板兜底，九个座位可能说同一句话，影响 3-5 分钟成片观感。
3. **部署一致性**：`/health` 仍只返回 `0.6.0`，无法自证 commit。本次靠「选座参数被拒」反推出版本落后，耗时约 15 分钟。建议后续加入构建信息（commit 短哈希 + 构建时间），把这类排查从「反推」变成「一查」。
4. **首次计时偏差**：我测得夜间自动推进为 20 秒（2 秒轮询粒度），订书机记录约 24 秒。两者均说明兜底生效，差异可能来自轮询精度与 deadline 起算点，不影响判定。

## 七、本次未做的事

- 未登录服务器，全部为外网探测。
- 未验证浏览器层的发言气泡、刷新恢复。
- 未修改任何业务代码。
- 未在公网写入持久数据（测试房间随进程过期）。
