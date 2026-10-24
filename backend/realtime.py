"""WebSocket connection tracking and viewer-scoped broadcasts."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from fastapi import WebSocket

from .rooms import InMemoryRoomRepository, RoomMutation, ViewerAccess


@dataclass(eq=False, slots=True)
class RoomConnection:
    """One authenticated WebSocket subscription."""

    websocket: WebSocket
    access: ViewerAccess
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class RealtimeHub:
    """Tracks room connections and sends only viewer-visible events."""

    def __init__(self, repository: InMemoryRoomRepository) -> None:
        self._repository = repository
        self._connections: dict[str, list[RoomConnection]] = {}
        self._registry_lock = asyncio.Lock()

    async def register(
        self,
        websocket: WebSocket,
        access: ViewerAccess,
    ) -> RoomConnection:
        connection = RoomConnection(websocket=websocket, access=access)
        async with self._registry_lock:
            self._connections.setdefault(access.room_id, []).append(connection)
        return connection

    async def unregister(self, connection: RoomConnection) -> None:
        async with self._registry_lock:
            room_connections = self._connections.get(connection.access.room_id, [])
            if connection in room_connections:
                room_connections.remove(connection)
            if not room_connections:
                self._connections.pop(connection.access.room_id, None)

    async def send(
        self,
        connection: RoomConnection,
        payload: dict[str, object],
    ) -> bool:
        try:
            async with connection.send_lock:
                await connection.websocket.send_json(payload)
            return True
        except Exception:
            await self.unregister(connection)
            return False

    async def broadcast_mutation(self, mutation: RoomMutation) -> None:
        async with self._registry_lock:
            connections = list(
                self._connections.get(mutation.room.room_id, [])
            )

        for connection in connections:
            events = self._repository.visible_events_since(
                mutation.room,
                connection.access,
                mutation.previous_event_seq,
            )
            for event in events:
                sent = await self.send(
                    connection,
                    {
                        "type": "event",
                        **self._repository.serialize_event(event).model_dump(
                            mode="json"
                        ),
                    },
                )
                if not sent:
                    break
            else:
                await self.send(
                    connection,
                    {
                        "type": "phase",
                        "room_id": mutation.room.room_id,
                        "phase": mutation.room.state.phase.value,
                        "day": mutation.room.state.day,
                        "event_seq": mutation.current_event_seq,
                    },
                )
                snapshot = self._repository.snapshot_for_access(
                    mutation.room,
                    connection.access,
                )
                await self.send(
                    connection,
                    {
                        "type": "snapshot",
                        "event_seq": mutation.current_event_seq,
                        "room": snapshot.model_dump(mode="json"),
                    },
                )
