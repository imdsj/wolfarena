# 2026-10-23 核心规则与 Agent 基线

日期：2026-10-23

本记录对应 2026-10-23 结束前的规则、夜间引擎和 AI 成长基线。

## 1. Git 基线

| 项目 | Commit |
| --- | --- |
| 当日开发前基线 | `394fabf` |
| Hurry 验收用例 | `779e116` |
| Hurry 环境记录 | `15b4946` |
| Hurry 阶段边界测试 | `f8570bc` |
| Hurry 成长测试表 | `b24b516` |
| GAP-08 修复 | `d6a5a9d` |
| 阶段与事件模型 | `54e0f94`、`8ef8fab` |
| 夜间动作与结算 | `5488ba9`、`ed15a9d` |
| AI 成长与 L0 | `140d650`、`629e1c7` |

Hurry 的四个提交均已进入当前 `main` 历史。

## 2. 验证结果

执行：

```powershell
python -m unittest discover -s tests -v
```

结果：

```text
Ran 69 tests in 0.008s

OK
```

同时执行：

```powershell
python -m compileall backend tests
git diff --check
git status --short --branch
```

结果：

- Python 编译检查通过。
- `git diff --check` 无输出。
- 工作区干净。
- 审计开始时，本地 `main` 与 `origin/main` 均指向 `629e1c7`。

当前 Codex 终端直接运行 `git ls-remote origin refs/heads/main` 时被 Git Credential Manager 登录提示阻断，错误为 `could not read Username for 'https://github.com'`。本地远程跟踪分支与远端推送结果一致，但在其他终端重新执行 `ls-remote` 后应再次确认。

## 3. 已完成规则

| 规则主题 | 状态 | 证据 |
| --- | --- | --- |
| GAP-08 真人数量边界 | 已完成 | 0 与 1 至 3 成功，4 至 9 拒绝 |
| 15 个细分阶段 | 已完成 | `PHASE_ORDER` 与枚举唯一性测试 |
| 13 个规则事件 | 已完成 | `EventType` 覆盖规则第 9 章 |
| 事件连续序号 | 已完成 | `append_event` 与序列测试 |
| 玩家、狼队、观战者可见性 | 已完成 | `get_visible_events` 与服务端过滤测试 |
| 狼队长选择 | 已完成 | 全 AI 可复现、单真人自动、多真人手动 |
| 两轮狼人发言 | 已完成 | 座次、轮次、阶段和身份校验 |
| 狼刀、空刀、自刀 | 已完成 | 队长唯一提交与目标存活校验 |
| 预言家查验 | 已完成 | `wolf`/`good` 结果和私有可见性 |
| 女巫用药 | 已完成 | 两药各一次、同夜单药、任意存活目标 |
| 女巫刀口可见性 | 已完成 | 有解药可见，解药耗尽或空刀不可见 |
| 夜间死亡合并 | 已完成 | 狼刀与毒药合并、多个死因单一事件 |
| 死亡原因保护 | 已完成 | 玩家隐藏、观战可见、结束后揭示 |
| 猎人夜间开枪资格 | 已完成 | 狼杀可进入 `NIGHT_HUNTER_SHOT`，被毒不可 |
| 胜负检查 | 已完成 | 夜间死亡结束后检查并写入胜者事件 |
| AI 成长数据结构 | 已完成 | `GrowthStage`、`DecisionRecord`、`StrategyRecord` |
| L0 新手策略 | 已完成 | 不调用外部模型，仅从合法动作中选择 |

## 4. 当前未完成

| 项目 | 状态 |
| --- | --- |
| 夜间猎人实际选目标并开枪 | 未实现 |
| `DAY_ANNOUNCEMENT` 后的完整白天流程 | 未实现 |
| 公开发言、投票、弃权、放逐 | 未实现 |
| 自爆与 10 秒窗口 | 未实现 |
| 白天猎人开枪与遗言顺序 | 未实现 |
| 前端页面、WebSocket 和计时器 | 未实现 |
| DeepSeek 与 RAG | 未实现 |
| 200 局训练场与模型指标 | 未实现 |

## 5. 阻塞项

GT-01 至 GT-08 的 200 局成长对比标记为**阻塞**。

阻塞原因：

1. 完整对局尚未闭环。
2. 投票、自爆和白天流程尚未实现。
3. 结构化动作日志尚未导出为训练数据。
4. 策略版本切换和批量模拟入口尚未实现。

本记录不包含胜率、策略提升幅度或虚构训练数据。

## 6. 安全与文件检查

```powershell
git ls-files .env
git grep -n -I -E "sk-[A-Za-z0-9]|BEGIN (RSA|OPENSSH|EC) PRIVATE KEY"
git status --ignored --short
```

结果：

- `.env` 未被 Git 跟踪。
- 未发现真实 API Key 或私钥特征。
- `.env`、`backend/__pycache__/` 和 `tests/__pycache__/` 均为忽略状态。
- `.gitattributes` 已存在并跟踪，包含 `* text=auto`，`.py` 和 `.md` 固定使用 LF。

## 7. 交接与次日第一件事

Hurry 的四个提交已确认进入历史。外部聊天发送和联调时间确认需要在团队聊天中由项目负责人完成，本记录不能代替实际发送。

次日第一件事：实现 `NIGHT_HUNTER_SHOT` 的实际开枪目标与结算，然后完成 `DAY_ANNOUNCEMENT` 后的白天流程。只有完整一局可以自动跑通并导出动作日志后，才开始 GT-01 至 GT-08 的 200 局成长对比。
