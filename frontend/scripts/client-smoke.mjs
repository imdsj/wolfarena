import { setTimeout as delay } from "node:timers/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { Window } from "happy-dom";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const frontendDirectory = path.resolve(scriptDirectory, "..");
const baseUrl = process.env.WOLFARENA_SMOKE_URL ?? "http://127.0.0.1:8010";

const window = new Window({ url: `${baseUrl}/` });
window.document.body.innerHTML = '<div id="app"></div>';
const nativeFetch = globalThis.fetch;
let createdRoomId = "";

Object.assign(globalThis, {
  window,
  document: window.document,
  localStorage: window.localStorage,
  Node: window.Node,
  Element: window.Element,
  HTMLElement: window.HTMLElement,
  HTMLInputElement: window.HTMLInputElement,
  SVGElement: window.SVGElement,
  WebSocket: globalThis.WebSocket,
  fetch: (input, init) => {
    const target =
      typeof input === "string" && input.startsWith("/")
        ? `${baseUrl}${input}`
        : input;
    return nativeFetch(target, init).then(async (response) => {
      if (target === `${baseUrl}/api/rooms` && init?.method === "POST") {
        const payload = await response.clone().json();
        createdRoomId = payload.room_id;
      }
      return response;
    });
  },
});

const { createApp } = await import("vue");
const { default: PhaseCountdown } = await import(
  "../dist/src/components/PhaseCountdown.js"
);

await import(pathToFileURL(path.join(frontendDirectory, "dist", "src", "main.js")));

async function waitFor(selector, timeoutMs = 5000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const element = document.querySelector(selector);
    if (element) {
      return element;
    }
    await delay(50);
  }
  throw new Error(`等待元素超时：${selector}`);
}

function buttonByText(text) {
  const button = [...document.querySelectorAll("button")].find(
    (candidate) => candidate.textContent?.trim() === text,
  );
  if (!button) {
    throw new Error(`找不到按钮：${text}`);
  }
  return button;
}

await waitFor(".lobby-panel");
const nicknameInput = document.querySelector("input");
if (!nicknameInput) {
  throw new Error("缺少昵称输入框");
}
nicknameInput.value = "订书机";
nicknameInput.dispatchEvent(new window.Event("input", { bubbles: true }));
await delay(0);
buttonByText("创建房间").click();

await waitFor(".room-shell");
await waitFor('.connection-status[data-state="connected"]');
const createdPhase = document.querySelector(".room-header h1")?.textContent?.trim();
const displayedRoomId = document
  .querySelector(".room-code code")
  ?.textContent?.trim();
const exactJoinResponse = await nativeFetch(
  `${baseUrl}/api/rooms/${encodeURIComponent(createdRoomId)}/join`,
  {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ nickname: "ExactCasePlayer" }),
  },
);
let hostUpdatedAfterJoin = false;
const joinUpdateDeadline = Date.now() + 5000;
while (Date.now() < joinUpdateDeadline) {
  if ((document.querySelector(".metric-grid")?.textContent ?? "").includes("2 / 7")) {
    hostUpdatedAfterJoin = true;
    break;
  }
  await delay(50);
}
const hasServerStartAction = [...document.querySelectorAll(".action-card strong")]
  .some((element) => element.textContent?.trim() === "开始首夜");
const uppercaseRoomId = createdRoomId.toUpperCase();
let uppercaseJoinStatus = null;
if (uppercaseRoomId !== createdRoomId) {
  const uppercaseJoinResponse = await nativeFetch(
    `${baseUrl}/api/rooms/${encodeURIComponent(uppercaseRoomId)}/join`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ nickname: "UppercasePlayer" }),
    },
  );
  uppercaseJoinStatus = uppercaseJoinResponse.status;
}

buttonByText("AI 推荐并执行").click();
const fallbackNotice = await waitFor(".ai-notice");
const deadline = Date.now() + 5000;
let eventText = "";
let phaseAfterAction = "";
while (Date.now() < deadline) {
  eventText = document.querySelector(".event-list")?.textContent ?? "";
  phaseAfterAction =
    document.querySelector(".room-header h1")?.textContent?.trim() ?? "";
  if (
    eventText.includes("NIGHT_STARTED") &&
    phaseAfterAction !== "等待开始"
  ) {
    break;
  }
  await delay(50);
}

const connectionText = document
  .querySelector(".connection-status")
  ?.textContent?.trim();

const countdownHost = document.createElement("div");
document.body.append(countdownHost);
const countdownTime = Date.now() / 1000;
const countdownApp = createApp(PhaseCountdown, {
  deadlineKind: "speech",
  remainingMs: 2500,
  serverTime: countdownTime,
  deadlineAt: countdownTime + 2.5,
});
countdownApp.mount(countdownHost);
const countdownElement = await waitFor(".phase-countdown");
const initialCountdown = Number(
  countdownElement.querySelector(".countdown-value span")?.textContent,
);
await delay(250);
const laterCountdown = Number(
  countdownElement.querySelector(".countdown-value span")?.textContent,
);
const countdownLabel = countdownElement.textContent?.trim();
if (!countdownLabel?.includes("公开发言倒计时")) {
  throw new Error("倒计时没有显示正确阶段");
}
if (!(laterCountdown < initialCountdown)) {
  throw new Error("倒计时数值没有随时间递减");
}

console.log(
  JSON.stringify(
    {
      createdPhase,
      createdRoomId,
      displayedRoomId,
      roomIdDisplayedExactly: createdRoomId === displayedRoomId,
      exactJoinStatus: exactJoinResponse.status,
      hostUpdatedAfterJoin,
      hasServerStartAction,
      uppercaseJoinStatus,
      phaseAfterAction,
      fallbackNotice: fallbackNotice.textContent?.trim(),
      connectionText,
      hasFallbackEvent: eventText.includes("AI_FALLBACK_USED"),
      hasNightStartedEvent: eventText.includes("NIGHT_STARTED"),
      countdownLabel,
      countdownDecreased: laterCountdown < initialCountdown,
    },
    null,
    2,
  ),
);

countdownApp.unmount();
window.close();
await delay(100);
process.exit(0);
