import { setTimeout as delay } from "node:timers/promises";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { Window } from "happy-dom";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const frontendDirectory = path.resolve(scriptDirectory, "..");
const baseUrl = process.env.WOLFARENA_SMOKE_URL ?? "http://127.0.0.1:8010";
const startedAt = Date.now();
const evidenceDirectory = path.resolve(
  frontendDirectory,
  "..",
  "docs",
  "evidence",
  "browser-2026-10-26",
);
const window = new Window({ url: `${baseUrl}/` });
window.innerWidth = 390;
window.innerHeight = 844;
window.document.body.innerHTML = '<div id="app"></div>';

const nativeFetch = globalThis.fetch;
let createdSession = null;
let activeSocket = null;
const NativeWebSocket = globalThis.WebSocket;

class TrackedWebSocket extends NativeWebSocket {
  constructor(...args) {
    super(...args);
    activeSocket = this;
  }
}

Object.assign(globalThis, {
  window,
  document: window.document,
  localStorage: window.localStorage,
  Node: window.Node,
  Element: window.Element,
  HTMLElement: window.HTMLElement,
  HTMLInputElement: window.HTMLInputElement,
  SVGElement: window.SVGElement,
  WebSocket: TrackedWebSocket,
  fetch: (input, init) => {
    const target =
      typeof input === "string" && input.startsWith("/")
        ? `${baseUrl}${input}`
        : input;
    let effectiveInit = init;
    if (
      target === `${baseUrl}/api/rooms` &&
      init?.method === "POST" &&
      typeof init.body === "string"
    ) {
      effectiveInit = {
        ...init,
        body: JSON.stringify({
          ...JSON.parse(init.body),
          seed: 2,
        }),
      };
    }
    return nativeFetch(target, effectiveInit).then(async (response) => {
      if (
        target === `${baseUrl}/api/rooms` &&
        init?.method === "POST" &&
        response.status === 201
      ) {
        createdSession = await response.clone().json();
      }
      return response;
    });
  },
});

const { createApp } = await import("vue");
const { default: App } = await import("../dist/src/App.js");
const stylesheet = document.createElement("style");
stylesheet.textContent = await readFile(
  path.join(frontendDirectory, "dist", "src", "styles.css"),
  "utf8",
);
document.head.append(stylesheet);

async function saveDomSnapshot(name) {
  await mkdir(evidenceDirectory, { recursive: true });
  const shellElement = document.querySelector(".app-shell")?.cloneNode(true);
  if (shellElement) {
    for (const element of shellElement.querySelectorAll(
      ".credential-row code",
    )) {
      element.textContent = "[REDACTED]";
    }
    for (const input of shellElement.querySelectorAll("input")) {
      input.removeAttribute("value");
    }
  }
  const shell = shellElement?.outerHTML ?? "";
  const html = `<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>WolfArena UI state ${name}</title>
    <style>${stylesheet.textContent}</style>
    <style>body { min-height: 844px; overflow-x: hidden; }</style>
  </head>
  <body>${shell}</body>
</html>`;
  await writeFile(path.join(evidenceDirectory, `${name}.html`), html, "utf8");
}

async function waitFor(predicate, message, timeoutMs = 15000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const value = predicate();
    if (value) {
      return value;
    }
    await delay(50);
  }
  throw new Error(`等待超时：${message}`);
}

function normalizedText(element) {
  return element?.textContent?.replace(/\s+/g, " ").trim() ?? "";
}

function buttonByText(text) {
  const button = [...document.querySelectorAll("button")].find(
    (candidate) => normalizedText(candidate) === text,
  );
  if (!button) {
    throw new Error(`找不到按钮：${text}`);
  }
  return button;
}

function inputByLabel(label) {
  const field = [...document.querySelectorAll(".field")].find((candidate) =>
    normalizedText(candidate.querySelector("span")).includes(label),
  );
  const input = field?.querySelector("input");
  if (!input) {
    throw new Error(`找不到输入框：${label}`);
  }
  return input;
}

