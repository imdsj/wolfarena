# 10 月 27 日模拟器步骤 3 至 4 验收

日期：2026-10-25

代码提交：`25e95e8`

## 输出文件

每次模拟在 `--out` 目录生成：

| 文件 | 内容 |
| --- | --- |
| `games.jsonl` | 每局 game_id、seed、winner、days、steps、角色、错误和耗时 |
| `actions.jsonl` | 每步 game_id、seed、day、phase、actor、role、action、target、ok 及审计字段 |
| `roles.json` | 每局每个 player_id、seat 和 role |
| `summary.json` | 完成率、合法率、动作频率、阵营胜率、平均步数和耗时 |
| `manifest.json` | commit、命令、Python 版本和输出文件 SHA-256 |
| `run.json` | 批次配置、完成/失败统计及兼容性摘要 |

非法提交或执行异常会以 `ok=false`、`succeeded=false` 和 `error` 写入动作日志；
失败局保留在 `games.jsonl`，不进入阵营胜率分母。

## 指标定义

```text
完成率 = 到达 END 的局数 / 总局数
行动合法率 = ok=true 的动作数 / 所有提交动作数
动作频率 = 某动作成功次数 / 总局数
阵营胜率 = 某阵营胜局 / winner 有效的 END 局数
平均步数 = 完成局总步数 / 完成局数
平均耗时 = 完成局总耗时 / 完成局数
```

## 200 局正式输出

命令：

```powershell
python -m backend.simulator `
  --games 200 `
  --seed-start 1000 `
  --policy l0 `
  --out training_runs/l0-200 `
  --commit 85bdb3c
```

结果：

```text
policy：l0.random.v1
seed：1000 至 1199
总局数：200
到达 END：200
失败局：0
完成率：1.0
提交动作：8719
成功动作：8719
失败动作：0
行动合法率：1.0
平均步数：43.595
平均单局耗时：15.099815 ms
批次总耗时：3019.963 ms
好人胜：168，胜率 0.84
狼人胜：32，胜率 0.16
```

动作频率前五项：

```text
wolf_speech   11.320 次/局
speech         8.575 次/局
vote           3.075 次/局
wolf_kill      2.850 次/局
resolve_night  2.850 次/局
```

完整动作频率在 `training_runs/l0-200/summary.json`。

## Manifest 校验

`manifest.json` 使用 SHA-256 绑定：

```text
run.json
games.jsonl
actions.jsonl
roles.json
summary.json
```

独立重新计算五个文件的 SHA-256，全部与 manifest 一致。

## 固定 seed 复算

seed `1033` 分别输出到 `repeat-a` 和 `repeat-b`：

```text
actions.jsonl 逐字段一致：是
actions.jsonl SHA-256：B080CC0578AD388114D12FDBF513E98CA29E5B36376E1E25F7CDD1A67D4DFBF1
replay_sha256：0418f9dd06c8053a0bc9dc0ff8e31498434ae84a43de2463d72611e08dcd8c56
终局摘要一致：是
动作数：74
终局：END
胜者：good
天数：4
```

独立指标命令：

```powershell
python -m backend.metrics --run training_runs/l0-200
```

结果：

```text
matches_summary：true
differences：[]
```

## 边界

本次 L0 只从服务端合法动作中选择，因此正式 200 局中非法提交为 0，合法率为
100%。指标代码和单元测试仍覆盖 `ok=false`、失败局、死锁和异常动作，保证
后续训练版出现非法动作时不会静默丢失。

训练原始文件保留在 `training_runs/`，不提交 Git。L0 的 84%/16% 原始阵营结果
不能写成训练提升，也不能作为训练版策略效果；同 seed 的 L0 与训练版对照尚未
开始。
