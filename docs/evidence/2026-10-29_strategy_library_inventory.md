# 策略库盘点 · 2026-10-29

- 目录：`strategy_library/seeds`
- 数量：33 条（要求 ≥30）
- 全部为 `status=seed`、`evidence_level=rule_derived`、`samples=0`、`win_rate=null`
- 去重：`strategy_id` 唯一；重复写入抛 `StrategyError`，不允许覆盖
- 字段校验：`risk`、`evidence_level` 为必填，缺失直接校验失败

| # | strategy_id | 角色 | 阶段 | 动作 | 来源 |
| ---: | --- | --- | --- | --- | --- |
| 1 | `good.avoid-random-hunter-shot` | hunter | ANY | day_hunter_shot | docs/01_game_rules_v1.md |
| 2 | `good.protect-credible-seer` | villager | VOTE | vote | WolfArena 团队策略假设；未经过胜率验证 |
| 3 | `good.resolve-counterclaim` | villager | VOTE | vote | WolfArena 团队策略假设；未经过胜率验证 |
| 4 | `hunter.last-words-information` | hunter | DAY_LAST_WORDS | last_words | WolfArena 团队策略假设；未经过胜率验证 |
| 5 | `hunter.shot-consensus-wolf` | hunter | ANY | day_hunter_shot | WolfArena 团队策略假设；未经过胜率验证 |
| 6 | `hunter.shot-exposed-wolf` | hunter | ANY | day_hunter_shot | WolfArena 团队策略假设；未经过胜率验证 |
| 7 | `seer.announce-check-plan` | seer | DAY_DISCUSSION | speech | WolfArena 团队策略假设；未经过胜率验证 |
| 8 | `seer.check-claim-conflict` | seer | NIGHT_SEER_CHECK | seer_check | WolfArena 团队策略假设；未经过胜率验证 |
| 9 | `seer.check-counterclaim` | seer | NIGHT_SEER_CHECK | seer_check | WolfArena 团队策略假设；未经过胜率验证 |
| 10 | `seer.check-unverified` | seer | NIGHT_SEER_CHECK | seer_check | docs/01_game_rules_v1.md |
| 11 | `seer.check-suspicious-voter` | seer | NIGHT_SEER_CHECK | seer_check | WolfArena 团队策略假设；未经过胜率验证 |
| 12 | `villager.avoid-blind-bandwagon` | villager | VOTE | vote | WolfArena 团队策略假设；未经过胜率验证 |
| 13 | `villager.compare-votes` | villager | DAY_DISCUSSION | vote | WolfArena 团队策略假设；未经过胜率验证 |
| 14 | `villager.preserve-evidence` | villager | DAY_DISCUSSION | speech | WolfArena 团队策略假设；未经过胜率验证 |
| 15 | `villager.question-claim` | villager | DAY_DISCUSSION | speech | WolfArena 团队策略假设；未经过胜率验证 |
| 16 | `villager.track-vote-reversal` | villager | VOTE | vote | WolfArena 团队策略假设；未经过胜率验证 |
| 17 | `werewolf.preserve-deep-cover` | werewolf | DAY_DISCUSSION | speech | WolfArena 团队策略假设；未经过胜率验证 |
| 18 | `witch.antidote-known-kill` | witch | NIGHT_WITCH_ACTION | witch_action | docs/01_game_rules_v1.md#WITCH-003 |
| 19 | `witch.respond-counterclaim` | witch | DAY_DISCUSSION | speech | WolfArena 团队策略假设；未经过胜率验证 |
| 20 | `witch.hold-poison-without-evidence` | witch | NIGHT_WITCH_ACTION | witch_action | docs/01_game_rules_v1.md |
| 21 | `witch.poison-high-confidence` | witch | NIGHT_WITCH_ACTION | witch_action | docs/01_game_rules_v1.md |
| 22 | `witch.save-before-following-vote` | witch | DAY_DISCUSSION | speech | WolfArena 团队策略假设；未经过胜率验证 |
| 23 | `witch.save-confirmed-power-role` | witch | NIGHT_WITCH_ACTION | witch_action | WolfArena 团队策略假设；未经过胜率验证 |
| 24 | `wolf.adapt-speech-style` | werewolf | DAY_DISCUSSION | speech | WolfArena 团队策略假设；未经过胜率验证 |
| 25 | `wolf.avoid-hunter-risk` | werewolf | NIGHT_WOLF_KILL | wolf_kill | docs/01_game_rules_v1.md |
| 26 | `wolf.avoid-overclaim` | werewolf | DAY_DISCUSSION | speech | WolfArena 团队策略假设；未经过胜率验证 |
| 27 | `wolf.endgame-count` | werewolf | ANY | wolf_kill | docs/01_game_rules_v1.md |
| 28 | `wolf.kill-claimed-hunter` | werewolf | NIGHT_WOLF_KILL | wolf_kill | docs/01_game_rules_v1.md |
| 29 | `wolf.kill-claimed-seer` | werewolf | NIGHT_WOLF_KILL | wolf_kill | WolfArena 团队策略假设；未经过胜率验证 |
| 30 | `wolf.kill-claimed-witch` | werewolf | NIGHT_WOLF_KILL | wolf_kill | WolfArena 团队策略假设；未经过胜率验证 |
| 31 | `wolf.disciplined-selfdest` | werewolf | DAY_DISCUSSION | self_destruct | docs/01_game_rules_v1.md |
| 32 | `wolf.split-vote` | werewolf | VOTE | vote | WolfArena 团队策略假设；未经过胜率验证 |
| 33 | `wolf.consensus-wolf-kill` | werewolf | NIGHT_WOLF_KILL | wolf_kill | WolfArena 团队策略假设；未经过胜率验证 |