function setInput(input, value) {
  input.value = value;
  input.dispatchEvent(new window.Event("input", { bubbles: true }));
  input.dispatchEvent(new window.Event("change", { bubbles: true }));
}

function setSelect(select, value) {
  select.value = value;
  select.dispatchEvent(new window.Event("change", { bubbles: true }));
}

function mountApp() {
  const previousHost = document.querySelector("#app");
  if (previousHost) {
    previousHost.replaceWith(Object.assign(document.createElement("div"), {
      id: "app",
    }));
  }
  const app = createApp(App);
  app.mount("#app");
  return app;
}

function phaseCode() {
  const metric = document.querySelectorAll(".metric strong")[3];
  return normalizedText(metric).split("/").at(-1)?.trim() ?? "";
}

function eventCount() {
  return document.querySelectorAll(".event-row").length;
}

function uiError() {
  return normalizedText(document.querySelector(".error-banner"));
}

const actionPriority = [
  "speech",
  "last_words",
  "wolf_speech",
  "seer_check",
  "witch_action",
  "vote",
  "close_vote",
  "resolve_vote",
  "begin_banishment_last_words",
  "wolf_kill",
  "night_hunter_shot",
  "day_hunter_shot",
  "resolve_night",
  "begin_day",
  "close_self_destruct_window",
];

let lastVoteKey = "";
let lastVoteCloseKey = "";

function chooseActionCard() {
  const cards = [...document.querySelectorAll(".action-card")];
  const currentPhase = phaseCode();
  const day = normalizedText(
    document.querySelectorAll(".metric strong")[3],
  ).split("/")[0]?.trim();
  const ranked = cards
    .map((card) => ({
      card,
      action: normalizedText(
        card.querySelector(".action-card-heading code"),
      ),
    }))
    .sort(
      (left, right) =>
        actionPriority.indexOf(left.action) -
        actionPriority.indexOf(right.action),
    );

  for (const candidate of ranked) {
    if (candidate.action === "vote" && lastVoteKey === `${day}:${currentPhase}`) {
      continue;
    }
    if (
      candidate.action === "close_vote" &&
      lastVoteCloseKey === `${day}:${currentPhase}`
    ) {
      continue;
    }
    return candidate;
  }
  return null;
}

async function configureAndSubmitAction(card, action) {
  const phase = phaseCode();
  const day = normalizedText(
    document.querySelectorAll(".metric strong")[3],
  ).split("/")[0]?.trim();

  const optionLabel = [...card.querySelectorAll(".compact-field")].find(
    (field) => normalizedText(field.querySelector("span")) === "行动选项",
  );
  const optionSelect = optionLabel?.querySelector("select");
  if (optionSelect) {
    const preferred =
      action === "witch_action" && optionSelect.value !== "none"
        ? "none"
        : optionSelect.value;
    setSelect(optionSelect, preferred);
  }

  const targetLabel = [...card.querySelectorAll(".compact-field")].find(
    (field) => normalizedText(field.querySelector("span")) === "目标",
  );
  const targetSelect = targetLabel?.querySelector("select");
  if (targetSelect) {
    const noTarget = ["vote", "wolf_kill", "night_hunter_shot", "day_hunter_shot"]
      .includes(action)
      ? [...targetSelect.options].find((option) => option.value === "__none__")
      : null;
    const selected = noTarget
      ? "__none__"
      : [...targetSelect.options].find((option) => option.value !== "__none__")
          ?.value;
    setSelect(targetSelect, selected ?? "");
  }

  const textarea = card.querySelector("textarea");
  if (textarea) {
    setInput(textarea, `浏览器验收：${action}`);
  }

  let liveCard = null;
  let submitButton = null;
  const buttonDeadline = Date.now() + 1500;
  while (Date.now() < buttonDeadline) {
    liveCard = [...document.querySelectorAll(".action-card")].find(
      (candidate) =>
        normalizedText(
          candidate.querySelector(".action-card-heading code"),
        ) === action,
    );
    submitButton = liveCard?.querySelector('button[type="submit"]');
    if (submitButton && !submitButton.disabled) {
      break;
    }
    const liveTextarea = liveCard?.querySelector("textarea");
    if (
      liveTextarea &&
      ["speech", "last_words", "wolf_speech"].includes(action)
    ) {
      setInput(liveTextarea, `浏览器验收：${action}`);
    }
    await delay(25);
  }
  if (!liveCard || !submitButton || submitButton.disabled) {
    console.error(
      `[acceptance] action-unavailable phase=${phaseCode()} action=${action} ` +
        `card=${Boolean(liveCard)} button=${Boolean(submitButton)} ` +
        `busy=${submitButton?.dataset.busy} target=${submitButton?.dataset.target} ` +
        `choice=${submitButton?.dataset.choice}`,
    );
    return null;
  }
  if (action === "vote") {
    lastVoteKey = `${day}:${phase}`;
  }
  if (action === "close_vote") {
    lastVoteCloseKey = `${day}:${phase}`;
  }
  const beforeEvents = eventCount();
  const beforePhase = phase;
  const beforeActionNotice = normalizedText(
    document.querySelector('[data-testid="action-notice"]'),
  );
  submitButton.click();
  return { beforeEvents, beforePhase, beforeActionNotice };
}

