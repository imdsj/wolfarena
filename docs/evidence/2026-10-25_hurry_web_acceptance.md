# 2026-10-25 Web 入口与联机验收

对应清单：`docs/11_web_entry_acceptance_checklist.md`

状态：**待执行**（订书机完成最小入口后通知联调，本文件随之填写）

- commit：
- 浏览器与系统：
- 启动命令：
- 房间配置：
- 判定：Web 入口可用 / 不可用
- 通过项：
- 失败项与复现步骤：
- 阻塞项：
- 截图/日志：
- 下一修复动作：

---

## 一、20:00 判定：最小入口（W 组）

> 预检记录：2026-10-24 15:50 本机实测（Hurry），commit `6ae38e0`。订书机已实现 FastAPI + WebSocket 最小入口，以下为独立复核结果。

| 编号 | 判据 | 结果 | 证据 |
| --- | --- | --- | --- |
| W-01 | 后端能启动 | **通过**（`python -m uvicorn backend.api:app` 进程稳定） | 启动无致命错误 |
| W-02 | `/health` 返回 200 且响应可解析 | **通过**：`{"status":"ok","service":"wolfarena-api","version":"0.2.0"}` | 见下命令记录 |
| W-03 | 能创建房间，9 人（1 真人 + 8 AI） | **通过**：`POST /api/rooms` 返回 201，`players=9`、真人数 1、`phase=INIT`、`day=0`，返回 `room_id`/`player_token`/`spectator_password` | 见下 |
| W-04 | WebSocket 能连并收到阶段事件 | **通过**：`/ws/rooms/{id}` 认证后收到 `{"type":"authenticated",...}`，随后收到 `{"type":"snapshot","event_seq":9,...}` | 见下 |
| W-05 | 身份隔离：好人只看自己、狼人看狼队、观战者看全部 | **通过**（按修正后口径）：<br>好人 `seed=901`（hunter）→ `[('p1','hunter')]` 仅自己<br>狼人 `seed=904` → `[('p1','werewolf'),('p3','werewolf'),('p5','werewolf')]` 自己 + 2 队友<br>狼人 `seed=905` → `[('p1','werewolf'),('p2','werewolf'),('p4','werewolf')]` | 见下 |

判定：**Web 入口可用**（W-01 至 W-05 全部通过）。

### 环境注意（新人会踩）

首次在新机器上跑测试会报 `ModuleNotFoundError: No module named 'fastapi'`，必须先安装依赖：

```powershell
python -m pip install -r requirements.txt
```

安装前全量测试为 `110 tests, 2 errors`（两个测试模块因缺依赖无法导入）；安装后为 **`136 tests, OK`**。

### 命令记录

```powershell
# W-01 启动
python -m uvicorn backend.api:app --host 127.0.0.1 --port 8000

# W-02 健康检查
curl http://127.0.0.1:8000/health

# W-03 创建房间
POST /api/rooms
{"seed": 901, "human_count": 1, "max_humans": 3, "nickname": "测试真人"}
→ 201 {"room_id":"...","player_token":"...","spectator_password":"...","room":{...}}

# W-04 WebSocket
ws://127.0.0.1:8000/ws/rooms/{room_id}
→ send {"type":"authenticate","token":"..."}
← {"type":"authenticated", ...}
→ send {"type":"action","action":"start_night"}
← {"type":"snapshot","event_seq":9,...}

# W-05 身份可见性
GET /api/rooms/{room_id}  (Header: X-Player-Token)
查 visible_events 中 event_type=ROLE_ASSIGNED 的 target_id 与 data.role
```

### 实测发现的实现事实

- 身份**不在** `players` 数组里：`PublicPlayer` 只有 `player_id`/`seat`/`name`/`is_human`/`is_alive`。身份只出现在 `viewer.role`（自己）与 `visible_events` 的 `ROLE_ASSIGNED`（按可见性过滤）。
- 因此 W-05 的判定**必须查事件流**，查 `players[].role` 永远为空，会误判为「身份全部隐藏」。
- `max_humans` 默认值 3，取值范围 1 至 3（`ge=1, le=3`），与 GAME-004 一致，可用于 L-04c。
- 创建房间返回 `spectator_password`，每局独立，可用于 P-05「无万能密码」。

