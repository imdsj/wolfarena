import { setTimeout as delay } from "node:timers/promises";

const baseUrl = process.env.WOLFARENA_SMOKE_URL ?? "http://127.0.0.1:8010";

function createSocket(roomId) {
  const protocol = baseUrl.startsWith("https:") ? "wss:" : "ws:";
  return new WebSocket(
    `${protocol}//${new URL(baseUrl).host}/ws/rooms/${encodeURIComponent(roomId)}`,
  );
}

async function receiveUntil(socket, predicate, timeoutMs = 5000) {
  return new Promise((resolve, reject) => {
    const messages = [];
    const deadline = Date.now() + timeoutMs;
    const timer = setInterval(() => {
      if (Date.now() >= deadline) {
        cleanup();
        reject(new Error(`WebSocket 消息等待超时：${JSON.stringify(messages)}`));
      }
    }, 50);
    const onMessage = (event) => {
      const message = JSON.parse(String(event.data));
      messages.push(message);
      if (predicate(message, messages)) {
        cleanup();
        resolve(messages);
      }
    };
    const onError = () => {
      cleanup();
      reject(new Error("WebSocket 连接失败"));
    };
    function cleanup() {
      clearInterval(timer);
      socket.removeEventListener("message", onMessage);
      socket.removeEventListener("error", onError);
    }
    socket.addEventListener("message", onMessage);
    socket.addEventListener("error", onError);
  });
}

async function connectPlayer(roomId, token) {
  const socket = createSocket(roomId);
  await new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, { once: true });
    socket.addEventListener("error", reject, { once: true });
  });
  const welcome = receiveUntil(
    socket,
    (_message, messages) => messages.length >= 3,
  );
  socket.send(JSON.stringify({ type: "authenticate", token }));
  const messages = await welcome;
  return { socket, snapshot: messages.find((item) => item.type === "snapshot") };
}

const createdResponse = await fetch(`${baseUrl}/api/rooms`, {
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify({
    human_count: 1,
    max_humans: 3,
    nickname: "同步房主",
  }),
});
if (createdResponse.status !== 201) {
  throw new Error(`创建房间失败：${createdResponse.status}`);
}
const created = await createdResponse.json();

const joinResponse = await fetch(
  `${baseUrl}/api/rooms/${encodeURIComponent(created.room_id)}/join`,
  {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ nickname: "同步玩家" }),
  },
);
if (joinResponse.status !== 200) {
  throw new Error(`加入房间失败：${joinResponse.status}`);
}
const joined = await joinResponse.json();

const host = await connectPlayer(created.room_id, created.player_token);
const guest = await connectPlayer(created.room_id, joined.player_token);

const hostUpdate = receiveUntil(
  host.socket,
  (message) => message.type === "phase" && message.phase !== "INIT",
);
const guestUpdate = receiveUntil(
  guest.socket,
  (message) => message.type === "phase" && message.phase !== "INIT",
);
host.socket.send(
  JSON.stringify({
    type: "action",
    action: "start_night",
    target_id: null,
    content: null,
    choice: null,
  }),
);

const [hostMessages, guestMessages] = await Promise.all([
  hostUpdate,
  guestUpdate,
]);
const hostPhase = hostMessages.find((message) => message.type === "phase");
const guestPhase = guestMessages.find((message) => message.type === "phase");
host.socket.close();
guest.socket.close();

const result = {
  hostPhase: hostPhase.phase,
  guestPhase: guestPhase.phase,
  samePhase: hostPhase.phase === guestPhase.phase,
  sameEventSequence: hostPhase.event_seq === guestPhase.event_seq,
  hostReceivedServerEvents: hostMessages.some(
    (message) => message.type === "event",
  ),
  guestReceivedServerEvents: guestMessages.some(
    (message) => message.type === "event",
  ),
};
if (
  !result.samePhase ||
  !result.sameEventSequence ||
  !result.hostReceivedServerEvents ||
  !result.guestReceivedServerEvents
) {
  throw new Error(`双客户端同步失败：${JSON.stringify(result)}`);
}

console.log(JSON.stringify(result, null, 2));
await delay(100);
process.exit(0);
