# WolfArena AI 成长数据与 L0 策略 V0.1

状态：数据结构与 L0 新手策略已实现；训练指标尚未测量。

代码位置：`backend/ai_growth.py`

## 1. 成长阶段

| 枚举值 | 名称 | 当前含义 |
| --- | --- | --- |
| `L0_NOVICE` | 新手基线 | 只在服务端合法动作中随机选择 |
| `L1_RULE` | 规则策略 | 预留：根据明确规则选择动作 |
| `L2_STRATEGY` | 策略模型 | 预留：共享 Q-learning 或其他策略模型 |
| `L3_ADVERSARIAL` | 对抗进化 | 预留：策略版本对战和持续更新 |

`GROWTH_STAGE_ORDER` 固定四个阶段顺序，前后端和训练日志应使用相同枚举值。

## 2. DecisionRecord

一次可审计决策必须包含：

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `game_id` | `str` | 非空 |
| `seed` | `int` | 整数 |
| `day` | `int` | 大于等于 0 |
| `phase` | `Phase` | 必须是稳定阶段枚举 |
| `player_id` | `str` | 非空 |
| `role` | `Role` | 必须是稳定角色枚举 |
| `legal_actions` | `tuple[str, ...]` | 非空、无重复、无空字符串 |
| `chosen_action` | `str` | 必须来自 `legal_actions` |
| `strategy_id` | `str` | 非空 |
| `confidence` | `float` | 0 至 1 |
| `outcome` | `str \| None` | 对局结束后填写 |
| `reflection` | `str \| None` | 复盘阶段填写 |

创建记录时就会校验动作合法性，非法选择无法进入训练数据。

## 3. StrategyRecord

策略记录包含：

```text
strategy_id
role
phase
trigger
action
source
samples
win_rate
interval
version
status
```

默认状态：

```text
samples = 0
win_rate = None
interval = None
version = v0.1
status = untested
```

没有样本时填写胜率或区间会直接抛出错误，从数据结构层阻止伪造训练指标。

## 4. L0Policy

`L0Policy(seed)` 使用独立的 `random.Random(seed)`：

- 不调用 DeepSeek、OpenAI 或任何外部 API。
- 只从调用方提供的 `legal_actions` 中选择。
- 相同 seed、相同调用顺序产生相同决策序列。
- 空动作列表会抛出 `ValueError`。
- 重复动作或空字符串动作会抛出 `ValueError`。
- `make_decision` 会生成 `strategy_id=l0.random.v1`、`confidence=0.0`、`outcome=None`、`reflection=None` 的决策记录。

`confidence=0.0` 表示 L0 没有模型置信度，不代表预测准确率。

## 5. 当前可执行验证

```powershell
python -m unittest discover -s tests -v
```

当前完整测试基线为 69 项，其中 15 项覆盖 AI 成长数据与 L0。

## 6. 成长指标状态

`GT-01` 至 `GT-08` 当前为**阻塞**。

阻塞原因：

- 完整白天流程尚未实现。
- 投票和放逐尚未实现。
- 自爆窗口尚未实现。
- 完整一局无法自动闭环。
- 训练场批量模拟入口尚未实现。
- 结构化动作日志尚未导出到训练文件。

因此当前不能计算 200 局胜率、策略分布或训练前后差异。后续只有在完整对局闭环后，才允许填写真实指标。
