# 10 月 25 日 Web 入口任务步骤 1 提前执行证据

实际执行日期：2026-10-24

执行范围：步骤 1，最小后端接口与内存房间仓库。

代码提交：`aed2e06`

## 1. 环境

- 操作系统：Windows
- Python：3.14.7
- 虚拟环境：仓库根目录 `.venv`，已确认不进入 Git
- FastAPI：0.162.0
- Uvicorn：0.54.0
- HTTP 测试客户端：httpx 0.28.1
- 依赖清单：`requirements.txt`

## 2. 自动化验证

执行命令：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

结果：

```text
Ran 122 tests
OK
```

其中原有规则引擎和成长数据测试 108 项，最小 Web 入口测试 14 项。

编译和工作区检查：

```powershell
.\.venv\Scripts\python.exe -m compileall backend tests
git diff --check
```

结果：无语法错误，无空白错误。

## 3. 实际服务验证

启动命令：

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.api:app --host 127.0.0.1 --port 8765
```

实际请求结果：

```text
HealthStatus: ok
Service: wolfarena-api
Phase: INIT
Players: 9
HumansAfterCreate: 1
ViewerRole: 返回且只出现在 viewer 对象
RoleFieldsInPlayerList: 0
HumansAfterJoin: 2
SecondSeat: 2
```

创建房间后，公开玩家列表为 9 人，其中 1 真人、8 AI。第二名真人通过加入接口领取预留或 AI 席位，房间当前真人数量变为 2。

## 4. W 组当前状态

| 编号 | 状态 | 依据 |
| --- | --- | --- |
| W-01 | 通过 | Uvicorn 进程正常启动并响应请求 |
| W-02 | 通过 | `/health` 返回 200，响应可解析，不包含密钥或服务器路径 |
| W-03 | 通过 | 创建房间返回 9 人，1 真人、8 AI |
| W-04 | 待步骤 2 | WebSocket 尚未实现 |
| W-05 | API 层通过，WebSocket 层待验 | `players` 不含 `role`，`viewer` 只返回本人角色；狼人按正式规则额外看到狼队友事件 |

因为 W-04 尚未实现，今天 20:00 的 W 组目前仍不能整体判定为通过。

## 5. 接口边界

- `human_count` 表示创建时预留的真人席位数量，范围 1 至 3。
- `max_humans` 默认 3，范围 1 至 3，且不得小于 `human_count`。
- 创建者领取第 1 个真人席位。
- 加入请求先领取预留真人席位，再按座次把 AI 席位转为真人。
- 默认房间允许最多 3 名真人；显式 `max_humans=2` 时第 3 名真人被拒绝。
- 玩家凭证使用 `X-Player-Token` 请求头，不放入 URL 查询参数。
- 房间数据仅保存在当前进程内，服务重启清空。

## 6. 下一步

实现 WebSocket：

1. 玩家使用房间号和 `X-Player-Token` 等价凭证连接。
2. 连接后 5 秒内发送包含当前 `phase` 的事件。
3. 以每名玩家的过滤后视角广播，不把原始事件列表直接发送给所有连接。
4. 用两个连接验证同房间、同阶段和不同身份信息。
