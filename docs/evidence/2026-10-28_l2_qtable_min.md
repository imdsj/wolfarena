# 最小 Q-learning 版本验收（`l2.qtable.v1`）

日期：2026-10-28

代码提交：`f911f4c`

模型文件：`training_runs/l2-train-20/model.json`（不入库）

模型内容哈希：`e59dc5b0ee14640355271bfe234ead337bd1fdaef1f346512ed30234011ea27b`

模型文件 SHA-256：`353743E565821BED68F5AC3792F99B842AB134E18B46217DA08A7284B4A347C1`

## 一、这一版做了什么

| 要素 | 实现 |
| --- | --- |
| 状态 | 自身角色、阶段、天数组、公开存活人数 |
| 动作 | 只从服务端 `legal_actions` 取动作类型 |
| 目标/选项/发言 | 沿用 L1 规则策略 |
| 奖励 | 终局胜方 +1、败方 -1，中间步骤 0 |
| 探索 | epsilon 从 0.3 线性降到 0.05 |
| 更新 | 一步 TD，`alpha=0.2`，`gamma=0.95` |
| 持久化 | JSON + `content_hash`，加载时校验 |
| 评估 | 加载后冻结为贪心，不再更新 |

状态只使用自身视角。测试 `test_other_players_hidden_roles_do_not_change_key`
证明修改他人角色不会改变状态键。

## 二、训练：20 局

```text
seed 范围：0 至 19
完成：20 / 20
动作：1357，合法率 100%
好人胜：11，狼人胜：9
平均步数：67.85
```

Q 表规模：

```text
状态数：133
状态-动作对：145
非零值：119
取值范围：-0.5343 至 0.4331
更新次数：1084
```

## 三、评估：独立 seed 20 局

```text
seed 范围：1000 至 1019
完成：20 / 20
动作：1489，合法率 100%
好人胜：5，狼人胜：15
平均步数：74.45
```

同 seed 的 L1 对照：

```text
好人胜：7，狼人胜：13
动作：1489，平均步数：74.45
```

两组动作数和平均步数完全相同，说明 20 局训练后 Q 表在这批状态上与 L1 的
动作优先级几乎没有分歧。**这不是提升证据，也不是退化证据**，只是说明样本量
远不足以区分两者。

## 四、可复现

评估跑两次，`actions.jsonl` 的 SHA-256 完全一致：

```text
44D6A446C1C1DF7C1860FA3EA49614D86C211FDCB0625FDC706515D0602B93A2
```

训练跑两次，模型文件 SHA-256 完全一致：

```text
353743E565821BED68F5AC3792F99B842AB134E18B46217DA08A7284B4A347C1
```

独立指标复算：训练、评估、L1 对照三组均为

```text
matches_summary = true
differences = []
```

## 五、命令

```powershell
python -m backend.simulator --games 20 --seed-start 0 --policy l2 `
  --out training_runs/l2-train-20 `
  --model-out training_runs/l2-train-20/model.json --commit f911f4c

python -m backend.simulator --games 20 --seed-start 1000 --policy l2 `
  --out training_runs/l2-eval-20 `
  --model-in training_runs/l2-train-20/model.json --commit f911f4c
```

## 六、不能说的事

- 不能说“训练后胜率提升”：评估 5/20 低于 L1 的 7/20，差异在噪声范围内。
- 不能说 G-06 已通过：还没有 200 局级别的训练前后同 seed 对照。
- 不能把 `l2.qtable.v1` 说成策略库自动进化：它只学习动作类别，目标仍由 L1 决定。
- 不能引用 `training_runs/` 原始日志当提交物：只提交本目录的 summary 与 manifest。

## 七、测试

```text
新增 tests/test_q_policy.py：18 项通过
全量：225 项通过
```