let app = mountApp();
await waitFor(
  () => document.querySelector(".lobby-panel"),
  "大厅加载",
);
await saveDomSnapshot("390-lobby");

setInput(inputByLabel("你的昵称"), "浏览器验收玩家");
await delay(0);
buttonByText("创建房间").click();
await waitFor(
  () => document.querySelector(".room-shell"),
  "创建房间",
);
await waitFor(
  () =>
    document.querySelector('.connection-status[data-state="connected"]'),
  "玩家 WebSocket 认证",
);
await waitFor(() => createdSession, "捕获创建房间响应");

const initialPhase = phaseCode();
const humanRole = normalizedText(document.querySelector(".metric strong"));
activeSocket.send(
  JSON.stringify({
    type: "action",
    action: "vote",
    target_id: null,
    content: null,
    choice: null,
  }),
);
const serverError = await waitFor(uiError, "服务器错误提示");

const startCard = [...document.querySelectorAll(".action-card")].find(
  (card) =>
    normalizedText(card.querySelector(".action-card-heading code")) ===
    "start_night",
);
if (!startCard) {
  throw new Error("缺少开始首夜动作");
}
startCard.querySelector('button[type="submit"]').click();
await waitFor(
  () => phaseCode() !== "INIT",
  "首夜开始",
);
await waitFor(() => !uiError(), "合法动作清除错误提示");

const seenPhases = new Set([initialPhase]);
const performedActions = [];
let savedInProgress = false;
let noActionSince = Date.now();
let noActionMarker = `${eventCount()}:${phaseCode()}`;
for (let step = 0; step < 500; step += 1) {
  if (document.querySelector('[data-testid="game-result"]')) {
    break;
  }
  const message = uiError();
  if (message) {
    throw new Error(`玩家动作被拒绝：${message}`);
  }
  seenPhases.add(phaseCode());
  if (
    !savedInProgress &&
    ["DAY_DISCUSSION", "VOTE", "SELF_DESTRUCT"].includes(phaseCode())
  ) {
    await saveDomSnapshot("390-player-in-progress");
    savedInProgress = true;
  }
  const candidate = chooseActionCard();
  if (!candidate) {
    const marker = `${eventCount()}:${phaseCode()}`;
    if (marker !== noActionMarker) {
      noActionMarker = marker;
      noActionSince = Date.now();
      console.error(
        `[acceptance] waiting phase=${phaseCode()} events=${eventCount()} ` +
          `actions=${[...document.querySelectorAll(".action-card-heading code")]
            .map((element) => normalizedText(element))
            .join(",")}`,
      );
    }
    if (Date.now() - noActionSince > 12000) {
      throw new Error(`阶段停滞：${phaseCode()}`);
    }
    await delay(100);
    continue;
  }
  noActionSince = Date.now();
  const before = await configureAndSubmitAction(
    candidate.card,
    candidate.action,
  );
  if (!before) {
    await delay(50);
    continue;
  }
  performedActions.push(candidate.action);
  console.error(
    `[acceptance] step=${step} phase=${before.beforePhase} action=${candidate.action}`,
  );
  await waitFor(
    () =>
      eventCount() > before.beforeEvents ||
      phaseCode() !== before.beforePhase ||
      document.querySelector('[data-testid="game-result"]') ||
      (normalizedText(
        document.querySelector('[data-testid="action-notice"]'),
      ) &&
        normalizedText(
          document.querySelector('[data-testid="action-notice"]'),
        ) !== before.beforeActionNotice) ||
      uiError(),
    `动作结果：${candidate.action}`,
  );
  if (Date.now() - startedAt > 30000) {
    throw new Error(
      `全流程超过 30 秒：phase=${phaseCode()}，` +
        `actions=${performedActions.join(",")}`,
    );
  }
}

