# 10 月 31 日公网回归与手机端实测

日期：2026-10-31

执行人：Hurry

代码：远端 main `71d2854`（`docs: pin public URL to :8080 and refresh submission checklist`）

## 一、代码状态

```text
远端 origin/main : 71d2854（2026-10-30 19:55 北京时间）
本地工作区       : 4f3e59f，干净，无未提交与未跟踪文件
```

**任务单提到的「6 个已修改文件和 1 个未跟踪文件」不在我这台机器上**，本地 `git status` 为空。那批未提交内容应位于订书机本机，需他侧提交。

`git pull` 本轮持续失败：

```text
fatal: unable to access 'https://github.com/imdsj/wolfarena/': schannel: server closed abruptly
fatal: unable to access 'https://github.com/imdsj/wolfarena/': CONNECT tunnel failed, response 502
```

同一时刻 `api.github.com` 可访问，因此改用 API 下载 `main` 压缩包（`imdsj-wolfarena-71d2854/`）作为核对对象。**本地工作区仍停在 `4f3e59f`，网络恢复后需 `git pull` 同步。**

已核对：`71d2854` 与 `4f3e59f` 的 `backend/` 完全一致（`diff -rq` 无差异），差异仅在前端源码与文档。

## 二、全量测试

在 `71d2854` 快照上跑：

```text
python -m unittest discover -s tests
Ran 234 tests in 4.861s
OK
```

## 三、公网冒烟（任务单第 3 项）

命令与任务单一致：

```powershell
python deploy\smoke.py http://106.14.113.216:8080
```

输出：

```text
target: http://106.14.113.216:8080
health: ok {'status': 'ok', 'service': 'wolfarena-api', 'version': '0.6.0'}
home: ok bytes=557
create_room: ok status=201
  ws_player: ok (authenticated)
  ws_spectator: ok (authenticated)
ws_bad_token: ok (rejected)
ALL CHECKS PASSED
```

**判定：通过。** 相比 10-30 我手工探测，本轮脚本额外覆盖了两项：观战者身份认证、错误 token 被拒绝。

## 四、密钥扫描（任务单第 5 项）

对象：`71d2854` 快照全部文件。

| 检查项 | 结果 |
| --- | --- |
| `.env` / `*.key` / `*.pem` / `id_rsa*` | **0 个** |
| 硬编码密钥（`sk-…` / `ghp_…` / `AKIA…`） | **0 个文件命中** |
| 本机路径 `C:\Users\dings\…` | 14 处（订书机侧文档，未清） |
| 本机路径 `D:\传智杯\…` | 14 处（订书机侧文档，未清） |

我负责的三份 evidence 文档中的绝对路径已在前一日全部替换为占位符，本轮复查为 0。剩余 28 处均在 `docs/13`、`docs/14`、`docs/handoff/` 等交接材料中，改动会触及原表述，需订书机确认后再清理。

风险定级：低（用户名与目录结构，非凭据）。

## 五、浏览器更正：本机无 Chrome，实际使用 Edge

任务单多次要求「真实 Chrome 截图」。本轮核实：

```text
C:\Program Files\Google\Chrome\Application\chrome.exe       不存在
C:\Program Files (x86)\Google\Chrome\Application\chrome.exe 不存在
全盘检索 chrome.exe（D:\ 与 LOCALAPPDATA，深度 3）           无结果
C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe 存在（注册表确认）
```

**本机只有 Microsoft Edge，没有 Chrome。**

因此：

1. `deploy\m02-mobile.ps1` 直接报 `Chrome not found`，脚本只探测两个 Chrome 默认路径。
2. 10-28 的浏览器验收证据实际由 **Edge** 采集，此前文档误记为 Chrome，**已在 `2026-10-25_hurry_web_acceptance.md` 中更正并加说明**。

影响评估：Edge 与 Chrome 同为 Chromium 内核，DevTools 面板（网络 / 套接字 / 消息）与协议一致，所验的是服务端行为与页面渲染，**结论不受浏览器品牌影响**。但若评审明确要求 Chrome 专有材料，需在装有 Chrome 的机器上复采。

建议：订书机在演示机上确认是否装了 Chrome；若没有，所有材料里的「Chrome 验收」表述统一改为「Chromium 内核浏览器（Edge）」，避免与实际不符。

## 六、手机 M-02（任务单第 4 项）

启动器在本机不可用（缺 Chrome），改为用 Edge 等效执行：

```powershell
# 本地服务（71d2854 + 新构建前端）
python -m uvicorn backend.api:app --host 127.0.0.1 --port 8000

# 390×844 应用窗口
Start-Process msedge.exe -ArgumentList @(
  "--app=http://127.0.0.1:8000/",
  "--new-window",
  "--window-size=390,844",
  "--window-position=120,80"
)
```

窗口已按 390×844 打开，服务端确认可用（`/health` 200、页面 200、建房 201、座位 1）。

**操作与截图结果**：

```text
390×844 下创建房间：待填
完成一次发言：      待填
完成一次投票：      待填
是否出现横向滚动：  待填
截图路径：          待填
```

**说明**：M-02 需要真人点击完成发言与投票，脚本无法替代。在收到实际操作结果前，此项保持「进行中」，不写通过。

## 七、待订书机确认（任务单第 6 项）

| 项 | 状态 |
| --- | --- |
| 预指导是否已提交 | **未知**，需订书机给出回执 |
| 演示视频链接 | 仓库与文档中仍无地址 |
| 测试账号 | 系统免登录，需确认是否已在材料中说明 |
| 公网链接口径 | 已由 `71d2854` 固定为 `:8080`，需确认 PPT 与 README 一致 |

## 八、本轮未做的事

- 未修改 `backend/`、`frontend/` 任何业务代码。
- 未向公网服务写入持久数据（仅一次冒烟建房，房间随后过期）。
- 未改写 Git 历史。
- 未使用系统 Python。
