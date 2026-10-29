# 10 月 28 日安全快照与提交验收

日期：2026-10-28

最终代码提交：`25e95e8`

最终快照提交：`5f59c83`

## 一、Git 同步结论

开始时远端 `main`：

```text
00a8ba5
```

远端包含以下我们及队友的提交：

```text
00a8ba5 test: record the real Chrome acceptance run
18fa9a1 test: verify commit state and re-run training evidence
9add0e4 test: record the 10-26 web acceptance run done on 10-27
466aa02 test: record independent training ground go/no-go decision
fe9cb29 docs: align simulator evidence with final test count
```

祖先关系检查：

```text
0f01afe 是 main 祖先：是
9c3cf41 是 main 祖先：是
```

因此“证据 commit 不存在”来自旧本地视图，不是远端对象缺失。没有执行
`git reset --hard`、`git checkout --` 或强制推送，也没有改写历史。

当前远端 `main`：

```text
5f59c83e8cd840707916b2b230bb91cebdce3a68
```

标签：

```text
v0.9.22-28-safe-snapshot
```

## 二、测试和构建

```text
Python：207 tests OK
前端：TypeScript 检查和静态构建通过
健康检查版本：0.6.0
```

本轮在 E 盘原始仓库内直接使用 `.venv` 运行成功。旧附件中“只能复制到可写目录
才能通过”的描述未在本轮复现；测试目录权限问题不代表业务断言失败。

## 三、文件分类

代码和受控资产：

```text
backend/
frontend/
tests/
strategy_library/seeds/
strategy_library/candidates/.gitkeep
strategy_library/validated/.gitkeep
strategy_library/rejected/.gitkeep
```

证据：

```text
docs/evidence/
docs/14_AI完整交接说明书_2026-10-25.md
docs/handoff/
```

保持忽略：

```text
.env
training_runs/
缓存和构建中间产物
AI 候选与淘汰策略正文
```

训练原始 L0/L1 记录保留在本地：

```text
training_runs/l0-200/
training_runs/l1-200/
training_runs/repeat-a/
training_runs/repeat-b/
training_runs/l1-repeat-a/
training_runs/l1-repeat-b/
```

## 四、策略库

种子策略由 12 条扩充到 33 条，全部 `win_rate=null`，没有伪造已验证胜率。

```text
seed 文件：33
唯一 strategy_id：33
默认可检索：seeds + validated
默认不可检索：candidates + rejected
```

AI 候选仍只能自动进入 `candidates/`。正式晋升要求 200 局固定 seed 评测、
manifest 哈希和非 AI 审核者。

## 五、训练证据重跑

用 `25e95e8` 重跑 L0/L1 各 200 局（2026-10-28 晚已用 `b2a8d89` 再次重绑，
见 `2026-10-28_evidence_rebind.md`）：

```text
L0：200/200 完成，8719 个动作，合法率 100%
L1：200/200 完成，15403 个动作，合法率 100%

L0：好人 168，狼人 32
L1：好人 73，狼人 127
```

两项独立指标复算均为：

```text
matches_summary = true
differences = []
```

固定 seed 1033 的 L0/L1 actions SHA-256 与 replay_sha256 在两次运行中一致。
manifest 已绑定 `25e95e8`。

## 六、安全边界

- 未发现真实 API Key 或私钥模式。
- `.env` 未被 Git 跟踪。
- 观战密码没有写入公开证据。
- 训练原始文件没有提交。
- 本轮没有把 L1 称为训练版，也没有生成训练前后提升结论。

## 七、当前待办

1. 真实 Chrome 截图/录屏文件需要从 Hurry 的本地证据目录纳入正式提交流程；
   当前文字验收显示双窗口、同步、赛后揭示已人工通过，但仓库仍缺原始媒体。
2. 策略库已验证目录仍为空。
3. 公网演示地址和评审账号未确认。
4. Q-learning 训练版、模型卡和 G-06 对照尚未开始。
