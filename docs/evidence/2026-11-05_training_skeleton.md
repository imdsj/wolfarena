# 训练场骨架与胜率 rollout · 2026-11-05

今天不训练，只搭接口、写算法、出文档。正式 L3 训练 11 月 8 日再开始。

## 1. 模型注册表（固定 ID）

`GET /api/training/models` 返回四个固定 ID，非法 ID 返回 404：

| model_id | policy | strategy_id | 状态 |
| --- | --- | --- | --- |
| `l0.random.v1` | l0 | `l0.random.v1` | baseline |
| `l1.rules.v1` | l1 | `l1.rules.v1` | baseline |
| `l2.qtable.v1` | l2 | `l2.qtable.v1` | No-Go |
| `l2.qtable.v2` | l2 | `l2.qtable.v2` | No-Go |

## 2. 指标接口

`GET /api/training/metrics` 返回每个模型的 seed 范围、样本数、好人/狼人胜场、
好人胜率、动作合法率、绑定 commit 和 `no_go` 标记。数字来自已冻结的 200 局
证据（`docs/evidence/2026-10-29_*_summary.json`），可用 `backend.metrics`
从原始日志独立复算：

| model_id | 样本 | 好人胜率 | 合法率 | no_go |
| --- | ---: | ---: | ---: | --- |
| `l0.random.v1` | 200 | 84.0% | 100% | 否 |
| `l1.rules.v1` | 200 | 36.5% | 100% | 否 |
| `l2.qtable.v1` | 200 | 31.5% | 100% | 是 |
| `l2.qtable.v2` | 200 | 35.0% | 100% | 是 |

`GET /api/training/metrics?model_id=l2.qtable.v2` 返回单条；未知 ID 返回 404。

## 3. 胜率 rollout 算法

`GET /api/training/rollout?policy=&seed_start=&games=&baseline_policy=`
对指定策略跑 `games` 局固定 seed 全对局，统计好人/狼人胜场：

- 用 `backend.simulator.simulate_game` 跑 seed `[seed_start, seed_start+games)`，
  全 AI 自博弈，动作经服务端合法动作校验。
- 好人胜率 `good_win_rate = good_wins / games`。
- 95% 置信区间用 Wilson 二项区间（`backend.training.wilson_interval`）。
- `delta_good_win_rate` = 该策略好人胜率 − 同 seed 基线的好人胜率
  （默认基线 `l0`）。
- `winners` 返回每局胜方，便于逐局核对；同参数两次调用结果完全一致。

边界：

- `policy` 只允许 `l0` / `l1` / `l2`；`baseline_policy` 只允许 `l0` / `l1`。
- `games` 限定 1–100，`seed_start` 非负整数，越界返回 422。
- “每个合法动作跑 N 次”的逐动作 rollout 已写进方法说明，但骨架阶段
  先落地“按策略的阵营胜率”；逐动作扩展留到 L3。

## 4. 20 局管线演示

命令（训练/评估 seed 与正式评估 1000–1199 完全分开）：

```powershell
python -m backend.simulator --games 20 --seed-start 2000 --policy l2 `
  --out training_runs/train-demo-20 `
  --model-out training_runs/train-demo-20/model.json --commit <sha>
python -m backend.simulator --games 20 --seed-start 3000 --policy l2 `
  --model-in training_runs/train-demo-20/model.json `
  --out training_runs/eval-demo-20 --commit <sha>
python -m backend.metrics --run training_runs/eval-demo-20
```

复跑结果：训练/评估各 20 局完成，`matches_summary: true`、`differences: []`，
证明训练命令链路可运行。正式模型未被覆盖。

## 5. 边界

- 十二人局不做。
- L2 No-Go 保持：接口返回的 `no_go` 字段为真，胜率 UI 未做。
- 所有数字都能回到 manifest 与原始日志复算，不生成任何“提升”结论。
