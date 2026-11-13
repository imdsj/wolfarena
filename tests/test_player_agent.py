"""Tests for the independent per-seat agent model."""

from __future__ import annotations

from unittest import TestCase

from backend.game_engine import create_game
from backend.personas import Archetype, ArchetypePolicy
from backend.player_agent import DecisionTrace, PlayerAgent, build_agents
from backend.rooms import InMemoryRoomRepository


class PlayerAgentTests(TestCase):
    def test_build_agents_covers_every_ai_seat(self) -> None:
        state = create_game(seed=1, human_count=0)
        self.assertEqual(len(build_agents(state, ())), 9)

    def test_build_agents_skips_human_seats(self) -> None:
        state = create_game(seed=1, human_count=1)
        self.assertEqual(len(build_agents(state, ())), 8)

    def test_record_appends_a_trace(self) -> None:
        agent = PlayerAgent(
            player_id="p1",
            persona=Archetype.LOGICAL,
            policy=ArchetypePolicy(seed=1, archetype=Archetype.LOGICAL),
        )
        agent.record(
            day=1,
            phase="VOTE",
            action="vote",
            target_id="p3",
            choice=None,
            strategy_id="l1.persona.logical",
            tool_calls=[
                {"name": "search_tactics", "tactic_ids": ["good.read-vote-blocs"]}
            ],
            tactic_ids=["good.read-vote-blocs"],
        )
        self.assertEqual(len(agent.decision_traces), 1)
        self.assertEqual(
            agent.decision_traces[0].tactic_ids,
            ["good.read-vote-blocs"],
        )

    def test_trace_as_dict_is_serializable(self) -> None:
        trace = DecisionTrace(
            day=1,
            phase="VOTE",
            action="vote",
            target_id="p3",
            choice=None,
            persona="logical",
            strategy_id="l1.persona.logical",
        )
        self.assertEqual(trace.as_dict()["action"], "vote")


class RoomAgentIntegrationTests(TestCase):
    def test_snapshot_exposes_archetype_and_spectator_insights(self) -> None:
        repository = InMemoryRoomRepository()
        created = repository.create_room(
            seed=10,
            human_count=1,
            max_humans=3,
            nickname="宿主",
        )
        ai_players = [
            player for player in created.room.players if not player.is_human
        ]
        self.assertEqual(len(ai_players), 8)
        self.assertTrue(all(player.archetype for player in ai_players))
        # A player does not see agent internals before the game ends.
        self.assertEqual(created.room.agent_insights, [])

        spectator = repository.authenticate_spectator(
            created.room_id,
            created.spectator_password,
        )
        self.assertEqual(len(spectator.snapshot.agent_insights), 8)


if __name__ == "__main__":
    import unittest

    unittest.main()
