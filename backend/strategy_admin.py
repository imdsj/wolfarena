"""HTTP-facing strategy laboratory: submit, evaluate, approve, reject, rollback.

Every mutation stays inside the local strategy library's existing security
boundary: user cards land in ``candidates/``, only whitelisted directives may
be auto-executed, promotion still requires the paired 200-game evidence, and
approve/reject/rollback require a shared reviewer secret.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import hmac
import json
from pathlib import Path
from typing import Any

from .promote import approve_candidate, evaluate_and_route
from .strategy_library import StrategyCard, StrategyError, StrategyLibrary


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STRATEGY_ROOT = PROJECT_ROOT / "strategy_library"
DEFAULT_EVIDENCE_ROOT = PROJECT_ROOT / "training_runs" / "promotions"


def reviewer_authorized(
    header_token: str | None,
    env_token: str | None,
) -> bool:
    """Approve/reject/rollback require a configured, non-empty shared secret."""

    if not env_token or not header_token:
        return False
    return hmac.compare_digest(header_token, env_token)


def _user_strategy_id(title: str, created_by: str) -> str:
    digest = hashlib.sha1(
        f"{title}\x00{created_by}\x00{datetime.now(UTC).isoformat()}".encode()
    ).hexdigest()
    return f"cand.user.{digest[:10]}"


def _card_summary(card: StrategyCard) -> dict[str, Any]:
    return {
        "strategy_id": card.strategy_id,
        "title": card.title,
        "role": card.role,
        "phase": card.phase,
        "action": card.action,
        "trigger": card.trigger,
        "recommendation": card.recommendation,
        "rationale": card.rationale,
        "risk": card.risk,
        "evidence_level": card.evidence_level,
        "source": card.source,
        "status": card.status,
        "directive": card.directive,
        "created_by": card.created_by,
        "created_at": card.created_at,
        "samples": card.samples,
        "win_rate": card.win_rate,
        "evaluation": card.evaluation,
        "tags": list(card.tags),
    }


def submit_candidate(
    payload: dict[str, Any],
    *,
    strategy_root: Path | None = None,
) -> dict[str, Any]:
    """Validate and record a user-submitted tactic as a candidate."""

    root = strategy_root or DEFAULT_STRATEGY_ROOT
    strategy_id = _user_strategy_id(
        payload["title"],
        payload["created_by"],
    )
    card = StrategyCard(
        strategy_id=strategy_id,
        title=payload["title"],
        role=payload["role"],
        phase=payload.get("phase") or "ANY",
        action=payload["action"],
        trigger=payload["trigger"],
        recommendation=payload["recommendation"],
        rationale=payload["rationale"],
        risk=payload["risk"],
        evidence_level="untested",
        tags=[],
        source_type="team",
        source="网页策略实验室提交",
        status="candidate",
        directive=payload.get("directive"),
        created_by=payload["created_by"],
        created_at=datetime.now(UTC).isoformat(),
    )
    StrategyLibrary(root).record_candidate(card)
    return _card_summary(card)


def list_library(*, strategy_root: Path | None = None) -> dict[str, Any]:
    root = strategy_root or DEFAULT_STRATEGY_ROOT
    library = StrategyLibrary(root)
    return {
        "counts": library.counts(),
        "candidates": [
            _card_summary(card) for card in library.load("candidate")
        ],
        "validated": [
            _card_summary(card) for card in library.load("validated")
        ],
        "rejected": [
            _card_summary(card) for card in library.load("rejected")
        ],
    }


def evaluate(
    candidate_id: str,
    *,
    strategy_root: Path | None = None,
    seed_start: int = 7000,
    games: int = 200,
) -> dict[str, Any]:
    """Run the paired comparison and let the gate route the candidate."""

    return evaluate_and_route(
        candidate_id,
        strategy_root=strategy_root or DEFAULT_STRATEGY_ROOT,
        seed_start=seed_start,
        games=games,
    )


def approve(
    candidate_id: str,
    reviewer: str,
    *,
    strategy_root: Path | None = None,
    skip_evaluation: bool = False,
) -> dict[str, Any]:
    return approve_candidate(
        candidate_id,
        reviewer,
        strategy_root=strategy_root or DEFAULT_STRATEGY_ROOT,
        skip_evaluation=skip_evaluation,
    )


def reject(
    candidate_id: str,
    reason: str,
    *,
    strategy_root: Path | None = None,
) -> dict[str, Any]:
    path = StrategyLibrary(
        strategy_root or DEFAULT_STRATEGY_ROOT
    ).reject_candidate(candidate_id, reason)
    return {
        "strategy_id": candidate_id,
        "status": "rejected",
        "reason": reason,
        "path": str(path),
    }


def rollback(
    strategy_id: str,
    reason: str,
    *,
    strategy_root: Path | None = None,
) -> dict[str, Any]:
    path = StrategyLibrary(
        strategy_root or DEFAULT_STRATEGY_ROOT
    ).rollback(strategy_id, reason)
    return {
        "strategy_id": strategy_id,
        "status": "candidate",
        "reason": reason,
        "path": str(path),
    }


def evaluation_for(candidate_id: str) -> dict[str, Any] | None:
    """Return the most recent evaluation evidence for one candidate."""

    out_dir = DEFAULT_EVIDENCE_ROOT / candidate_id.replace("/", "_")
    evaluation_path = out_dir / "evaluation.json"
    if not evaluation_path.is_file():
        return None
    return json.loads(evaluation_path.read_text(encoding="utf-8"))


__all__ = [
    "DEFAULT_STRATEGY_ROOT",
    "approve",
    "evaluate",
    "evaluation_for",
    "list_library",
    "reject",
    "reviewer_authorized",
    "rollback",
    "submit_candidate",
    "StrategyError",
]
