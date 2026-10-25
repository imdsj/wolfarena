<script setup lang="ts">
import { onBeforeUnmount, reactive, ref } from "vue";

import LobbyPanel from "./components/LobbyPanel.vue";
import RoomPanel from "./components/RoomPanel.vue";
import type {
  ActionSubmission,
  AiActionResponse,
  ConnectionState,
  GameEvent,
  RoomSessionResponse,
  RoomSnapshot,
} from "./types";

const busy = ref(false);
const errorMessage = ref("");
const room = ref<RoomSnapshot | null>(null);
const events = ref<GameEvent[]>([]);
const connectionState = ref<ConnectionState>("idle");
const aiNotice = ref("");
const session = reactive({
  roomId: "",
  playerToken: "",
  spectatorPassword: "",
});

let socket: WebSocket | null = null;

function mergeEvents(incoming: GameEvent[]): void {
  const bySequence = new Map<number, GameEvent>();
  for (const event of [...events.value, ...incoming]) {
    bySequence.set(event.event_seq, event);
  }
  events.value = [...bySequence.values()].sort(
    (left, right) => left.event_seq - right.event_seq,
  );
}

async function requestJson<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(path, init);
  const payload = await response.json();
  if (!response.ok) {
    const detail = payload?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : detail?.message ?? `请求失败（${response.status}）`;
    throw new Error(message);
  }
  return payload as T;
}

function applySession(payload: RoomSessionResponse): void {
  session.roomId = payload.room_id;
  session.playerToken = payload.player_token;
  session.spectatorPassword = payload.spectator_password ?? "";
  room.value = payload.room;
  events.value = payload.room.visible_events;
  errorMessage.value = "";
  connectSocket();
}

async function createRoom(nickname: string): Promise<void> {
  busy.value = true;
  errorMessage.value = "";
  try {
    const payload = await requestJson<RoomSessionResponse>("/api/rooms", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        human_count: 1,
        max_humans: 3,
        nickname,
      }),
    });
    applySession(payload);
  } catch (error) {
    errorMessage.value = errorMessageFrom(error);
  } finally {
    busy.value = false;
  }
}

async function joinRoom(payload: {
  roomId: string;
  nickname: string;
}): Promise<void> {
  busy.value = true;
  errorMessage.value = "";
  try {
    const session = await requestJson<RoomSessionResponse>(
      `/api/rooms/${encodeURIComponent(payload.roomId)}/join`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ nickname: payload.nickname }),
      },
    );
    applySession({
      room_id: payload.roomId,
      player_token: session.player_token,
      room: session.room,
    });
  } catch (error) {
    errorMessage.value = errorMessageFrom(error);
  } finally {
    busy.value = false;
  }
}

function connectSocket(): void {
  if (!session.roomId || !session.playerToken) {
    return;
  }
  socket?.close();
  connectionState.value = "connecting";
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const current = new WebSocket(
    `${protocol}//${window.location.host}/ws/rooms/${encodeURIComponent(session.roomId)}`,
  );
  socket = current;

  current.onopen = () => {
    connectionState.value = "authenticating";
    current.send(
      JSON.stringify({
        type: "authenticate",
        token: session.playerToken,
      }),
    );
  };

  current.onmessage = (messageEvent) => {
    let message: unknown;
    try {
      message = JSON.parse(String(messageEvent.data));
    } catch {
      errorMessage.value = "服务器返回了无法解析的 WebSocket 消息";
      return;
    }
    handleServerMessage(message);
  };

  current.onclose = () => {
    if (socket === current) {
      connectionState.value = "disconnected";
      socket = null;
    }
  };

  current.onerror = () => {
    if (socket === current) {
      connectionState.value = "error";
    }
  };
}

function handleServerMessage(message: unknown): void {
  if (!isRecord(message) || typeof message.type !== "string") {
    errorMessage.value = "收到缺少 type 的服务器消息";
    return;
  }

  if (message.type === "authenticated") {
    connectionState.value = "connected";
    return;
  }
  if (message.type === "snapshot" && isRecord(message.room)) {
    room.value = message.room as unknown as RoomSnapshot;
    mergeEvents(message.room.visible_events as GameEvent[]);
    return;
  }
  if (message.type === "phase") {
    if (!room.value) {
      return;
    }
    room.value = {
      ...room.value,
      phase: String(message.phase),
      day: Number(message.day),
    };
    return;
  }
  if (message.type === "event") {
    const event = message as unknown as GameEvent;
    if (Number.isInteger(event.event_seq) && typeof event.event_type === "string") {
      mergeEvents([event]);
    }
    return;
  }
  if (message.type === "action_result") {
    errorMessage.value = "";
    return;
  }
  if (message.type === "error") {
    errorMessage.value = String(message.message ?? "服务器拒绝了操作");
  }
}

async function runAction(action: ActionSubmission): Promise<void> {
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    errorMessage.value = "连接尚未建立，不能提交动作";
    return;
  }
  aiNotice.value = "";
  socket.send(JSON.stringify({ type: "action", ...action }));
}

async function runAiAction(): Promise<void> {
  busy.value = true;
  errorMessage.value = "";
  aiNotice.value = "";
  try {
    const response = await requestJson<AiActionResponse>(
      `/api/rooms/${encodeURIComponent(session.roomId)}/ai-action`,
      {
        method: "POST",
        headers: { "X-Player-Token": session.playerToken },
      },
    );
    const source = response.decision.source;
    aiNotice.value =
      source === "fallback"
        ? `已使用离线兜底（${response.decision.fallback_reason ?? "unknown"}）`
        : `AI 候选已通过校验（来源：${source}）`;
  } catch (error) {
    errorMessage.value = errorMessageFrom(error);
  } finally {
    busy.value = false;
  }
}

function leaveRoom(): void {
  socket?.close();
  socket = null;
  session.roomId = "";
  session.playerToken = "";
  session.spectatorPassword = "";
  room.value = null;
  events.value = [];
  connectionState.value = "idle";
  aiNotice.value = "";
  errorMessage.value = "";
}

function errorMessageFrom(error: unknown): string {
  return error instanceof Error ? error.message : "发生未知错误";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

onBeforeUnmount(() => socket?.close());
</script>

<template>
  <main class="app-shell">
    <RoomPanel
      v-if="room"
      :room="room"
      :events="events"
      :spectator-password="session.spectatorPassword"
      :connection-state="connectionState"
      :busy="busy"
      :ai-notice="aiNotice"
      @action="runAction"
      @ai-action="runAiAction"
      @reconnect="connectSocket"
      @leave="leaveRoom"
    />
    <LobbyPanel
      v-else
      :busy="busy"
      @create="createRoom"
      @join="joinRoom"
    />

    <p v-if="errorMessage" class="error-banner">{{ errorMessage }}</p>
  </main>
</template>
