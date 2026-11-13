"""Tests for the whitelisted agent tools."""

from __future__ import annotations

from unittest import TestCase

from backend.agent_tools import (
    TOOL_DEFINITIONS,
    TOOL_NAMES,
    analyze_votes,
    audit_logic,
    execute_tool,
    search_tactics,
)
from backend.game_engine import Role, create_game


class AgentToolsTests(TestCase):
    def setUp(self) -> None:
        self.state = create_game(seed=5, human_count=0)
        self.actor = next(
            player
            for player in self.state.players
            if player.role is Role.VILLAGER
        )

    def test_tool_definitions_match_names(self) -> None:
        names = {definition["function"]["name"] for definition in TOOL_DEFINITIONS}
        self.assertEqual(names, set(TOOL_NAMES))

    def test_unknown_tool_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            execute_tool("remove_all", {}, self.state, self.actor)

    def test_parameters_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            execute_tool("audit_logic", {"path": "/etc"}, self.state, self.actor)

    def test_audit_logic_shape(self) -> None:
        result = audit_logic(self.state, self.actor)
        self.assertIn("findings", result)
        self.assertIn("strongest", result)

    def test_analyze_votes_shape(self) -> None:
        result = analyze_votes(self.state, self.actor)
        self.assertIn("summary", result)

    def test_search_tactics_returns_sourced_cards(self) -> None:
        result = search_tactics(self.state, self.actor)
        self.assertIn("tactics", result)
        for tactic in result["tactics"]:
            self.assertIn("strategy_id", tactic)
            self.assertIn("source", tactic)


if __name__ == "__main__":
    import unittest

    unittest.main()
