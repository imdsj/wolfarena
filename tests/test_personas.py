"""Tests for deterministic player archetypes."""

from __future__ import annotations

from unittest import TestCase

from backend.game_engine import (
    EventType,
    Phase,
    Role,
    Visibility,
    append_event,
    create_game,
)
from backend.personas import (
    ARCHETYPE_LABELS,
    Archetype,
    ArchetypePolicy,
    assign_archetypes,
    persona_guidance,
)
from backend.schemas import ActionView


class PersonaTests(TestCase):
    def test_wolves_receive_distinct_archetypes(self) -> None:
        for seed in range(24):
            with self.subTest(seed=seed):
                state = create_game(seed=seed, human_count=0)
                wolves = [
                    player
                    for player in state.players
                    if player.role is Role.WEREWOLF
                ]
                assigned = assign_archetypes(seed, state.players)
                self.assertEqual(
                    len({assigned[wolf.player_id] for wolf in wolves}),
                    len(wolves),
                )

    def test_assignment_is_deterministic(self) -> None:
        first = create_game(seed=7, human_count=0)
        second = create_game(seed=7, human_count=0)
        self.assertEqual(
            assign_archetypes(7, first.players),
            assign_archetypes(7, second.players),
        )

    def test_labels_cover_every_archetype(self) -> None:
        for archetype in Archetype:
            self.assertIn(archetype, ARCHETYPE_LABELS)

    def test_strategy_id_carries_persona(self) -> None:
        for archetype in Archetype:
            policy = ArchetypePolicy(seed=1, archetype=archetype)
            self.assertIn(archetype.value, policy.strategy_id)

    def test_guidance_differs_across_archetypes(self) -> None:
        texts = {archetype: persona_guidance(archetype) for archetype in Archetype}
        self.assertEqual(len(set(texts.values())), len(Archetype))

    def test_every_archetype_picks_a_legal_target(self) -> None:
        state = create_game(seed=3, human_count=0)
        state.phase = Phase.VOTE
        state.day = 1
        actor = next(
            player
            for player in state.players
            if player.role is Role.VILLAGER
        )
        targets = [
            player.player_id
            for player in state.players
            if player.player_id != actor.player_id
        ]
        view = ActionView(
            action="vote",
            label="投票",
            target_ids=targets,
            requires_target=True,
        )
        for archetype in Archetype:
            with self.subTest(archetype=archetype.value):
                policy = ArchetypePolicy(seed=3, archetype=archetype)
                self.assertIn(
                    policy.choose_target(state, actor, view),
                    targets,
                )

    def test_aggressive_prefers_a_reported_wolf(self) -> None:
        state = create_game(seed=11, human_count=0)
        state.phase = Phase.VOTE
        state.day = 1
        villagers = [
            player
            for player in state.players
            if player.role is Role.VILLAGER
        ]
        claimant = villagers[0]
        actor = villagers[1]
        wolf = next(
            player
            for player in state.players
            if player.role is Role.WEREWOLF
        )
        append_event(
            state,
            EventType.PUBLIC_SPEECH,
            actor_id=claimant.player_id,
            visibility=Visibility.PUBLIC,
            data={"content": f"我是预言家，我验了{wolf.seat}号是狼"},
        )
        targets = [
            player.player_id
            for player in state.players
            if player.player_id != actor.player_id
        ]
        view = ActionView(
            action="vote",
            label="投票",
            target_ids=targets,
            requires_target=True,
        )
        policy = ArchetypePolicy(seed=11, archetype=Archetype.AGGRESSIVE)
        self.assertEqual(
            policy.choose_target(state, actor, view),
            wolf.player_id,
        )

    def test_chaotic_target_is_seed_deterministic(self) -> None:
        state = create_game(seed=3, human_count=0)
        state.phase = Phase.VOTE
        state.day = 1
        actor = next(
            player
            for player in state.players
            if player.role is Role.VILLAGER
        )
        targets = [
            player.player_id
            for player in state.players
            if player.player_id != actor.player_id
        ]
        view = ActionView(
            action="vote",
            label="投票",
            target_ids=targets,
            requires_target=True,
        )
        first = ArchetypePolicy(seed=3, archetype=Archetype.CHAOTIC)
        second = ArchetypePolicy(seed=3, archetype=Archetype.CHAOTIC)
        self.assertEqual(
            first.choose_target(state, actor, view),
            second.choose_target(state, actor, view),
        )


if __name__ == "__main__":
    import unittest

    unittest.main()
