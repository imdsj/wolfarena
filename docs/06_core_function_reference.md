# WolfArena 核心函数说明 V0.1

状态：已实现最小版本并通过自动化测试。

代码位置：`backend/game_engine.py`

## 1. `create_game`

调用形式：

```python
create_game(seed: int, human_count: int = 1, player_names=None) -> GameState
```

| 项目 | 内容 |
| --- | --- |
| 输入 | 整数 `seed`、真人数量 `human_count`，可选九名玩家的昵称 |
| 输出 | 新的 `GameState` |
| 主要作用 | 固定生成九名玩家，并按 seed 打乱角色牌堆 |
| 初始状态 | `phase=INIT`、`day=0`、`night_result=None` |
| 角色组成 | 3 狼人、3 村民、预言家/女巫/猎人各 1 名 |
| 错误情况 | seed 类型错误、真人数量越界、昵称不足九个或重复 |

同一个 seed 只控制角色分配的随机顺序。使用新的相同 seed 再创建一局时，座位与角色的对应关系一致。

## 2. `get_player`

调用形式：

```python
get_player(state: GameState, identifier: str) -> Player
```

| 项目 | 内容 |
| --- | --- |
| 输入 | 当前游戏状态、玩家编号或唯一昵称 |
| 输出 | 找到的 `Player` |
| 主要作用 | 从九名玩家中定位一名玩家 |
| 示例 | `get_player(state, "p4")` 或 `get_player(state, "选手4")` |
| 错误情况 | 标识不存在时抛出 `KeyError` |

## 3. `start_night`

调用形式：

```python
start_night(state: GameState) -> GameState
```

| 项目 | 内容 |
| --- | --- |
| 输入 | 当前 `GameState` |
| 输出 | 更新后的同一个 `GameState` |
| 主要作用 | 天数加一，阶段切换为 `NIGHT`，清空旧的夜间结果 |
| 可进入夜晚的阶段 | `INIT`、`VOTE`、`SELF_DESTRUCT` |
| 当前不负责 | 狼人讨论、刀人、查验、女巫用药、死亡和猎人开枪 |
| 错误情况 | 已经在 `NIGHT` 或游戏已经结束时拒绝重复切换 |

调用后可以选择：

```python
state.day
state.phase
state.night_result
```

## 4. `check_winner`

调用形式：

```python
check_winner(state: GameState) -> Team | None
```

| 项目 | 内容 |
| --- | --- |
| 输入 | 当前 `GameState` |
| 输出 | `Team.GOOD`、`Team.WOLF` 或 `None` |
| `Team.GOOD` | 存活狼人数为 0 |
| `Team.WOLF` | 存活狼人数大于或等于存活好人数 |
| `None` | 两个胜利条件都未满足 |
| 当前不负责 | 修改阶段、设置最终胜者、公开身份或写入结束事件 |
| 调用时机 | 每次出现玩家死亡后 |

若两个条件同时成立，先判断狼人是否全灭，因此好人阵营获胜。

## 5. 当前验收基线

运行：

```powershell
python -m unittest discover -s tests -v
```

功能提交 `a969d0c` 的基线结果是 17 项测试通过。测试把创建、查询、阶段切换和胜负判断分开验证，不使用界面操作代替规则检查。

学习这四个函数时应能回答：

1. 它接收什么数据？
2. 它返回什么？
3. 它会不会修改原来的游戏状态？
4. 哪些输入会导致拒绝或报错？
5. 它对应规则文档中的哪些编号？