---

## 二、联机基础（L 组）

| 编号 | 判据 | 结果 | 证据 |
| --- | --- | --- | --- |
| L-01 | 双浏览器同房：房间号、座位表、当前阶段一致 | 待测 | |
| L-02 | 1 真人房补 8 个 AI | 待测 | |
| L-03 | 2 真人房补 7 个 AI | 待测 | |
| L-04 | 显式 `max_humans=2` 的房间拒绝第 3 名真人 | 待测 | |
| L-04b | 默认房间允许第 3 名真人、拒绝第 4 名 | 待测 | |
| L-04c | `max_humans` 传 1/3 接受，传 4/0 拒绝 | 待测 | |
| L-05 | 阶段同步在 2 秒内反映到另一窗口 | 待测 | |
| L-06 | 断线重连回到原座位、原阶段、保留自身视角 | 待测 | |
| L-07 | 满员房间加入被明确拒绝 | 待测 | |

失败项记录格式：

```text
编号：L-__
我做了什么：
我期望发生什么：
实际发生了什么：
完整报错或截图：
是否改变了游戏状态：是 / 否
```

---

## 三、权限与可见性（P 组）

| 编号 | 判据 | 结果 | 证据 |
| --- | --- | --- | --- |
| P-01 | 玩家 WebSocket 帧中无 `WOLF_SPEECH`、无他人 `role`、无夜间 `causes` | 待测 | |
| P-02 | 死亡后刷新、重连仍是玩家视角 | 待测 | |
| P-03 | 错误观战密码不进入观战 | 待测 | |
| P-04 | 正确密码进入上帝视角 | 待测 | |
| P-05 | 两局观战密码不同，无万能密码 | 待测 | |
| P-06 | 结束后公开身份、胜负、死因 | 待测 | |

P-01 抓包方法：

```text
开发者工具 → Network → WS → 选中连接 → Messages
筛选关键字：WOLF_SPEECH / role / causes
```

---

## 四、服务层计时（T 组，引擎测不到，只能在这里验）

| 编号 | 判据 | 结果 | 证据（时间戳） |
| --- | --- | --- | --- |
| T-01 | 自爆后不操作，约 10 秒自动关窗并进入下一夜 | 待测 | |
| T-02 | 窗口开放期间投票被拒绝 | 待测 | |
| T-03 | 发言 30 秒自动轮到下一位 | 待测 | |
| T-04 | 遗言 30 秒自动推进 | 待测 | |
| T-05 | 界面倒计时与服务端切换相差 ≤1 秒 | 待测 | |

T-01 记录格式：

```text
自爆触发时刻：
界面倒计时归零时刻：
实际阶段切换时刻：
服务端日志中的 close 调用时刻：
是否由服务端自动触发（而非人工点击）：是 / 否
```

---

## 五、移动端（M 组）

| 编号 | 判据 | 结果 | 证据 |
| --- | --- | --- | --- |
| M-01 | 390×844 下创建房间无横向滚动 | 待测 | |
| M-02 | 390px 下能完成发言与投票 | 待测 | |
| M-03 | 390px 下结算页信息不溢出 | 待测 | |

---

## 六、模型失败兜底（A 组）

| 编号 | 判据 | 结果 | 证据 |
| --- | --- | --- | --- |
| A-01 | 移除 API Key 后服务不崩，AI 降级为本地文案 | 待测 | |
| A-02 | 模型超时后对局不卡死 | 待测 | |
| A-03 | 非法 JSON 被拒并回退合法动作 | 待测 | |

---

## 七、降级路径（若 W 组未全通）

按清单第四节执行，当天仍要留下产出：

1. 引擎层补 `DAY_ANNOUNCEMENT → VOTE → 下一夜` 完整闭环用例。
2. L / P / T / M / A 各组标记**阻塞**，写明缺失接口。
3. 用固定 seed 全 AI 跑完整一局，导出事件序列作为单机演示材料。

降级时本文件对应填写：

```text
阻塞项：
  缺失依赖：
  预计补齐时间：
  对 10 月 30 日交付的影响：
```
