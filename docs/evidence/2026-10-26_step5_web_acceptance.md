# 步骤 5 与 10 月 26 日网页验收记录

日期：2026-10-25（北京时间）

功能提交：`384986c`

证据提交：`184508a`

证据脱敏提交：`4547914`

后端版本：`0.4.0`

## 本轮实现

- 大厅增加房间号与观战密码入口，通过 WebSocket 首消息认证观战者。
- 玩家会话和观战会话持久化到浏览器本地；刷新后重新认证并恢复座位、身份、
  当前阶段、事件和 WebSocket。
- 观战者显示上帝视角，页面不渲染玩家动作；服务端仍独立拒绝观战动作。
- 死亡玩家只显示“已出局”提示，不转换身份，不显示上帝视角；服务端可见事件
  仍由原有过滤逻辑决定。
- 九人席位表只使用当前视角已经收到的 `ROLE_ASSIGNED` 和 `PLAYER_DIED` 事件。
- 目标动作只列出服务端动作目录中的存活目标；文本动作显示文本框。
- 动作卡片通过 WebSocket 提交，服务器拒绝原因显示在页面错误区。
- 赛后显示胜方、九名玩家身份和当前视角可见的死因。
- 修复自爆窗口截止前提前显示“关闭窗口”动作的问题。关闭动作现在只在达到
  服务端截止时间后进入动作目录。

## 自动化结果

```text
命令：.\.venv\Scripts\python.exe -m unittest discover -s tests -q
结果：Ran 177 tests in 1.112s
结论：OK
```

```text
命令：npm run build
结果：TypeScript 检查通过，Static Vue build written to frontend\dist
```

```text
命令：Invoke-RestMethod http://127.0.0.1:8010/health
结果：{"status":"ok","service":"wolfarena-api","version":"0.4.0"}
```

全流程 DOM 运行时验收：

```text
初始阶段：INIT
真人身份：村民
经历阶段：INIT、SELF_DESTRUCT、END
服务器错误显示：当前玩家不能执行动作：vote
最终阶段：END
终局席位数：9
刷新恢复阶段：END
刷新后 WebSocket：已连接
错误观战密码：观战密码错误
观战模式：上帝视角
观战动作卡：0
观战只读提示：存在
观战可见 WOLF_SPEECH：是
视口：390×844
整轮耗时：约 10.6 秒
```

该验收从真实 Vue DOM 发出建房 HTTP 请求，通过真实 WebSocket 提交动作，并由
实际 FastAPI 服务和规则引擎推进到 `END`。测试请求注入固定 seed 以复现流程；
生产页面仍由服务端生成实时房 seed。

双客户端同步：

```text
房主阶段：NIGHT_WOLF_DISCUSSION_R1
加入者阶段：NIGHT_WOLF_DISCUSSION_R1
相同阶段：是
相同 event_seq：是
双方均收到服务器事件：是
```

视角组件：

```text
观战者上帝视角：是
观战者只读提示：是
观战者动作卡：0
死亡玩家提示：是
死亡玩家指标显示已出局：是
死亡玩家出现观战提示：否
死亡目标从下拉框隐藏：是
存活目标显示：是
文本动作输入框：是
```

## 验收矩阵

| 编号 | 状态 | 真实证据 |
| --- | --- | --- |
| W-01 至 W-05 | 通过 | 健康检查、建房、WebSocket、身份隔离和既有 Web 测试 |
| A-01 | 通过 | 一名真人从 INIT 经真实 API/WebSocket 到 END，终局 9 人 |
| A-02 | 通过 | 177 项测试；17 个动作在等待玩家 INIT 状态下全部被拒绝 |
| A-03 | 通过 | 确定性截止测试、超时广播测试；本轮真实 10 秒自爆窗口自动推进 |
| A-04 | 功能通过，视觉待补 | 两个独立 WebSocket 客户端阶段和 event_seq 一致；未生成真实双 Chrome 录屏 |
| A-05 | 功能通过，真实截图待补 | 错误/正确观战密码、只读视角、死亡视角、刷新重连均验证 |
| A-06 | 部分通过 | 390×844 DOM 状态快照已生成；真实 Chrome 截图未通过当前沙箱 |
| A-07 | 通过 | 模型超时、非法 JSON、非法结构和无 Key 兜底测试通过 |

## 390px 证据边界

状态快照位于：

```text
docs/evidence/browser-2026-10-26/390-lobby.html
docs/evidence/browser-2026-10-26/390-player-in-progress.html
docs/evidence/browser-2026-10-26/390-player-end.html
docs/evidence/browser-2026-10-26/390-spectator-end.html
```

对应 PNG 由 Windows 旧版 WebBrowser 控件生成，只用于检查内容存在和基本宽度，
不能代表现代 Chrome 的 Grid/Flex 排版，不能据此声称 A-06 已完整通过。

当前沙箱阻止 Chrome 启动 Mojo/信号管道进程，因此仍缺失：

1. 真实 Chrome 两窗口并排录屏。
2. 真实 Chrome 390×844 创建、发言、投票、结算截图。

这两项必须在允许启动浏览器进程的普通桌面环境中补录。功能自动化结果、静态
DOM 快照和旧渲染器图片不得替代上述视觉验收。

## Git

```text
功能提交：384986c
提交说明：feat: complete spectator and web game flow
证据提交：184508a
脱敏提交：4547914
```

当前环境仍不能写 E 盘仓库 `.git`，提交通过临时 Git 元数据完成；推送后必须用
远端 `refs/heads/main` 核对哈希，不能在本地旧 HEAD 上重复提交。