## 触发条件与风险

### `good.avoid-random-hunter-shot` 证据不足时猎人不开枪

- 触发：猎人获得开枪机会，但公开信息没有形成可信目标。
- 建议：选择不开枪，等待赛后复盘或用规则允许的遗言继续传递信息。
- 风险：漏枪会让好人少一次击杀窗口；把有证据的目标误判为“证据不足”会放走已暴露的狼。

### `good.protect-credible-seer` 好人优先保护可信预言家

- 触发：预言家已经给出一致可核验的查验链，狼队正在集中攻击该身份。
- 建议：优先处理直接威胁可信预言家的高嫌疑目标，并避免把票投给已核验好人。
- 风险：过早集中保护会被狼队反向利用票型；对“可信”的判断一旦出错会连带失去真神职。

### `good.resolve-counterclaim` 好人先解决预言家冲突

- 触发：出现多个预言家自报或互相冲突的查验结论，且冲突未解决。
- 建议：优先比较双方查验逻辑、验人顺序和受益关系，再决定投票；证据不足时避免盲目跟随单一归票。
- 风险：白天资源全押在对跳上会挤占刀口与归票分析；两边都不是关键狼位时等于浪费一天。

### `hunter.last-words-information` 猎人遗言传递可核验信息

- 触发：猎人即将通过遗言发言，队内仍需要其身份和判断依据。
- 建议：先说明可核验事实，再给出怀疑顺位；不编造未获得的信息。
- 风险：遗言过长或写入未验证推断会误导好人；应只保留可被规则或日志复核的内容。

### `hunter.shot-consensus-wolf` 猎人优先处理高可信狼位

- 触发：猎人合法开枪，场上已有较稳定的自报冲突、票型或查验证据。
- 建议：优先选择证据最集中且对好人威胁最高的狼位；没有可信目标时选择不开枪。
- 风险：依赖共识意味着可能跟随错误多数；共识本身可能是狼队刻意制造的一致。

### `hunter.shot-exposed-wolf` 猎人处理已暴露狼位

- 触发：合法开枪时，已有公开事件、票型或查验明确指向一个狼位。
- 建议：优先带走证据链最清晰的狼人，并避免被未经核实的归票节奏推动。
- 风险：已暴露狼位也可能是狼队弃子诱导开枪；开枪前需确认没有更值得保护的神职目标。

### `seer.announce-check-plan` 预言家公开查验逻辑

- 触发：预言家已经掌握多轮查验结果，需要对好人阵营提供可核验信息。
- 建议：按夜次说明查验对象和结果，并解释目标选择；只陈述实际收到的结果。
- 风险：公开查验逻辑会同时给狼队提供刀口与伪装线索；过早公布完整计划可能被反向利用。

### `seer.check-claim-conflict` 预言家围绕身份冲突补查验

- 触发：某名未查验玩家支持与自己结论直接冲突的神职自报。
- 建议：在合法且未查验的目标中优先核验该玩家，以验证冲突阵营的结构。
- 风险：围绕冲突补查验会消耗有限查验次数；冲突双方都不是关键位时信息收益很低。

### `seer.check-counterclaim` 预言家优先核验冲突位

