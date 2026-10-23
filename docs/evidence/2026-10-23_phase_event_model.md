# 阶段与事件模型验收记录

日期：2026-10-23

测试对象提交：`54e0f94`（`feat: model detailed phases and event visibility`）

Python：3.14.7

## 验收命令

```powershell
python -m unittest discover -s tests -v
```

## 结果

```text
----------------------------------------------------------------------
Ran 28 tests in 0.005s

OK
```

## 本次确认

- `Phase` 已升级为规则文档要求的 15 个稳定阶段。
- 旧的粗粒度 `NIGHT` 已删除，`start_night` 进入 `NIGHT_WOLF_DISCUSSION_R1`。
- `EventType` 已覆盖规则第 9 章要求的全部事件。
- 阶段枚举值和事件枚举值均不重复。
- 每个事件保留九个固定字段。
- `append_event` 自动生成连续 `event_seq`。
- `get_visible_events` 区分普通玩家、存活狼人和观战者。
- 死亡狼人不能再读取新的狼队事件。
- 游戏进入 `END` 后，玩家视角揭示全部事件。

## 当前边界

本提交建立阶段与事件结构，不包含狼人发言、刀人、查验、女巫用药、投票和死亡结算的具体业务动作。