const result = await waitFor(
  () => document.querySelector('[data-testid="game-result"]'),
  "对局结束页面",
  35000,
);
const resultText = normalizedText(result);
const resultPlayers = document.querySelectorAll(".result-player").length;
const finalPhase = phaseCode();
await saveDomSnapshot("390-player-end");

app.unmount();
document.querySelector("#app")?.remove();
document.body.append(Object.assign(document.createElement("div"), { id: "app" }));
app = mountApp();
await waitFor(
  () => document.querySelector('[data-testid="game-result"]'),
  "刷新后恢复终局",
);
const restoredPhase = phaseCode();
const restoredSocketConnected = Boolean(
  document.querySelector('.connection-status[data-state="connected"]'),
);

buttonByText("离开").click();
await waitFor(() => document.querySelector(".lobby-panel"), "返回大厅");
setInput(inputByLabel("房间号"), createdSession.room_id);
setInput(inputByLabel("观战密码"), "wrong-password");
await delay(0);
buttonByText("进入观战").click();
const wrongPasswordError = await waitFor(uiError, "错误观战密码提示");
await waitFor(() => document.querySelector(".lobby-panel"), "观战失败留在大厅");

setInput(inputByLabel("观战密码"), createdSession.spectator_password);
await delay(0);
buttonByText("进入观战").click();
await waitFor(
  () => document.querySelector('[data-testid="spectator-mode"]'),
  "观战者上帝视角",
);
await waitFor(
  () =>
    document.querySelector('.connection-status[data-state="connected"]'),
  "观战 WebSocket 认证",
);
const spectatorActionCards =
  document.querySelectorAll(".action-card").length;
const spectatorReadonly = Boolean(
  document.querySelector('[data-testid="spectator-readonly"]'),
);
const spectatorEventText = normalizedText(
  document.querySelector(".event-list"),
);
await saveDomSnapshot("390-spectator-end");
if (
  !performedActions.includes("speech") ||
  !performedActions.includes("vote")
) {
  throw new Error(
    `全流程未覆盖发言和投票：${JSON.stringify(performedActions)}`,
  );
}

console.log(
  JSON.stringify(
    {
      initialPhase,
      humanRole,
      seenPhases: [...seenPhases],
      performedActions,
      serverError,
      finalPhase,
      resultPlayers,
      resultText,
      restoredPhase,
      restoredSocketConnected,
      wrongPasswordError,
      spectatorMode: true,
      spectatorActionCards,
      spectatorReadonly,
      spectatorSawWolfSpeech: spectatorEventText.includes("WOLF_SPEECH"),
      viewport: `${window.innerWidth}x${window.innerHeight}`,
      savedDomSnapshots: [
        "390-lobby.html",
        "390-player-in-progress.html",
        "390-player-end.html",
        "390-spectator-end.html",
      ],
      durationMs: Date.now() - startedAt,
    },
    null,
    2,
  ),
);

app.unmount();
window.close();
await delay(100);
process.exit(0);