- 触发：场上存在查验结论冲突、多个自称预言家或高影响力争议玩家。
- 建议：在未查验且合法的目标中优先选择能最大程度消除公共冲突的位置。
- 风险：只盯对跳位会漏掉沉默的深水狼；单点核验无法覆盖全部可疑归票。

### `seer.check-unverified` 预言家避免重复查验

- 触发：当前仍有存活且本人尚未查验的合法目标。
- 建议：从未查验的合法目标中选择信息价值最高者，避免重复消耗夜间查验。
- 风险：追求“未查验”可能挑到信息价值低的目标；要结合发言异常，而不是只看是否查过。

### `seer.check-suspicious-voter` 预言家优先查验异常归票者

- 触发：某玩家有明显异常归票、发言与票型不一致，且尚未被查验。
- 建议：在合法未查验目标中优先核验该玩家，以便将投票线索转化为确定信息。
- 风险：异常归票也可能来自信息不足的好人；误判会直接浪费一次查验。

### `villager.avoid-blind-bandwagon` 村民避免无证据跟票

- 触发：票型快速集中，但最早归票理由没有公共证据支撑。
- 建议：要求归票者说明依据，并在可接受时选择弃权或支持证据更充分的目标。
- 风险：拒绝跟票可能造成分票放走狼；必须给出可复核理由，不能只是消极不投。

### `villager.compare-votes` 村民比较投票动机与发言变化

- 触发：白天出现多组互相冲突的发言，投票前无法仅凭单一发言判断身份。
- 建议：对照玩家前后立场、归票行为和受益方，优先选择解释成本最高的目标。
- 风险：投票动机解读带主观性；把正常的策略性归票误读为狼行为会误伤好人。

### `villager.preserve-evidence` 好人保留可核验事件链

- 触发：白天讨论出现多轮身份自报和冲突结论。
- 建议：引用实际发生的自报、查验、死亡和票型事件，避免用记忆模糊的二手描述定案。
- 风险：只保存证据不下结论会拖慢节奏；关键回合仍需要明确表态。

### `villager.question-claim` 村民追问神职自报细节

- 触发：有玩家自报神职，但验人顺序、药水状态或行为因果无法闭合。
- 建议：针对可核验细节提出简短追问，并要求对方按时间顺序说明。
- 风险：追问过细会迫使真神职暴露更多信息，也可能被狼队用来消耗发言时间。

### `villager.track-vote-reversal` 村民关注归票反转

- 触发：投票截止前出现明显归票反转，且反转方的公开理由不足。
- 建议：对照反转前后的受益者，将解释不足者列为高优先级嫌疑，而不是机械追随末轮归票。
- 风险：归票反转有时只是信息更新；过度解读会人为制造对立。

### `werewolf.preserve-deep-cover` 狼队保留深水位队友

- 触发：狼队已有队友暴露风险，但仍有未被重点关注的存活队友。
- 建议：避免所有狼人使用相同归票和发言结构，优先让低暴露队友保留后续夜间行动空间。
- 风险：保深水会让狼队短期少一个火力点；深水队友一旦被查验会整体暴露。

### `witch.antidote-known-kill` 女巫按可见刀口评估解药

- 触发：女巫仍有解药，并且服务端私密信息给出了当夜准确刀口。
- 建议：只在刀口目标属于关键好人或当前局势不能承受该死亡时使用解药；空刀不使用解药。
- 风险：只按可见刀口评估会漏掉自刀骗药的局；救错目标会浪费唯一的解药。

### `witch.respond-counterclaim` 女巫处理神职对跳

- 触发：出现女巫身份冲突或有人冒充女巫影响好人归票。
- 建议：只在必要且可解释时披露自己的关键决策信息，说明限制和不确定之处。
- 风险：女巫参与对跳会暴露药量信息；判断失误会同时失去可信度与药品。

### `witch.hold-poison-without-evidence` 无解药女巫保留毒药证据门槛

- 触发：解药已用、毒药仍可用，但没有结构化高可信狼位。
- 建议：选择不用药，继续观察公开冲突和票型；不要因没有刀口信息而随机毒人。
- 风险：过度保守可能带着毒药出局；毒药没用出去等于放弃一次击杀机会。

### `witch.poison-high-confidence` 女巫毒药只用于较高可信度目标

- 触发：毒药仍可用，存在发言矛盾、查验冲突或投票行为高度可疑的目标。
- 建议：当错误毒杀的代价明显大于观望时再使用毒药；缺少结构化证据时选择不用药。
- 风险：“高可信”仍可能是狼队诱导；毒错好人会直接改变人数优势。

