# 本地策略库基础验收

日期：2026-10-27

代码提交：`25e95e8`

## 目录边界

```text
strategy_library/
  seeds/        团队种子，可被默认检索
  candidates/   AI 候选，gitignored，默认不可检索
  validated/    固定 seed 评测和人工确认后晋升
  rejected/     淘汰或来源不明策略，gitignored
```

种子策略 33 条，覆盖：

- 狼人刀神职与保护深水位。
- 预言家避免重复查验和处理对跳。
- 女巫解药、毒药的基础风险规则。
- 猎人开枪与空枪的风险判断。
- 村民分析发言、票型和预言家冲突。

所有种子策略的 `samples=0`、`win_rate=null`、`interval=null`。它们只是团队战术
假设，不是“高胜率已验证战术”。

## 检索

```powershell
python -m backend.strategy_library `
  --root strategy_library `
  search --role werewolf --phase NIGHT_WOLF_KILL --query 神职
```

默认只加载 `seed` 与 `validated`。即使候选文件命中关键词，也不会进入正式检索。

运行时只读取本地 JSON，不发起网络请求。外部网页资料只能在离线整理后作为一个
带来源字段的候选或种子文件进入。

## 候选与晋升

AI 候选：

```powershell
python -m backend.strategy_library `
  --root strategy_library `
  add-candidate --file candidate.json
```

候选必须：

- `status=candidate`
- 不填写未经评测的胜率
- 不与 seed/validated/candidate 中的 ID 重复

晋升必须提供：

- 非 AI 人工审核者
- 明确的 baseline/candidate 策略版本
- 同一固定 seed 范围
- 至少 200 局
- 两份 manifest SHA-256
- 审核说明

候选晋升后会从 `candidates/` 移入 `validated/`，之后才进入默认检索。

## 测试

```text
Python：207 tests OK
```

策略库测试覆盖：

- seed 可检索。
- candidate 默认不可检索。
- 候选不能覆盖已有 seed ID。
- 候选不能填写未验证胜率。
- 200 局且人工审核后才能晋升。
- AI 作为审核者会被拒绝。
- 小样本晋升被拒绝。

## 当前限制

已实现的是本地策略库和受控候选入口。尚未实现：

- LLM 在赛后自动总结候选战术。
- 向量数据库和语义检索。
- 对局中自动调用策略检索。
- 策略级胜率统计和自动评测流水线。
- 联网资料抓取。

因此不能宣称 AI 已经会自主学习新战术。下一步需要把比赛事件复盘、策略候选
生成、固定 seed 评测和页面证据展示串成闭环。
