# 2026-10-28 训练证据重绑

日期：2026-10-28

绑定提交：`b2a8d89`

## 一、为什么重跑

旧 manifest 绑定的 `0f01afe`、`9c3cf41`、`25e95e8` 在使用临时 Git 元数据
推送后，本地 `.git` 未同步，导致本机无法证明指标来自当前远端代码。为消除
这一证据缺口，用远端 `main` 的真实提交 `b2a8d89` 重跑两组各 200 局。

## 二、命令

```powershell
python -m backend.simulator --games 200 --seed-start 1000 --policy l0 --out training_runs/l0-200 --commit b2a8d89
python -m backend.simulator --games 200 --seed-start 1000 --policy l1 --out training_runs/l1-200 --commit b2a8d89
python -m backend.metrics --run training_runs/l0-200
python -m backend.metrics --run training_runs/l1-200
```

## 三、结果

| 策略 | 局数 | 完成 | 动作 | 合法率 | 好人胜 | 狼人胜 | 平均步数 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| L0 随机 | 200 | 200 | 8719 | 100% | 168 | 32 | 43.595 |
| L1 规则 | 200 | 200 | 15403 | 100% | 73 | 127 | 77.015 |

与 10 月 27 日结果逐项相同。

独立指标复算：

```text
L0 matches_summary = true, differences = []
L1 matches_summary = true, differences = []
```

## 四、动作流哈希未变

同一 seed 区间 1000 至 1199：

```text
L0 actions.jsonl  9ab277a428a9a233995c4722cd8ab31dceca5998d92c99b29cb9052531fdcbcf
L1 actions.jsonl  ee5ed968879a0c14a14cb1d4c923998d78a67f6c9f6dcb99b0c20c21c0a05641
```

L0 与新一次运行的哈希完全一致，说明换绑提交号只改变了 `run.json`、
`games.jsonl`、`summary.json` 中的提交号与时间戳，没有改变策略行为。

## 五、文件

- `docs/evidence/2026-10-27_l0-200_summary.json`
- `docs/evidence/2026-10-27_l0-200_manifest.json`
- `docs/evidence/2026-10-27_l1-200_summary.json`
- `docs/evidence/2026-10-27_l1-200_manifest.json`

文件名保留 10 月 27 日的原始命名，内容已绑定 `b2a8d89`。

## 六、边界

- L1 仍是人工规则策略，不是 Q-learning。
- 没有训练前后对照，G-06 维持 No-Go。
- 原始 `training_runs/` 日志不入库，只提交 summary 与 manifest。
