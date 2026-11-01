# 训练证据展示报告 · 2026-11-01

本报告只整理已有训练结果，不重新训练、不调参、不修改正式模型。
结论是负结果：**L2 没有超过 L1，G-06 维持 No-Go**。

## 1. 训练命令与 seed 范围

### 1.1 正式实验（已入库的证据）

| 批次 | 训练 seed | 局数 | 模型文件 | 评估 seed | 评估局数 |
| --- | --- | ---: | --- | --- | ---: |
| L2 v1 | 0–999 | 1000 | `strategy_library/models/l2-qtable-v1.json` | 1000–1199 | 200 |
| L2 v2 | 0–999 | 1000 | `strategy_library/models/l2-qtable-v2.json` | 1000–1199 | 200 |

```powershell
python -m backend.simulator --games 1000 --seed-start 0 --policy l2 `
  --out training_runs/train-l2-0000-0999 `
  --model-out strategy_library/models/l2-qtable-v1.json --commit b1234e9

python -m backend.simulator --games 200 --seed-start 1000 --policy l2 `
  --model-in strategy_library/models/l2-qtable-v1.json `
  --out training_runs/eval-l2-200 --commit b1234e9
```

### 1.2 本次演示批次（commit `71d2854`）

演示只用 20 局，目的是证明训练管线能真实运行；**不覆盖正式模型**，
seed 也与正式评估（1000–1199）完全分开。

| 批次 | seed | 局数 | 输出目录 |
| --- | --- | ---: | --- |
| 训练 | 2000–2019 | 20 | `training_runs/train-demo-20` |
| 评估 | 3000–3019 | 20 | `training_runs/eval-demo-20` |

```powershell
$sha = "71d2854"
python -m backend.simulator --games 20 --seed-start 2000 --policy l2 `
  --out training_runs/train-demo-20 `
  --model-out training_runs/train-demo-20/model.json --commit $sha

python -m backend.simulator --games 20 --seed-start 3000 --policy l2 `
  --model-in training_runs/train-demo-20/model.json `
  --out training_runs/eval-demo-20 --commit $sha

python -m backend.metrics --run training_runs/eval-demo-20
```

实测结果：

| 指标 | 训练批次 | 评估批次 |
| --- | ---: | ---: |
| 完成 / 总局数 | 20 / 20 | 20 / 20 |
| 失败局 | 0 | 0 |
| 动作合法率 | 100% | 100% |
| 好人胜 / 狼人胜 | 10 / 10 | 5 / 15 |
| 平均步数 | 63.0 | 74.85 |
| code_commit | `71d2854` | `71d2854` |

演示模型：`l2.qtable.v2`，schema 2，192 个状态、202 个状态-动作对，
内容哈希 `e119332e70b79f40…`，文件 SHA-256 `2a087c21402b6203…`。
正式模型未被覆盖：v1 仍为 `474F109D…D34DD4`，v2 仍为 `266A1071…C0B1B7`。

## 2. 好人胜率对比（seed 1000–1199，各 200 局）

| 策略 | 好人胜 | 狼人胜 | 好人胜率 | 平均步数 |
| --- | ---: | ---: | ---: | ---: |
| L0 随机 | 168 | 32 | 84.0% | 43.595 |
| L1 人工规则 | 73 | 127 | 36.5% | 77.015 |
| L2 v1（Q 表） | 63 | 137 | 31.5% | 72.955 |
| L2 v2（扩展状态） | 70 | 130 | 35.0% | 73.485 |

四个版本使用同一组评估 seed、同一套规则引擎、同一动作校验；
失败局单列，本次四批均为 0。

对应 manifest（可复算）：

- `docs/evidence/2026-10-29_l0-200_manifest.json`
- `docs/evidence/2026-10-29_l1-200_manifest.json`
- `docs/evidence/2026-10-29_l2-200_manifest.json`
- `docs/evidence/2026-10-29_l2-v2-200_manifest.json`

## 3. 为什么 L2 没有超过 L1，以及为什么这是真实负结果

**结果本身**：v1 31.5%、v2 35.0%，都低于 L1 的 36.5%。v2 比 v1 好 3.5
个百分点，但仍没追上规则基线；200 局下 3–10 局的差距属于噪声范围，
不能据此宣称任何提升。

**结构性原因**：

- 状态过于离散：v1 只有 199 个状态，v2 也只有 489 个，
  无法表达发言内容、票型细节和怀疑度。
- 奖励只有终局胜负，中间步骤为 0，信号极稀疏。
- 九名 AI 共用一个 Q 表，角色差异只能靠自身角色维度部分区分。
- 只学动作类别，目标、选项和发言仍由 L1 规则决定，
  因此它不构成策略自进化。
- 训练与评估是不同 seed 段，规则对手在训练中同步变化，
  价值基线本身在漂移。

**为什么保留负结果**：这套实验的每一步都可复现——固定 seed、可重新加载
的模型文件、内容哈希校验、可从原始日志复算的指标。它证明的是
“训练管线真实跑通并如实报告”，不是“训练后变强”。

## 4. 评委可复现的复算命令

```powershell
# 1) 模型完整性与哈希
python -c "from backend.q_policy import QTablePolicy; from pathlib import Path; \
p=QTablePolicy.load(Path('strategy_library/models/l2-qtable-v2.json')); \
print(p.strategy_id, p.content_hash)"

# 2) 从原始日志复算正式评估指标
python -m backend.metrics --run training_runs/eval-l2-v2-200
python -m backend.metrics --run training_runs/eval-l1-200
python -m backend.metrics --run training_runs/eval-l0-200

# 3) 重跑演示批次（独立 seed，不覆盖正式模型）
python -m backend.simulator --games 20 --seed-start 2000 --policy l2 `
  --out training_runs/train-demo-20 `
  --model-out training_runs/train-demo-20/model.json --commit 71d2854
python -m backend.simulator --games 20 --seed-start 3000 --policy l2 `
  --model-in training_runs/train-demo-20/model.json `
  --out training_runs/eval-demo-20 --commit 71d2854
python -m backend.metrics --run training_runs/eval-demo-20
```

每次 `backend.metrics` 都应输出 `matches_summary: true` 与空的 `differences`。