### `witch.save-before-following-vote` 女巫先处理夜间信息再跟票

- 触发：女巫掌握与白天归票方向冲突的夜间信息，但尚未决定是否公开。
- 建议：先比较公开信息的风险与收益，再用最小必要细节纠正错误归票。
- 风险：先处理夜间信息可能延误白天归票；夜间信息不完整时容易两头落空。

### `witch.save-confirmed-power-role` 女巫优先保护高可信度神职

- 触发：解药仍可用，刀口目标有较高可信度的预言家或关键好人身份。
- 建议：在资源和局势允许时使用解药保护该目标，并在白天避免泄露过多夜间细节。
- 风险：“高可信”依赖白天发言，狼队可伪装神职骗药；救错即浪费解药。

### `wolf.adapt-speech-style` 狼人避免固定发言模板

- 触发：多名狼队友连续使用近似的发言结构和归票理由。
- 建议：根据各自公开视角调整用词和关注点，保持事实一致但不复刻同一模板。
- 风险：刻意变化可能显得不自然；过度模仿好人模板反而会暴露。

### `wolf.avoid-hunter-risk` 狼队避开不确定猎人刀口

- 触发：高价值目标可能是猎人，且狼队无法承受其开枪反制。
- 建议：在刀神职收益与被猎人带走的风险之间比较，必要时选择更安全的目标或空刀。
- 风险：回避猎人刀口会放弃高价值目标；过度谨慎会让神职多活一天。

### `wolf.avoid-overclaim` 狼人避免无准备的神职对跳

- 触发：没有验人逻辑、票型或队友配合支撑时考虑自报神职。
- 建议：缺少可验证叙事时保持普通好人表达，不临时自报高冲突神职。
- 风险：完全不跳神职会失去话语权；残局必须抢节奏时过度保守会直接输。

### `wolf.endgame-count` 狼人终局优先计算人数

- 触发：存活人数接近获胜条件，狼队需要在击杀、空刀和自爆之间选择。
- 建议：先计算行动后的存活狼人与好人数量，再选择能直接满足胜利条件或阻止好人获胜的方案。
- 风险：只算人数会忽略猎人枪与女巫药；错算一次就可能把必胜局打成平局。

### `wolf.kill-claimed-hunter` 谨慎评估公开跳猎人的刀口

- 触发：玩家公开自报猎人，且狼队当前不能承受猎人开枪风险。
- 建议：比较直接击杀猎人与其可能带走的狼队友风险；风险过高时改刀其他神职或空刀。
- 风险：刀真猎人会立即挨一枪；把它判断成假跳则可能浪费一刀。

### `wolf.kill-claimed-seer` 优先处理公开跳预言家的目标

- 触发：白天有玩家明确自报预言家，且该玩家存活、属于本夜合法刀人目标。
- 建议：在确认自报信息不是明显玩笑后，优先选择该目标；若多个自报，结合票型和发言可信度排序。
- 风险：跳预言家可能是好人诈身份或狼队对跳；刀错目标会暴露刀口逻辑。

### `wolf.kill-claimed-witch` 评估公开跳女巫目标的刀口价值

- 触发：白天有玩家明确自报女巫，已经出现神职冲突或该玩家掌握用药信息。
- 建议：优先比较自报女巫与自报预言家的威胁；解药信息已明确时优先处理更高信息价值目标。
- 风险：女巫可能已经无药；刀口价值要结合药量推断，误判会浪费关键刀。

### `wolf.disciplined-selfdest` 狼人只在收益明确时自爆

- 触发：狼人即将被确定放逐，或自爆能够立即终止不利投票并扭转节奏。
- 建议：只有当收益高于保留身份和发言机会时自爆；普通讨论不因情绪触发。
- 风险：自爆会放弃当天发言与归票收益；判断失误会让狼队直接少一人。

### `wolf.split-vote` 狼队避免集中暴露归票链

- 触发：狼队需要隐藏队友关系且当前票型不足以确保放逐目标。
- 建议：按预设分工投票并保留可解释理由，避免所有狼人机械跟随同一目标。
- 风险：分票可能直接把队友票出去；人数劣势时分票风险高于收益。

### `wolf.consensus-wolf-kill` 狼队刀口保持统一信息

- 触发：狼队内部对多个目标存在不同判断。
- 建议：先形成统一目标并记录理由，避免队员在后续复盘中引用互相矛盾的刀口信息。
- 风险：统一刀口会留下稳定行为模式；被复盘时容易识别出狼队协同。

