# 第 6 步核心函数验收记录

日期：2026-10-22

测试对象提交：`a969d0c`（`feat: add night transition and winner checks`）

Python：3.14.7

## 验收命令

```powershell
python -m unittest discover -s tests -v
```

## 结果

```text
----------------------------------------------------------------------
Ran 17 tests in 0.005s

OK
```

## 本次确认

- `create_game` 创建固定九人阵容并支持可复现角色分配。
- `get_player` 支持玩家编号和唯一昵称查询。
- `start_night` 将第 0 天 `INIT` 推进到第 1 天 `NIGHT`。
- `start_night` 拒绝在同一夜晚重复调用。
- `check_winner` 在初始 3 狼对 6 好人时返回游戏未结束。
- 全部狼人死亡时好人获胜。
- 存活狼人数大于或等于存活好人数时狼人获胜。
- 两个条件同时成立时按规则优先判好人获胜。

## 当前边界

本提交中的 `start_night` 只完成阶段入口。完整夜间行动、死亡事件、遗言、投票和游戏结束写入将在后续里程碑实现。
