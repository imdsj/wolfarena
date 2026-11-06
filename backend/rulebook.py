"""Compact nine-player rulebook text injected into model prompts.

The engine is the source of truth for legality: a model can never submit an
illegal action because the server validates every action against
``available_actions_for_state``. What the model *does* need as text is the
九人局 flow, because that is what turns "legal" moves into sensible ones.
"""

from __future__ import annotations


RULES_BRIEF = """九人局配置：3 狼人、预言家、女巫、猎人、3 村民。无警长、无十二人局。
胜负：狼人杀光全部神职或全部平民即狼胜；好人放逐或杀死全部狼人即好人胜。
夜晚顺序：狼人内部讨论 2 轮 -> 狼刀（可空刀，可自刀）-> 预言家查验 -> 女巫用药 -> 结算。
预言家：每晚查验一名玩家，可以连续查验不同的人，这是正常规则，不代表前后矛盾。
女巫：解药和毒药各一次，同一晚不能同时用；解药可以救被狼刀的人，包括自己。
猎人：被狼刀或被投票放逐时可以开枪，被女巫毒死不能开枪。
白天：公布死讯（平安夜要明确说"平安夜"）-> 死者遗言 -> 按座位顺序逐个发言 -> 投票 -> 放逐遗言 -> 猎人开枪（如适用）。
投票：每名存活玩家一票，可弃票；平票时无人出局。
狼人自爆：白天发言阶段可以自爆，立即结束当天并进入黑夜。
信息边界：只能使用自己看到的公开信息和自己角色的私密信息；不得编造未发生的查验、刀口或用药。"""


def rules_brief() -> str:
    return RULES_BRIEF
