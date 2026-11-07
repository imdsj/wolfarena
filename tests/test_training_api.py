"""Tests for the training-ground skeleton endpoints and rollout."""

from __future__ import annotations

from unittest import TestCase

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.rooms import InMemoryRoomRepository
from backend.training import wilson_interval


class TrainingApiTests(TestCase):
    def setUp(self) -> None:
        self.client = TestClient(create_app(InMemoryRoomRepository()))

    def test_models_endpoint_lists_four_fixed_ids(self) -> None:
        response = self.client.get("/api/training/models")
        self.assertEqual(response.status_code, 200, response.text)
        ids = [model["model_id"] for model in response.json()["models"]]
        self.assertEqual(
            ids,
            [
                "l0.random.v1",
                "l1.rules.v1",
                "l2.qtable.v1",
                "l2.qtable.v2",
            ],
        )

    def test_unknown_model_is_rejected(self) -> None:
        response = self.client.get("/api/training/models/not-a-model")
        self.assertEqual(response.status_code, 404)

    def test_metrics_endpoint_matches_frozen_evidence(self) -> None:
        response = self.client.get("/api/training/metrics")
        self.assertEqual(response.status_code, 200, response.text)
        by_id = {
            row["model_id"]: row for row in response.json()["metrics"]
        }
        self.assertEqual(len(by_id), 4)

        l1 = by_id["l1.rules.v1"]
        self.assertEqual(l1["samples"], 200)
        self.assertAlmostEqual(l1["good_win_rate"], 0.16, places=3)
        self.assertIs(l1["no_go"], False)

        l2v2 = by_id["l2.qtable.v2"]
        self.assertEqual(l2v2["samples"], 200)
        self.assertAlmostEqual(l2v2["good_win_rate"], 0.35, places=3)
        self.assertIs(l2v2["no_go"], True)

        single = self.client.get(
            "/api/training/metrics",
            params={"model_id": "l2.qtable.v2"},
        )
        self.assertEqual(single.status_code, 200)
        self.assertEqual(single.json()["model_id"], "l2.qtable.v2")

    def test_metrics_unknown_model_is_rejected(self) -> None:
        response = self.client.get(
            "/api/training/metrics",
            params={"model_id": "missing"},
        )
        self.assertEqual(response.status_code, 404)

    def test_rollout_is_deterministic_and_reports_interval(self) -> None:
        params = {
            "policy": "l0",
            "seed_start": 1000,
            "games": 8,
        }
        first = self.client.get("/api/training/rollout", params=params).json()
        second = self.client.get("/api/training/rollout", params=params).json()

        self.assertEqual(first["good_win_rate"], second["good_win_rate"])
        self.assertEqual(first["winners"], second["winners"])
        self.assertEqual(first["delta_good_win_rate"], 0.0)
        self.assertEqual(len(first["confidence_interval_95"]), 2)
        self.assertGreaterEqual(first["good_win_rate"], 0.0)
        self.assertLessEqual(first["good_win_rate"], 1.0)

    def test_rollout_rejects_invalid_arguments(self) -> None:
        for params in (
            {"policy": "nope", "seed_start": 0, "games": 5},
            {"policy": "l0", "seed_start": 0, "games": 0},
            {"policy": "l0", "seed_start": 0, "games": 101},
            {"policy": "l0", "seed_start": -1, "games": 5},
        ):
            response = self.client.get(
                "/api/training/rollout",
                params=params,
            )
            self.assertEqual(response.status_code, 422, params)


class WilsonIntervalTests(TestCase):
    def test_interval_is_inside_unit_range_and_symmetric(self) -> None:
        low, high = wilson_interval(10, 20)
        self.assertLessEqual(low, 0.5)
        self.assertGreaterEqual(high, 0.5)
        self.assertGreaterEqual(low, 0.0)
        self.assertLessEqual(high, 1.0)

    def test_zero_samples_spans_full_range(self) -> None:
        self.assertEqual(wilson_interval(0, 0), (0.0, 1.0))
