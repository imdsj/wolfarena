# 10 月 26 日统一动作路由任务提前执行证据

实际执行日期：2026-10-25

对应手册：2026-10-26 两小时计划步骤 1、步骤 2。

起始提交：`54cebeb`

代码提交：`8dcb883`

## 1. 基线环境

仓库：

```text
E:\dings\Documents\Codex\2026-10-20\web\wolfarena
```

执行结果：

- `git pull --ff-only origin main`：Already up to date。
- 仓库内 `.venv` 可用。
- 后端自动化测试：155 项通过。
- `npm run build`：通过。
- `npm run smoke:client`：通过。

## 2. 构建环境修正

当前 Codex Windows 沙箱禁止 Vite 的 `esbuild` 启动子进程。为保证手册中的
`npm run build` 确实可执行：

- `npm run build` 改为 Vue 类型检查加仓库内静态 Vue 构建。
- 标准 Vite 构建保留为 `npm run build:vite`。
- 构建脚本新增 `ActionForm.vue` 编译项。

## 3. 统一动作入口

新增 `backend/actions.py`：

- `available_actions_for_state` 生成当前凭证的合法动作、目标和选项。
- `execute_engine_action` 是唯一动作分发入口。
- HTTP 与 WebSocket 都调用房间仓库的同一个 `execute_action`。
- 调用引擎前保存完整状态副本，校验或引擎异常时恢复，保证非法动作不改变状态。

当前动作映射：

```text
start_night
wolf_speech
wolf_kill
seer_check
witch_action
resolve_night
night_hunter_shot
begin_day
last_words
speech
self_destruct
close_self_destruct_window
vote
close_vote
resolve_vote
begin_banishment_last_words
day_hunter_shot
```

## 4. 服务端快照

`RoomSnapshot.available_actions` 现在包含：

```text
action
label
target_ids
choices
requires_content
requires_target
allow_no_target
```

动作按服务端阶段、角色、存活状态、座次和权限生成。观战者没有动作；普通玩家
不会收到其他角色的私有动作；系统推进动作只提供给房主控制端。

HTTP：

```text
POST /api/rooms/{room_id}/actions
X-Player-Token: 玩家凭证
```

WebSocket：

```json
{"type":"action","action":"vote","target_id":"p2"}
```

两种入口共用同一执行函数。

## 5. 自动化覆盖

新增 `tests/test_actions.py`，覆盖：

- INIT 阶段只向房主提供 `start_night`。
- 狼人发言按服务端座次顺序逐渐开放。
- 无人工修改引擎状态的完整首夜、白天发言、全员弃权和下一夜闭环。
- 非法目标在进入引擎前被拒绝。
- 非法目标和阶段外动作不会改变阶段或事件数。
- HTTP 动作推进阶段，并使用与 WebSocket 相同的执行入口。

全量结果：

```text
Ran 155 tests
OK
```

## 6. Vue 动态动作面板

- 新增 `ActionForm.vue`。
- 按钮、目标、选项和文本输入全部来自服务器快照。
- 浏览器不自行判断阶段权限。
- `start_night` 仍可显示 AI 推荐入口。
- DOM 冒烟确认服务器开始动作被渲染，并能在执行后更新阶段。

DOM 结果：

```text
hasServerStartAction: true
hostUpdatedAfterJoin: true
phaseAfterAction: 首夜狼队讨论
connectionText: 已连接
```

## 7. 当前边界

本次只完成统一动作路由和动态动作展示，尚未完成：

- AI 自动完成非真人阶段并推进到下一次真人决策。
- 服务层 10 秒与 30 秒定时器。
- 浏览器刷新后的凭证恢复。
- 独立观战登录页面与死亡视角页面。

这些属于手册后续步骤，不写入已完成结论。
