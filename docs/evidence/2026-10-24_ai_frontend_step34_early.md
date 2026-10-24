# 10 月 25 日 DeepSeek 与最小前端任务提前执行证据

实际执行日期：2026-10-24

执行范围：步骤 3 DeepSeek 适配与离线兜底，步骤 4 Vue 最小前端入口。

## 1. DeepSeek 安全边界

模型输入只来自 `RoomSnapshot`：当前玩家可见的玩家列表、事件、阶段、日期，
以及服务端给出的 `legal_actions` 和 `valid_target_ids`。

模型输出先经过 Pydantic `CandidateAction` 校验，再由 API 检查：

- 动作必须存在于当前 `legal_actions`。
- 目标必须为空或存在于 `valid_target_ids`。
- 通过后才调用规则引擎的 `start_night`。
- 模型没有权限直接修改 `GameState`。

API：

```text
POST /api/rooms/{room_id}/ai-action
X-Player-Token: 玩家凭证
```

## 2. 失败与降级

| 失败场景 | 已验证行为 |
| --- | --- |
| 没有 API Key | 不发起网络请求，使用本地 `start_night`，记录 `AI_FALLBACK_USED` |
| 超时或网络错误 | 同一请求最多重试一次，然后兜底，游戏继续推进 |
| 非法 JSON | 只发起一次修复请求；仍失败则兜底 |
| Pydantic 拒绝 | 多余字段或错误结构不得进入规则引擎 |
| 非法动作 | 返回 `AI_ACTION_INVALID`，阶段不变，记录 `AI_ACTION_REJECTED` |
| 非法目标 | 返回 `AI_TARGET_INVALID`，阶段不变，记录 `AI_ACTION_REJECTED` |

测试全部使用 `httpx.MockTransport` 固定假响应，没有调用真实 DeepSeek。
测试同时检查日志中不包含 `Authorization` 或测试密钥。

## 3. 自动化验证

后端：

```text
Ran 148 tests
OK
```

前端：

```text
vue-tsc --noEmit -p tsconfig.app.json
node scripts/build-static.mjs
node --check <每个编译后的模块>
node scripts/client-smoke.mjs
```

以上检查全部通过。`client-smoke.mjs` 使用 Happy DOM 挂载编译后的 Vue
应用，并连接真实的 FastAPI HTTP/WebSocket。实际结果：

```text
createdPhase: 等待开始
phaseAfterAction: 首夜狼队讨论
fallbackNotice: 已使用离线兜底（missing_api_key）
connectionText: 已连接
hasFallbackEvent: true
hasNightStartedEvent: true
```

这证明页面能创建房间、完成 WebSocket 认证、显示真实连接状态、调用 AI
接口、接收兜底和新阶段事件并更新界面。

静态构建产物包括：

```text
dist/index.html
dist/src/main.js
dist/src/App.js
dist/src/components/*.js
dist/src/styles.css
dist/vendor/vue.esm-browser.prod.js
```

FastAPI 实际托管静态页面后，以下路径均返回 HTTP 200：

```text
/
/src/main.js
/src/App.js
/src/styles.css
/vendor/vue.esm-browser.prod.js
/health
```

## 4. 真实服务冒烟

服务版本为 `0.3.0`。在没有 DeepSeek Key 的独立进程中：

1. 创建九人房间。
2. WebSocket 首消息认证。
3. 调用 `/api/rooms/{room_id}/ai-action`。
4. 实际收到 `AI_FALLBACK_USED` 和 `NIGHT_STARTED`。
5. 阶段从 `INIT` 推进到 `NIGHT_WOLF_DISCUSSION_R1`。

访问日志未记录玩家 Token、API Key 或请求头。

## 5. Vue 页面

页面包含：

- 昵称创建房间。
- 房间号与昵称加入房间。
- 真人/AI 人数、当前阶段、本人身份和座位。
- WebSocket 的认证、快照、事件、阶段和断线状态。
- 房主直接开始首夜。
- “AI 推荐并执行”和来源/兜底提示。
- 服务器事件列表，按 `event_seq` 去重并排序。
- 390px 窄屏响应式规则。

开发模式使用 Vite 代理；生产/演示模式由 FastAPI 托管 `frontend/dist`。

## 6. 视觉验证边界

当前 Codex Windows 进程沙箱禁止 Chrome/Playwright 启动浏览器子进程，因此本轮
不能把真实浏览器像素截图误记为通过。页面源码、DOM 挂载、按钮点击、
TypeScript、静态编译模块、静态资源响应和真实 API/WebSocket 已经验证；
移动端视觉效果仍需手动目检。

服务已在 `http://127.0.0.1:8010/` 启动，供项目负责人手动做最终视觉检查。

## 7. 房间号大小写修复

联合验收时发现页面样式把混合大小写的房间号显示成全大写，但服务端房间号
区分大小写，导致第二窗口按屏幕文字加入时返回 `ROOM_NOT_FOUND`。

修复后：

- 房间号保留服务端原始大小写，并使用等宽字体显示。
- 房间页提供“复制房间号”按钮。
- 加入输入框关闭自动大写和拼写检查。
- DOM 冒烟测试确认显示值与服务端一致。
- 精确房间号加入返回 200；强制全大写加入返回 404。

联合验收还发现：第二窗口加入成功后，第一窗口虽然收到 `PLAYER_JOINED`，
但人数仍停留在 1/8。原因是状态变化广播包含事件和新阶段，却没有包含更新后的
房间快照。修复后每位已认证连接会依次收到可见事件、新阶段和按本人权限过滤的
最新快照；DOM 冒烟验证第一窗口会无需刷新更新为 2/7。
