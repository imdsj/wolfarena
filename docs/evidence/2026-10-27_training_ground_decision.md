# 10 月 27 日训练场 Go / No-Go 判定（Hurry 独立验证）

日期：2026-10-27

执行人：Hurry

验证对象提交：`fe9cb29`（`docs: align simulator evidence with final test count`）

对照文档：`docs/evidence/2026-10-27_training_go_no_go.md`（订书机撰写，基于 `0f01afe`）

环境：`<local-path>` + `.venv`（Python 3.14.0）

## 一、判定结论

```text
基础闭环（G-01、G-02、G-04、G-05）：通过
策略成长（G-03 训练版、G-06 前后对比）：未通过
```

**10 月 30 日可交付**：L0 基线、L1 规则版工程对照、固定 seed 可复现日志、动作分布与阵营胜率、200 局批量报告。

**10 月 30 日不可宣称**：AI 通过训练变强、训练前后胜率提升。L0 与 L1 的差异来自规则不同，不是学习结果。

## 二、验证方法

不采信既有文档的结论，全部在本机用 `.venv` 复跑，命令与原始数据均保留在 `<local-path>`。

```powershell
python -m backend.simulator --games 200 --seed-start 1000 --policy l0 --out <local-path>
python -m backend.simulator --games 1   --seed-start 1033 --policy l0 --out <local-path>
python -m backend.simulator --games 1   --seed-start 1033 --policy l0 --out <local-path>
python -m backend.simulator --games 200 --seed-start 1000 --policy l1 --out <local-path>
python -m backend.metrics   --run <local-path>
```

## 三、门禁逐项结果

| 门禁 | 判定 | 我的复跑证据 |
| --- | --- | --- |
| G-01 批量对局 | **通过** | 200 局 `completed_games=200`、`failed_games=0`、`errors_by_type={}`，总耗时 2703.902 ms |
| G-02 固定 seed 复现 | **通过** | seed 1033 两次运行各 74 个动作、`0` 失败；`actions.jsonl` 的 SHA-256 两次完全相同：`B080CC0578AD388114D12FDBF513E98CA29E5B36376E1E25F7CDD1A67D4DFBF1` |
| G-03 版本切换 | **工程通过，训练版阻塞** | CLI `--policy` 支持 `l0` / `l1`；`l1` 的 `policy_version` 为 `l1.rule.v1`，是规则版，仓库内不存在训练版策略 |
| G-04 日志导出 | **通过** | 每次运行产出 `actions.jsonl`、`games.jsonl`、`roles.json`、`summary.json`、`manifest.json`、`run.json`；动作记录含 actor / role / target / ok |
| G-05 指标可复算 | **通过** | `backend.metrics` 从 JSONL 独立复算，输出 `matches_summary: true`、`differences: []` |
| G-06 前后对比 | **No-Go** | 无训练版，按约定不生成任何训练前后胜率结论 |

## 四、200 局实测数据（我的复跑）

| 策略 | 版本标识 | 好人胜 | 狼人胜 | 好人胜率 | 平均步数 | 总耗时 | 错误 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| L0 | `l0.random.v1` | 168 | 32 | 0.840 | 43.595 | 2703.902 ms | 0 |
| L1 | `l1.rule.v1` | 73 | 127 | 0.365 | 77.015 | 6186.741 ms | 0 |

seed 范围均为 1000 至 1199，两者使用同一组 seed。

这两组数字与订书机文档中的 `168/32`、`73/127` 逐项一致。

**解读边界**：L1 相对 L0 把好人胜率从 0.84 压到 0.365，原因是 L1 加了三类规则（狼人优先攻击公开自报神职、预言家优先查验未查验目标、女巫有解药时按可见刀口用药）。这是**同一套引擎下两种策略的工程对照**，能证明策略层可插拔、可替换，**不能证明任何学习效果**。L0 的 0.84 本身也只是随机合法动作的基线，不是「AI 打得好」。

## 五、一项比订书机文档更强的证据

固定 seed 的 `actions.jsonl` 哈希在两个不同机器上完全一致：

```text
订书机文档记录的 SHA-256：B080CC05…4DFBF1
我在本机复跑的 SHA-256：  B080CC05…4DFBF1
```

说明确定性不依赖机器性能或时序，**任意评审者用同一 seed 都能得到同一局**。这一点对 10 月 30 日的可信度很关键，建议在演示材料里明确写出来。

## 六、给 10 月 30 日的三条建议

1. **演示话术要卡住边界**：可以说「同一 seed 下两种策略产生 125/200 局不同结局，说明策略层真实生效」，不能说「训练后胜率提升」。前者是事实，后者在本仓库没有证据。
2. **把 `l1.rule.v1` 明确标为规则版**，不要在任何界面或 PPT 上叫「训练版」，否则会被追问训练方法。
3. **G-06 保持 No-Go**，直到出现带版本标识、可复算的训练版策略。

## 七、风险项

| 编号 | 问题 | 影响 |
| --- | --- | --- |
| R-01 | `strategy_library/seeds/` 只有 **12 个**种子策略，10 月 30 日清单要求「至少 30 条」 | 清单该项当前不满足，需补 18 条，或提前与订书机确认降级口径 |
| R-02 | `strategy_library/validated/` 为空（0 条已校验） | 种子策略未经校验流程，若清单要求「可用策略」需先完成校验 |
| R-03 | 无训练版策略 | G-03、G-06 无法转 Go，「新手版与训练版有可观察差异」这条清单项不成立 |

## 八、本次未做的事

- 未生成任何训练前后胜率对比。
- 未把 L1 表述为训练版或学习成果。
- 未修改 `backend/` 下任何业务代码与策略实现。
- 未使用系统 Python 判断项目状态（全程 `.venv`）。

## 九、附注：一处需要修正的文档日期

`docs/evidence/2026-10-27_training_go_no_go.md` 正文首行写的是「日期：2026-10-25」，但该文档关联的提交是 `0f01afe`（2026-10-27 10:48）。证据文档的日期需与提交时间对应，建议改为 2026-10-27。
