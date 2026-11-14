"""Explainable public-information win-rate estimates.

The baseline consumes only events whose visibility is ``public``. DeepSeek
receives the same redacted transcript, never seat roles, wolf chat, night
targets or private checks. A model failure is labelled as a statistical
fallback instead of being presented as a model prediction.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import math
from typing import Any

import httpx

from .ai_provider import DeepSeekSettings
from .game_engine import EventType, GameState, Visibility
from .llm_budget import LEDGER
from .logic_audit import admits_deception
from .public_signals import parse_speech


PREDICTION_EVENTS = frozenset(
    {
        EventType.PUBLIC_SPEECH,
        EventType.VOTE_RESULT,
        EventType.PLAYER_DIED,
        EventType.SELF_DESTRUCTED,
        EventType.HUNTER_SHOT,
        EventType.WINNER_DECIDED,
    }
)


def _clamp(value: float) -> float:
    return min(0.95, max(0.05, value))


def _seat_map(state: GameState) -> dict[str, int]:
    return {player.player_id: player.seat for player in state.players}


def _event_label(event, seats: dict[str, int]) -> str:
    actor = seats.get(str(event.actor_id))
    target = seats.get(str(event.target_id))
    if event.event_type is EventType.PUBLIC_SPEECH:
        return f"{actor or '?'}号公开发言"
    if event.event_type is EventType.VOTE_RESULT:
        return f"投票结果：{target or '?'}号被放逐" if target else "投票结果：平局"
    if event.event_type is EventType.PLAYER_DIED:
        return f"{target or '?'}号出局"
    if event.event_type is EventType.SELF_DESTRUCTED:
        return f"{actor or '?'}号狼人自爆"
    if event.event_type is EventType.HUNTER_SHOT:
        return f"{actor or '?'}号猎人开枪 → {target or '?'}号"
    if event.event_type is EventType.WINNER_DECIDED:
        return "对局结果确认"
    return event.event_type.value


def baseline_timeline(state: GameState) -> list[dict[str, Any]]:
    """Replay public evidence into a deterministic, explainable curve."""

    seats = _seat_map(state)
    score = 0.0
    previous = 0.5
    timeline: list[dict[str, Any]] = []
    reported_wolves: set[int] = set()
    accused: set[int] = set()

    for event in state.events:
        if event.visibility is not Visibility.PUBLIC:
            continue
        if event.event_type not in PREDICTION_EVENTS:
            continue
        delta = 0.0
        drivers: list[str] = []
        actor = seats.get(str(event.actor_id))
        target = seats.get(str(event.target_id))

        if event.event_type is EventType.PUBLIC_SPEECH:
            content = str(event.data.get("content") or "")
            claims, accusations, reports = parse_speech(content)
            if "seer" in claims and reports:
                for seat, result in reports.items():
                    if result == "wolf":
                        reported_wolves.add(seat)
                        delta += 0.015
                        drivers.append(f"公开查杀指向{seat}号，为归票提供可检验线索")
                    else:
                        drivers.append(f"{seat}号金水仍需后续票型验证")
            if accusations:
                accused.update(accusations)
            if admits_deception(content):
                delta += 0.04
                drivers.append("发言自认伪装，公开矛盾降低其阵营可信度")
            if not drivers:
                drivers.append("发言已记录，未出现足以调整胜率的公开硬证据")

        elif event.event_type is EventType.VOTE_RESULT:
            banished = seats.get(str(event.data.get("banished_id")))
            if banished is not None:
                if banished in reported_wolves:
                    delta += 0.025
                    drivers.append(f"被公开查杀的{banished}号被放逐，归票线索兑现")
                elif banished in accused:
                    delta += 0.01
                    drivers.append(f"高嫌疑的{banished}号被放逐，但身份仍待结果验证")
                else:
                    delta -= 0.015
                    drivers.append(f"{banished}号缺少公开硬证据却被放逐，误伤风险上升")
            else:
                drivers.append("投票平局，阵营信息没有实质性推进")

        elif event.event_type is EventType.PLAYER_DIED:
            causes = set(event.data.get("causes") or ())
            if "wolf_kill" in causes:
                delta -= 0.015
                drivers.append("夜间减员压缩好人轮次")
            elif not causes & {"banished", "hunter_shot", "self_destruct"}:
                drivers.append("减员已记录，公开信息不足以确认其阵营")

        elif event.event_type is EventType.SELF_DESTRUCTED:
            delta += 0.1
            drivers.append("自爆公开确认一张狼人牌出局")

        elif event.event_type is EventType.HUNTER_SHOT:
            if target in reported_wolves or target in accused:
                delta += 0.02
                drivers.append("猎人带走已有公开嫌疑的目标")
            elif target is not None:
                delta -= 0.02
                drivers.append("猎人带走缺少公开嫌疑的目标，误伤风险上升")

        elif event.event_type is EventType.WINNER_DECIDED:
            winner = event.data.get("winner")
            score = 0.45 if winner == "good" else -0.45
            drivers.append("胜负已由规则引擎确认，不再是概率估计")

        score = max(-0.45, min(0.45, score + delta))
        good = 1.0 if event.event_type is EventType.WINNER_DECIDED and score > 0 else (
            0.0 if event.event_type is EventType.WINNER_DECIDED else _clamp(0.5 + score)
        )
        timeline.append(
            {
                "event_seq": event.event_seq,
                "day": event.day,
                "phase": event.phase.value,
                "event_type": event.event_type.value,
                "label": _event_label(event, seats),
                "good": round(good, 4),
                "wolf": round(1.0 - good, 4),
                "delta": round(good - previous, 4),
                "drivers": drivers[:3],
                "actor_seat": actor,
                "target_seat": target,
            }
        )
        previous = good
    return timeline


def public_transcript(state: GameState, event_seq: int) -> str:
    """A redacted public transcript suitable for the external predictor."""

    seats = _seat_map(state)
    lines: list[str] = []
    for event in state.events:
        if event.event_seq > event_seq:
            break
        if event.visibility is not Visibility.PUBLIC:
            continue
        if event.event_type not in PREDICTION_EVENTS:
            continue
        label = _event_label(event, seats)
        detail = ""
        if event.event_type is EventType.PUBLIC_SPEECH:
            detail = str(event.data.get("content") or "")[:180]
        elif event.event_type is EventType.VOTE_RESULT:
            raw_votes = event.data.get("votes") or {}
            votes = [
                f"{seats.get(str(voter), '?')}→{seats.get(str(target), '弃权') if target else '弃权'}"
                for voter, target in raw_votes.items()
            ]
            detail = "；".join(votes)
        elif event.event_type is EventType.WINNER_DECIDED:
            detail = str(event.data.get("winner") or "")
        lines.append(f"第{event.day}天 #{event.event_seq} {label} {detail}".strip())
    return "\n".join(lines[-40:])


def _deepseek_estimate(
    *,
    transcript: str,
    baseline_good: float,
    settings: DeepSeekSettings,
) -> dict[str, Any]:
    system = (
        "你是狼人杀公开信息胜率评估器。你不知道任何玩家的真实身份，"
        "只能使用用户给出的公开事件。身份自报和查杀都只是声明，不是事实。"
        "评估好人阵营最终胜率，输出严格 JSON："
        '{"good_win_rate":0.5,"reason":"不超过80字","drivers":["因素1","因素2"]}。'
        "good_win_rate 必须在0.05到0.95之间，drivers最多3条，不得编造身份。"
    )
    user = (
        f"统计基线好人胜率：{baseline_good:.3f}。\n"
        f"公开事件：\n{transcript or '暂无'}\n"
        "请给出你的独立判断和主要依据。"
    )
    with httpx.Client(timeout=settings.timeout_seconds) as client:
        response = client.post(
            f"{settings.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.2,
                "max_tokens": 240,
            },
        )
        response.raise_for_status()
        body = response.json()
        LEDGER.record(
            source="win_rate",
            usage=body.get("usage"),
            prompt_chars=len(system) + len(user),
            completion_chars=len(str(body["choices"][0]["message"]["content"])),
        )
    payload = json.loads(body["choices"][0]["message"]["content"])
    value = payload.get("good_win_rate")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("model_win_rate_invalid")
    if not math.isfinite(float(value)) or not 0.05 <= float(value) <= 0.95:
        raise ValueError("model_win_rate_out_of_range")
    reason = " ".join(str(payload.get("reason") or "").split())[:160]
    drivers = [
        " ".join(str(item).split())[:100]
        for item in (payload.get("drivers") or [])
        if str(item).strip()
    ][:3]
    return {
        "good": float(value),
        "reason": reason or "大模型已根据公开事件给出判断",
        "drivers": drivers,
    }


def predict_win_rate(
    state: GameState,
    event_seq: int,
    *,
    settings: DeepSeekSettings | None = None,
) -> dict[str, Any]:
    """Blend the statistical baseline with a labelled DeepSeek estimate."""

    points = [
        point for point in baseline_timeline(state)
        if point["event_seq"] <= event_seq
    ]
    point = next((item for item in points if item["event_seq"] == event_seq), None)
    if point is None:
        raise ValueError("该事件不是可预测的公开事件")
    transcript = public_transcript(state, event_seq)
    baseline_good = float(point["good"])
    result: dict[str, Any] = {
        **point,
        "baseline_good": baseline_good,
        "llm_good": None,
        "source": "statistical_fallback",
        "model": None,
        "reason": "当前使用可复现统计模型",
        "transcript_sha256": hashlib.sha256(transcript.encode()).hexdigest(),
        "created_at": datetime.now(UTC).isoformat(),
    }
    if point["event_type"] == EventType.WINNER_DECIDED.value:
        result.update(source="result_confirmed", reason="胜负已由规则引擎确认")
        return result

    config = settings or DeepSeekSettings.from_environment()
    if not config.api_key:
        result["reason"] = "未配置大模型密钥，当前为统计模型回退"
        return result
    try:
        estimate = _deepseek_estimate(
            transcript=transcript,
            baseline_good=baseline_good,
            settings=config,
        )
    except Exception:
        LEDGER.record_failure()
        result["reason"] = "大模型调用失败，当前为统计模型回退"
        return result

    combined = 0.35 * baseline_good + 0.65 * estimate["good"]
    result.update(
        good=round(combined, 4),
        wolf=round(1.0 - combined, 4),
        delta=round(combined - baseline_good, 4),
        llm_good=round(estimate["good"], 4),
        source="deepseek_hybrid",
        model=config.model,
        reason=estimate["reason"],
        drivers=estimate["drivers"] or point["drivers"],
    )
    return result


__all__ = [
    "PREDICTION_EVENTS",
    "baseline_timeline",
    "predict_win_rate",
    "public_transcript",
]
