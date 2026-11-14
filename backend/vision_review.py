"""Screenshot review: audit a user-confirmed transcript of a game screenshot.

Without a paid vision API or a bundled OCR model, the reliable offline path is
human-in-the-loop: the user uploads the screenshot and confirms the speech
lines, then the deterministic logic auditor flags contradictions. The image is
still part of the review flow (preview + evidence), and the analysis is done
by the same whitelisted rules the live game uses.
"""

from __future__ import annotations

from collections import Counter
import re
from typing import Any

from .logic_audit import (
    contradicts_own_report,
    impossible_seer_claim_in_text,
    mentions_two_nights_on_day_one,
)
from .public_signals import parse_speech


_PREFIX = re.compile(r"(\d{1,2})\s*号?\s*[:：]\s*(.+)")


def review_transcript(lines: list[str], *, day: int = 1) -> dict[str, Any]:
    """Return a structured, auditable review of a screenshot transcript."""

    findings: list[dict[str, Any]] = []
    claims: dict[int, set[str]] = {}
    accusations: Counter = Counter()
    reports: dict[int, str] = {}

    for raw in lines:
        text = raw.strip()
        if not text:
            continue
        speaker: int | None = None
        body = text
        match = _PREFIX.match(text)
        if match:
            speaker = int(match.group(1))
            body = match.group(2).strip()

        found_claims, found_accusations, found_reports = parse_speech(body)
        if speaker is not None:
            claims.setdefault(speaker, set()).update(found_claims)
        for seat, count in found_accusations.items():
            if seat != speaker:
                accusations[seat] += count
        reports.update(found_reports)

        if impossible_seer_claim_in_text(body, day):
            findings.append(
                {
                    "kind": "impossible_seer_checks",
                    "speaker_seat": speaker,
                    "detail": f"{body}：一晚报多个查验，违反硬规则",
                }
            )
        if contradicts_own_report(body):
            findings.append(
                {
                    "kind": "report_vs_vote",
                    "speaker_seat": speaker,
                    "detail": f"{body}：金水反投，前后矛盾",
                }
            )
        if mentions_two_nights_on_day_one(body, day):
            findings.append(
                {
                    "kind": "two_nights_day_one",
                    "speaker_seat": speaker,
                    "detail": f"{body}：第一天提到两晚查验",
                }
            )

    role_flips = [
        {
            "kind": "role_flip",
            "speaker_seat": seat,
            "detail": f"{seat}号自报多个神职：{'、'.join(sorted(claimed))}",
        }
        for seat, claimed in claims.items()
        if len(claimed) >= 2
    ]

    return {
        "day": day,
        "transcript": lines,
        "findings": role_flips + findings,
        "claims": {str(seat): sorted(values) for seat, values in claims.items()},
        "top_accused": [
            {"seat": seat, "count": count}
            for seat, count in accusations.most_common(5)
        ],
        "reports": {str(seat): result for seat, result in reports.items()},
    }


__all__ = ["review_transcript"]
