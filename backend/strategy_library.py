"""Local, auditable strategy library with safe candidate promotion."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import sys
from typing import Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .game_engine import PHASE_ORDER, Role


StrategyStatus = Literal["seed", "candidate", "validated", "rejected"]
SourceType = Literal[
    "team",
    "rule_doc",
    "offline_research",
    "agent_observation",
]


class StrategyError(ValueError):
    """Raised when the local strategy library cannot safely proceed."""


class StrategyCard(BaseModel):
    """One retrievable tactical instruction."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: Literal[1] = 1
    strategy_id: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,79}$",
    )
    title: str = Field(min_length=1, max_length=120)
    role: Literal["werewolf", "villager", "seer", "witch", "hunter"]
    phase: str = Field(min_length=1, max_length=64)
    action: str = Field(min_length=1, max_length=64)
    trigger: str = Field(min_length=1, max_length=600)
    recommendation: str = Field(min_length=1, max_length=600)
    rationale: str = Field(min_length=1, max_length=1000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    source_type: SourceType
    source: str = Field(min_length=1, max_length=500)
    status: StrategyStatus
    version: str = Field(default="v1", min_length=1, max_length=32)
    samples: int = Field(default=0, ge=0)
    win_rate: float | None = Field(default=None, ge=0, le=1)
    interval: tuple[float, float] | None = None
    created_by: str = Field(min_length=1, max_length=64)
    created_at: str = Field(min_length=1, max_length=64)
    evaluation: dict[str, object] | None = None

    @model_validator(mode="after")
    def validate_metrics_and_phase(self):
        phase_values = {phase.value for phase in PHASE_ORDER}
        if self.phase != "ANY" and self.phase not in phase_values:
            raise ValueError(f"未知阶段：{self.phase}")
        if self.win_rate is not None and self.samples <= 0:
            raise ValueError("没有真实样本时不能填写 win_rate")
        if self.interval is not None:
            low, high = self.interval
            if not 0 <= low <= high <= 1:
                raise ValueError("interval 必须是 0 到 1 的有序二元组")
            if self.win_rate is None or self.samples <= 0:
                raise ValueError("没有真实胜率和样本时不能填写 interval")
        return self

    @property
    def searchable_text(self) -> str:
        return " ".join(
            (
                self.title,
                self.role,
                self.phase,
                self.action,
                self.trigger,
                self.recommendation,
                self.rationale,
                " ".join(self.tags),
            )
        ).lower()


class PromotionEvidence(BaseModel):
    """Human-approved evidence required before a candidate can be validated."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    reviewer: str = Field(min_length=1, max_length=64)
    approved: bool
    baseline_policy: str = Field(min_length=1, max_length=32)
    candidate_policy: str = Field(min_length=1, max_length=32)
    seed_start: int = Field(ge=0)
    seed_end: int = Field(ge=0)
    sample_size: int = Field(ge=200)
    baseline_run_id: str = Field(min_length=1, max_length=160)
    candidate_run_id: str = Field(min_length=1, max_length=160)
    baseline_manifest_sha256: str = Field(
        pattern=r"^[a-fA-F0-9]{64}$",
    )
    candidate_manifest_sha256: str = Field(
        pattern=r"^[a-fA-F0-9]{64}$",
    )
    notes: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def validate_review(self):
        if not self.approved:
            raise ValueError("未批准的评测不能晋升策略")
        if self.reviewer.strip().lower() in {"ai", "agent", "model"}:
            raise ValueError("晋升必须由人工审核者确认")
        if self.seed_end < self.seed_start:
            raise ValueError("seed_end 不能小于 seed_start")
        if self.sample_size < self.seed_end - self.seed_start + 1:
            raise ValueError("sample_size 与 seed 范围不一致")
        return self


class StrategyMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    card: StrategyCard
    score: float
    matched_terms: list[str]


def _normalise_term(value: str) -> str:
    return re.sub(r"\s+", "", value).lower()


def _tokens(value: str) -> set[str]:
    lowered = value.lower()
    tokens = set(re.findall(r"[a-z0-9_]{2,}", lowered))
    for sequence in re.findall(r"[\u4e00-\u9fff]+", lowered):
        tokens.add(sequence)
        if len(sequence) > 1:
            tokens.update(
                sequence[index : index + 2]
                for index in range(len(sequence) - 1)
            )
    return tokens


class StrategyLibrary:
    """Read seed/validated tactics and isolate AI-generated candidates."""

    folders: dict[StrategyStatus, str] = {
        "seed": "seeds",
        "candidate": "candidates",
        "validated": "validated",
        "rejected": "rejected",
    }

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        for folder in self.folders.values():
            (self.root / folder).mkdir(parents=True, exist_ok=True)

    def load(self, status: StrategyStatus) -> list[StrategyCard]:
        folder = self.root / self.folders[status]
        cards: list[StrategyCard] = []
        seen: set[str] = set()
        for path in sorted(folder.glob("*.json")):
            try:
                card = StrategyCard.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
            except Exception as exc:
                raise StrategyError(f"策略文件无效：{path}: {exc}") from exc
            if card.status != status:
                raise StrategyError(
                    f"策略 {card.strategy_id} 状态 {card.status} "
                    f"与目录 {status} 不一致"
                )
            if card.strategy_id in seen:
                raise StrategyError(f"重复策略 ID：{card.strategy_id}")
            seen.add(card.strategy_id)
            cards.append(card)
        return cards

    def search(
        self,
        query: str = "",
        *,
        role: str | None = None,
        phase: str | None = None,
        limit: int = 5,
        include_candidates: bool = False,
    ) -> list[StrategyMatch]:
        if limit <= 0:
            raise ValueError("limit 必须大于 0")
        statuses: tuple[StrategyStatus, ...] = ("seed", "validated")
        if include_candidates:
            statuses += ("candidate",)
        cards = [
            card
            for status in statuses
            for card in self.load(status)
        ]
        query_terms = _tokens(query)
        ranked: list[StrategyMatch] = []
        for card in cards:
            if role is not None and card.role != role:
                continue
            if phase is not None and card.phase not in {"ANY", phase}:
                continue
            card_terms = _tokens(card.searchable_text)
            matched = sorted(query_terms & card_terms)
            score = float(len(matched))
            if role:
                score += 5.0
            if phase and card.phase == phase:
                score += 4.0
            if query and not matched:
                continue
            ranked.append(
                StrategyMatch(
                    card=card,
                    score=score,
                    matched_terms=matched,
                )
            )
        ranked.sort(key=lambda item: (-item.score, item.card.strategy_id))
        return ranked[:limit]

    def record_candidate(self, card: StrategyCard) -> Path:
        if card.status != "candidate":
            card = card.model_copy(update={"status": "candidate"})
        if card.win_rate is not None:
            raise StrategyError("候选策略不能带有未经评测的胜率")
        for status in ("seed", "validated", "candidate", "rejected"):
            if any(
                existing.strategy_id == card.strategy_id
                for existing in self.load(status)
            ):
                raise StrategyError(f"策略 ID 已存在：{card.strategy_id}")
        target = self.root / self.folders["candidate"] / f"{card.strategy_id}.json"
        target.write_text(
            card.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        return target

    def promote_candidate(
        self,
        strategy_id: str,
        evidence: PromotionEvidence,
    ) -> StrategyCard:
        candidates = {
            card.strategy_id: card for card in self.load("candidate")
        }
        if strategy_id not in candidates:
            raise StrategyError(f"候选策略不存在：{strategy_id}")
        card = candidates[strategy_id].model_copy(
            update={
                "status": "validated",
                "evaluation": evidence.model_dump(),
            }
        )
        source = (
            self.root / self.folders["candidate"] / f"{strategy_id}.json"
        )
        target = (
            self.root / self.folders["validated"] / f"{strategy_id}.json"
        )
        target.write_text(
            card.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        source.unlink()
        return card


def card_from_file(path: Path) -> StrategyCard:
    try:
        return StrategyCard.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise StrategyError(f"策略文件无效：{path}: {exc}") from exc


def evidence_from_file(path: Path) -> PromotionEvidence:
    try:
        return PromotionEvidence.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except Exception as exc:
        raise StrategyError(f"晋升证据无效：{path}: {exc}") from exc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="WolfArena local strategy library",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("strategy_library"),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    search = subparsers.add_parser("search")
    search.add_argument("--query", default="")
    search.add_argument("--role", choices=[role.value for role in Role])
    search.add_argument("--phase")
    search.add_argument("--limit", type=int, default=5)

    add = subparsers.add_parser("add-candidate")
    add.add_argument("--file", type=Path, required=True)

    promote = subparsers.add_parser("promote")
    promote.add_argument("--strategy-id", required=True)
    promote.add_argument("--evidence", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    library = StrategyLibrary(args.root)
    try:
        if args.command == "search":
            matches = library.search(
                args.query,
                role=args.role,
                phase=args.phase,
                limit=args.limit,
            )
            print(
                json.dumps(
                    [match.model_dump(mode="json") for match in matches],
                    ensure_ascii=False,
                    indent=2,
                )
            )
        elif args.command == "add-candidate":
            path = library.record_candidate(card_from_file(args.file))
            print(str(path))
        else:
            card = library.promote_candidate(
                args.strategy_id,
                evidence_from_file(args.evidence),
            )
            print(json.dumps(card.model_dump(mode="json"), ensure_ascii=False, indent=2))
    except StrategyError as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
