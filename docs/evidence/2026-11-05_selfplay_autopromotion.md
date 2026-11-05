# 自对弈 + 自动晋级闭环（2026-11-05）

## 结论先行

九人局 AI 现在可以整夜自己跟自己打，每局自动复盘成一条候选战术，再用固定
seed 的 200 局配对对照检验，证据充分且显著的战术自动进入 `validated/`，
不显著或负面的进 `rejected/`，其余留在 `candidates/` 等人工点头。全程不
伪造胜率、不读隐藏身份、不调用任何非白名单动作。

## 三种入库路径

| 路径 | 触发条件 | 审核人字段 |
| --- | --- | --- |
| 自动晋级 | 同 seed 200 局，McNemar p<=0.05 且好人胜率 delta>=+3% | `auto-gate.v1` |
| 自动拒绝 | 显著变差（delta<=-2% 且 p<=0.05，或 delta<=-5%） | 记录拒绝原因 |
| 人工确认 | 其余所有情况（证据不充分 / 效果不明显） | 真实姓名 |

每条战术卡都带一个机器可执行指令 `directive`，属于固定白名单（例如
`vote_most_accused`、`witch_poison_most_accused`、`hunter_hold`、
`seer_check_counterclaim`、`wolf_kill_accuser`）。指令只能重排服务器给出的
合法目标，永远无法生成新动作或非法目标。

## 今晚跑了什么

无 API Key 时复盘走确定性兜底卡，对局本身免费。一次 3 轮小样本验证：

- `cand.review.6677d4fb` `wolf_kill_accuser`：delta=+2.0pp，p=0.48 -> 人工确认
- 手工构造的 `cand.vote-most-accused.v1` `vote_most_accused`：delta=+2.0pp，p=0.125 -> 人工确认

两个候选都**没有**自动晋级，因为 n=200 下 2pp 的差距落在噪声里。这正是闸门
该有的样子：宁可排队等人，也不把噪声当提升。

## 为什么 n=200 很难自动晋级

配对 McNemar 检验要求一次战术改动至少翻转约 7 局才显著（7:0 -> p≈0.016）。
规则策略的一处目标选择改动通常只翻转 2~4 局，所以大多数发现会进人工队列。
想更快看到自动晋级，需要每夜更多局数（如评估 500 局）或把多条同向指令合并
成一条候选一起评估。前者要时间，后者要更聪明的复盘归纳，都属于后续工作。

## 当前 L1 基线漂移

重测发现 L1 好人胜率已从 10 月记录的 36.5%（seed 1000-1199）漂移到约
17%~21.5%（同样 seed 1000-1199 为 17.0%，seed 7000-7199 为 21.5%）。这不是
今天新引入的，commit `c9b98a2` 已标注「L1 baseline drift」。含义：过去文档
里的 L1=36.5% 已不可作为当前基准，后续对照必须重新在同一批 seed 上测基线，
不能拿新策略和旧数字比。

## 夜里怎么跑

在项目目录（已激活 `.venv`）执行：

```powershell
python -m backend.autotrain --hours 5 --budget 15 --games 20 --review-games 3
```

- `--hours 5` 每晚最多跑 5 小时，可随时 Ctrl+C，`state.json` 会记下已用 seed，
  下次接着跑，不重复。
- `--budget 15` 每天估算花费上限 15 元；无 Key 时对局和复盘全免费。
- 报告写在 `training_runs/autotrain/report.md`，每轮一行，含候选、delta、p 和判决。

花费按 deepseek-chat 保守价格估算（输入 2 元/M token、输出 8 元/M token），
只对复盘 LLM 调用计数。对局本身纯本地 CPU，不花钱。

## 人工点头入库怎么操作

看队列：

```powershell
python -m backend.promote pending
```

跑 200 局对照（写证据，先不晋级）：

```powershell
python -m backend.promote evaluate <策略ID> --seed-start 7000 --games 200
```

点头入库（填真名，会把你写进 `reviewer` 字段留痕）：

```powershell
python -m backend.promote approve <策略ID> --reviewer 张三
```

后悔了，把已验证策略退回候选：

```powershell
python -m backend.promote rollback <策略ID> --reason "理由"
```

入库后，`rooms.py` 会在每局开始时加载 `validated/` 里的指令，实时对局立即生效；
自对弈也用同一套 `validated/`，所以学习成果会滚雪球进入下一夜的对局。

## 规则从哪里来

AI 不需要你手写一份“可执行规则”——合法性由服务端引擎强制（非法动作直接被拒）。
模型需要的是流程文字，已收敛到 `backend/rulebook.py`，自动注入复盘和发言提示词：
九人局角色、胜负条件、夜晚顺序、女巫/猎人/自爆细节、信息边界。这套规则同样
保证自对弈里狼可以自刀、可以骗药，但永远读不到好人视角外的隐藏身份。
