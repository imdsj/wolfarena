<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref } from "vue";

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
const actionNotice = ref("");
const session = reactive({
  kind: "" as "" | "player" | "spectator",
  roomId: "",
  playerToken: "",
  spectatorPassword: "",
  accessPassword: "",
});
const restoring = ref(false);

let socket: WebSocket | null = null;
const SESSION_STORAGE_KEY = "wolfarena.session.v1";
const REMEMBERED_SESSION_VERSION = 1;

interface RememberedSession {
  version: number;
  kind: "player" | "spectator";
  roomId: string;
  playerToken?: string;
  spectatorPassword?: string;
  accessPassword?: string;
}

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
  session.kind = "player";
  session.roomId = payload.room_id;
  session.playerToken = payload.player_token;
  session.spectatorPassword = payload.spectator_password ?? "";
  session.accessPassword = "";
  room.value = payload.room;
  events.value = payload.room.visible_events;
  errorMessage.value = "";
  persistSession();
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

function watchRoom(payload: {
  roomId: string;
  password: string;
}): void {
  socket?.close();
  socket = null;
  session.kind = "spectator";
  session.roomId = payload.roomId;
  session.playerToken = "";
  session.spectatorPassword = "";
  session.accessPassword = payload.password;
  room.value = null;
  events.value = [];
  aiNotice.value = "";
  errorMessage.value = "";
  busy.value = true;
  connectSocket();
}

function connectSocket(): void {
  if (
    !session.roomId ||
    (session.kind === "player" && !session.playerToken) ||
    (session.kind === "spectator" && !session.accessPassword)
  ) {
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
      JSON.stringify(
        session.kind === "spectator"
          ? {
              type: "authenticate",
              spectator_password: session.accessPassword,
            }
          : {
              type: "authenticate",
              token: session.playerToken,
            },
      ),
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
      busy.value = false;
      restoring.value = false;
    }
  };

  current.onerror = () => {
    if (socket === current) {
      connectionState.value = "error";
      busy.value = false;
      restoring.value = false;
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
    busy.value = false;
    restoring.value = false;
    return;
  }
  if (message.type === "snapshot" && isRecord(message.room)) {
    room.value = message.room as unknown as RoomSnapshot;
    mergeEvents(message.room.visible_events as GameEvent[]);
    actionNotice.value = "";
    busy.value = false;
    restoring.value = false;
    persistSession();
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
    actionNotice.value =
      `已提交：${String(message.action ?? "动作")}` +
      (Number.isInteger(message.event_seq)
        ? `（事件 #${message.event_seq}）`
        : "");
    busy.value = false;
    return;
  }
  if (message.type === "error") {
    errorMessage.value = String(message.message ?? "服务器拒绝了操作");
    actionNotice.value = "";
    busy.value = false;
    const code = String(message.code ?? "");
    if (
      [
        "INVALID_PLAYER_TOKEN",
        "INVALID_SPECTATOR_PASSWORD",
        "ROOM_NOT_FOUND",
        "AUTH_REQUIRED",
        "AUTH_TIMEOUT",
      ].includes(code)
    ) {
      clearStoredSession();
      restoring.value = false;
      room.value = null;
    }
  }
}

async function runAction(action: ActionSubmission): Promise<void> {
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    errorMessage.value = "连接尚未建立，不能提交动作";
    return;
  }
  busy.value = true;
  aiNotice.value = "";
  actionNotice.value = "";
  socket.send(JSON.stringify({ type: "action", ...action }));
}

async function runAiAction(): Promise<void> {
  busy.value = true;
  errorMessage.value = "";
  aiNotice.value = "";
  actionNotice.value = "";
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

function resetSession(): void {
  socket?.close();
  socket = null;
  session.kind = "";
  session.roomId = "";
  session.playerToken = "";
  session.spectatorPassword = "";
  session.accessPassword = "";
  room.value = null;
  events.value = [];
  connectionState.value = "idle";
  aiNotice.value = "";
  actionNotice.value = "";
  busy.value = false;
  restoring.value = false;
}

function leaveRoom(): void {
  resetSession();
  errorMessage.value = "";
  clearStoredSession();
}

function persistSession(): void {
  if (!session.kind || !session.roomId) {
    return;
  }
  const payload: RememberedSession = {
    version: REMEMBERED_SESSION_VERSION,
    kind: session.kind,
    roomId: session.roomId,
  };
  if (session.kind === "player") {
    payload.playerToken = session.playerToken;
    payload.spectatorPassword = session.spectatorPassword;
  } else {
    payload.accessPassword = session.accessPassword;
  }
  try {
    localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(payload));
  } catch {
    errorMessage.value = "浏览器无法保存当前会话，请重新连接";
  }
}

function clearStoredSession(): void {
  try {
    localStorage.removeItem(SESSION_STORAGE_KEY);
  } catch {
    // Storage failures must not block the current WebSocket session.
  }
}

function restoreRememberedSession(): void {
  let remembered: RememberedSession;
  try {
    const raw = localStorage.getItem(SESSION_STORAGE_KEY);
    if (!raw) {
      return;
    }
    remembered = JSON.parse(raw) as RememberedSession;
  } catch {
    clearStoredSession();
    return;
  }
  if (
    remembered.version !== REMEMBERED_SESSION_VERSION ||
    !remembered.roomId ||
    (remembered.kind !== "player" && remembered.kind !== "spectator")
  ) {
    clearStoredSession();
    return;
  }
  if (
    remembered.kind === "player" &&
    typeof remembered.playerToken !== "string"
  ) {
    clearStoredSession();
    return;
  }
  if (
    remembered.kind === "spectator" &&
    typeof remembered.accessPassword !== "string"
  ) {
    clearStoredSession();
    return;
  }

  session.kind = remembered.kind;
  session.roomId = remembered.roomId;
  session.playerToken = remembered.playerToken ?? "";
  session.spectatorPassword = remembered.spectatorPassword ?? "";
  session.accessPassword = remembered.accessPassword ?? "";
  room.value = null;
  events.value = [];
  busy.value = true;
  restoring.value = true;
  connectSocket();
}

function errorMessageFrom(error: unknown): string {
  return error instanceof Error ? error.message : "发生未知错误";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

onMounted(restoreRememberedSession);
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
      :action-notice="actionNotice"
      @action="runAction"
      @ai-action="runAiAction"
      @reconnect="connectSocket"
      @leave="leaveRoom"
    />
    <LobbyPanel
      v-else
      :busy="busy || restoring"
      @create="createRoom"
      @join="joinRoom"
      @watch="watchRoom"
    />

    <p v-if="errorMessage" class="error-banner">{{ errorMessage }}</p>
  </main>
</template>
