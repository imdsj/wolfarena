# WolfArena 本地策略库

策略文件使用 JSON，由 `backend.strategy_library.StrategyLibrary` 读取。

## 目录

```text
seeds/       团队整理并提交的种子策略，可被默认检索
candidates/  AI 从复盘或离线资料提出的候选策略，不参与默认检索
validated/   通过固定 seed 评测和人工审核的策略，可被默认检索
rejected/    低于基线、来源不明或未通过审核的策略
```

## 安全边界

- 运行时只读本地文件，不联网搜索。
- 网页资料必须先离线整理并写入带来源的 JSON，才可进入候选或种子库。
- AI 只能自动新增 `candidate`。
- `promote` 至少要求 200 局、同一 seed 范围的新旧策略评测，以及非 AI
  审核者确认。
- 未验证策略不得填写胜率或置信区间。
- 种子策略的胜率为空，只表示战术假设，不表示真实效果。

## 必填字段

每张策略卡都必须写全下列内容，缺任意一项都会被模型校验拒绝：

| 字段 | 要求 |
| --- | --- |
| `source_type` / `source` | 来源类型与可追溯来源路径或说明 |
| `phase` | 适用阶段，必须是 `backend.game_engine.PHASE_ORDER` 中的值或 `ANY` |
| `trigger` | 触发条件 |
| `action` / `recommendation` | 动作类别与具体建议 |
| `risk` | 该策略失效或被反向利用时的风险 |
| `evidence_level` | `untested`、`rule_derived`、`simulated`、`human_validated` 之一 |
| `status` | `seed`、`candidate`、`validated`、`rejected` |

当前 33 条种子策略全部为 `evidence_level=rule_derived`、`samples=0`、
`win_rate=null`：它们来自规则文档与团队讨论，尚未取得模拟或真人样本证据。
任何策略ID重复写入都会抛 `StrategyError`，不允许覆盖已有卡片。

## 命令

```powershell
python -m backend.strategy_library `
  --root strategy_library `
  search --role werewolf --phase NIGHT_WOLF_KILL --query 神职
```

```powershell
python -m backend.strategy_library `
  --root strategy_library `
  add-candidate --file path/to/candidate.json
```

```powershell
python -m backend.strategy_library `
  --root strategy_library `
  promote --strategy-id candidate.example `
  --evidence path/to/evaluation.json
```
