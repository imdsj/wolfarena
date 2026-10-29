# 模型卡 · l2.qtable.v1

## 基本信息

| 项 | 值 |
| --- | --- |
| 策略版本 | `l2.qtable.v1` |
| 类型 | 表格式 Q-learning（只学动作类别） |
| 文件 | `strategy_library/models/l2-qtable-v1.json`（18028 字节） |
| 内容哈希 | `3461404ed50f43b85e3d61a583e3d1e5b5af2e6a0ab07cba4dfe2f5f0c233572` |
| 文件 SHA-256 | `474f109d29e8d43e3d102fd8d1d73f3f7f1805f15f2c8d598ef2c25fe3d34dd4` |
| 训练提交 | `b1234e9` |
| 训练数据 | 自博弈模拟，seed `0`–`999`，1000 局 |
| 评估数据 | 自博弈模拟，seed `1000`–`1199`，200 局（与训练不重叠） |
| 状态数 / 状态-动作对 | 199 / 248 |
| 状态 | 自身角色、阶段、天数组、公开存活人数 |
| 动作 | 服务端 `legal_actions` 中的动作类型 |
| 目标/选项/发言 | 全部委派 L1 规则，不学习 |
| 奖励 | 终局：己方胜 +1、负 −1；中间步 0 |
| 超参数 | `alpha=0.2`、`gamma=0.95`、`epsilon 0.3→0.05` |

## 训练与评估结论

- 训练 1000 局稳定完成，无非法动作，|TD 误差| 下降 15%，但每座位平均
  终局奖励没有变好（−0.015 → −0.030）：**判为稳定、未收敛到提升**。
- 评估 200 局：好人胜率 31.5%，同 seed L1 为 36.5%，L0 为 84.0%。
  L2 未超过 L1，也没有证据支持“训练前后胜率提升”。
- 同模型同 seed 两次评估动作流哈希完全一致，可复现。

## 用途限制

- 只能作为“真实训练实验结果”保留与展示，**不得**用于宣传胜率提升。
- 不进入策略库默认检索集合（`strategy_library/seeds|validated` 均未收录）。
- 不进入 10-30 预成果演示主链；主链继续使用可解释的 L1 规则基线。
- 状态构造只使用自身可见信息；读取他人隐藏身份即视为缺陷，必须停止使用。
- 训练 seed 与评估 seed 严禁重叠；不得在评估 seed 上调参。

## 已知局限

- 状态极度离散（199 键），无法表达发言内容、票型和怀疑度。
- 九名 AI 共用一个 Q 表，角色与阵营信息只以自身角色维度体现。
- 终局稀疏奖励 + 同步自博弈导致价值基线漂移，Q 值在 ±1 区间震荡。
- 只学动作类别，真正的“选目标/组织发言”仍由 L1 规则决定，
  因此它不构成策略库自进化。

## 复现

```powershell
python -m backend.simulator --games 1000 --seed-start 0 --policy l2 `
  --out training_runs/train-l2-0000-0999 `
  --model-out strategy_library/models/l2-qtable-v1.json --commit b1234e9
python -m backend.simulator --games 200 --seed-start 1000 --policy l2 `
  --model-in strategy_library/models/l2-qtable-v1.json `
  --out training_runs/eval-l2-200 --commit b1234e9
```

详见 `docs/evidence/2026-10-29_l2_train_eval_200.md`。
