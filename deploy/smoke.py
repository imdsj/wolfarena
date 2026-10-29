"""部署后冒烟检查：健康检查、首页、建房、玩家/观战 WebSocket、错误令牌拒绝。

用法（在服务器上用项目 venv 运行，需要 websockets 依赖）：

    ./.venv/bin/python deploy/smoke.py http://127.0.0.1:8001
    ./.venv/bin/python deploy/smoke.py http://<公网地址>:8080
"""

from __future__ import annotations

import asyncio
import json
import sys
import urllib.error
import urllib.request

import websockets


def http_json(base: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        base.rstrip("/") + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.status, json.loads(response.read())


async def ws_probe(ws_base: str, room_id: str, payload: dict, label: str) -> bool:
    async with websockets.connect(
        f"{ws_base}/ws/rooms/{room_id}", open_timeout=10
    ) as socket:
        await socket.send(json.dumps(payload))
        message = json.loads(await asyncio.wait_for(socket.recv(), 10))
    ok = message.get("type") == "authenticated"
    print(f"  {label}: {'ok' if ok else 'FAIL'} ({message.get('type')})")
    return ok


async def run(base: str) -> int:
    failures: list[str] = []

    status, health = http_json(base, "/health")
    ok_health = status == 200 and health.get("status") == "ok"
    print(f"health: {'ok' if ok_health else 'FAIL'} {health}")
    if not ok_health:
        failures.append("health")

    with urllib.request.urlopen(base.rstrip("/") + "/", timeout=15) as response:
        html = response.read().decode("utf-8", "replace")
    ok_home = response.status == 200 and "<html" in html.lower()
    print(f"home: {'ok' if ok_home else 'FAIL'} bytes={len(html)}")
    if not ok_home:
        failures.append("home")

    status, room = http_json(
        base,
        "/api/rooms",
        {"nickname": "SmokeA", "human_count": 1, "max_humans": 1},
    )
    ok_room = status == 201 and room.get("player_token")
    print(f"create_room: {'ok' if ok_room else 'FAIL'} status={status}")
    if not ok_room:
        print("room 创建失败，后续 WebSocket 检查跳过")
        return 1

    ws_base = base.replace("https://", "wss://").replace("http://", "ws://")
    room_id = room["room_id"]
    if not await ws_probe(
        ws_base, room_id, {"type": "authenticate", "token": room["player_token"]}, "ws_player"
    ):
        failures.append("ws_player")
    if not await ws_probe(
        ws_base,
        room_id,
        {
            "type": "authenticate",
            "spectator_password": room["spectator_password"],
        },
        "ws_spectator",
    ):
        failures.append("ws_spectator")

    async with websockets.connect(
        f"{ws_base}/ws/rooms/{room_id}", open_timeout=10
    ) as socket:
        await socket.send(json.dumps({"type": "authenticate", "token": "wrong"}))
        reply = json.loads(await asyncio.wait_for(socket.recv(), 10))
    ok_reject = reply.get("type") == "error"
    print(f"ws_bad_token: {'ok (rejected)' if ok_reject else 'FAIL'}")
    if not ok_reject:
        failures.append("ws_bad_token")

    if failures:
        print("FAILED:", ", ".join(failures))
        return 1
    print("ALL CHECKS PASSED")
    return 0


def main() -> int:
    base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8001"
    print(f"target: {base}")
    try:
        return asyncio.run(run(base))
    except (urllib.error.URLError, OSError) as error:
        print(f"FAILED: 无法连接 {base} ({error})")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
