import { setTimeout as delay } from "node:timers/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { Window } from "happy-dom";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const frontendDirectory = path.resolve(scriptDirectory, "..");
const baseUrl = process.env.WOLFARENA_SMOKE_URL ?? "http://127.0.0.1:8010";
const window = new Window({ url: `${baseUrl}/` });
window.document.body.innerHTML = '<div id="app"></div>';

Object.assign(globalThis, {
  window,
  document: window.document,
  localStorage: window.localStorage,
  Node: window.Node,
  Element: window.Element,
  HTMLElement: window.HTMLElement,
  HTMLInputElement: window.HTMLInputElement,
  SVGElement: window.SVGElement,
});

const { createApp } = await import("vue");
const { default: RoomPanel } = await import(
  "../dist/src/components/RoomPanel.js"
);
const { default: ActionForm } = await import(
  "../dist/src/components/ActionForm.js"
);

const players = Array.from({ length: 9 }, (_, index) => ({
  player_id: `p${index + 1}`,
  seat: index + 1,
  name: index === 0 ? "浏览器玩家" : `玩家${index + 1}`,
  is_human: index < 2,
  is_alive: index !== 3,
}));

const time = Date.now() / 1000;
const baseRoom = {
  room_id: "ViewerSmoke",
  phase: "DAY_DISCUSSION",
  day: 2,
  server_time: time,
  deadline_at: null,
  deadline_kind: null,
  remaining_ms: null,
  human_count: 2,
  max_humans: 3,
  players,
  visible_events: [],
};

const maliciousAction = {
  action: "start_night",
  label: "不应显示的开始动作",
  target_ids: [],
  choices: [],
  requires_content: false,
  requires_target: false,
  allow_no_target: false,
};

function mountRoom(room) {
  const host = document.createElement("div");
  document.body.append(host);
  const app = createApp(RoomPanel, {
    room,
    events: [],
    spectatorPassword: "",
    connectionState: "connected",
    busy: false,
    aiNotice: "",
  });
  app.mount(host);
  return { app, host };
}

const spectator = mountRoom({
  ...baseRoom,
  viewer: {
    kind: "spectator",
    player_id: null,
    seat: null,
    name: "观战者",
    role: null,
    is_alive: null,
    is_host: false,
  },
  available_actions: [maliciousAction],
});
await delay(0);
const spectatorMode = Boolean(
  document.querySelector('[data-testid="spectator-mode"]'),
);
const spectatorReadonly = Boolean(
  document.querySelector('[data-testid="spectator-readonly"]'),
);
const spectatorActionCards =
  document.querySelectorAll(".action-card").length;
spectator.app.unmount();
spectator.host.remove();

const deadPlayer = mountRoom({
  ...baseRoom,
  viewer: {
    kind: "player",
    player_id: "p4",
    seat: 4,
    name: "玩家4",
    role: "werewolf",
    is_alive: false,
    is_host: false,
  },
  available_actions: [],
});
await delay(0);
const deadMode = Boolean(
  document.querySelector('[data-testid="dead-player-mode"]'),
);
const deadMetric = [...document.querySelectorAll(".metric strong")].some(
  (element) => element.textContent?.includes("已出局"),
);
const deadSpectatorBanner = Boolean(
  document.querySelector('[data-testid="spectator-mode"]'),
);
deadPlayer.app.unmount();
deadPlayer.host.remove();

const voteHost = document.createElement("div");
document.body.append(voteHost);
const voteApp = createApp(ActionForm, {
  action: {
    action: "vote",
    label: "投票或弃权",
    target_ids: ["p1", "p2", "p4"],
    choices: [],
    requires_content: false,
    requires_target: false,
    allow_no_target: true,
  },
  players,
  busy: false,
});
voteApp.mount(voteHost);
await delay(0);
const targetValues = [...voteHost.querySelectorAll("select option")].map(
  (option) => option.value,
);
const deadTargetHidden = !targetValues.includes("p4");
const aliveTargetShown =
  targetValues.includes("p1") && targetValues.includes("p2");
voteApp.unmount();
voteHost.remove();

const speechHost = document.createElement("div");
document.body.append(speechHost);
const speechApp = createApp(ActionForm, {
  action: {
    action: "speech",
    label: "公开发言",
    target_ids: [],
    choices: [],
    requires_content: true,
    requires_target: false,
    allow_no_target: false,
  },
  players,
  busy: false,
});
speechApp.mount(speechHost);
await delay(0);
const textareaPresent = Boolean(speechHost.querySelector("textarea"));
speechApp.unmount();
speechHost.remove();

const result = {
  spectatorMode,
  spectatorReadonly,
  spectatorActionCards,
  deadMode,
  deadMetric,
  deadSpectatorBanner,
  deadTargetHidden,
  aliveTargetShown,
  textareaPresent,
};

if (
  !result.spectatorMode ||
  !result.spectatorReadonly ||
  result.spectatorActionCards !== 0 ||
  !result.deadMode ||
  !result.deadMetric ||
  result.deadSpectatorBanner ||
  !result.deadTargetHidden ||
  !result.aliveTargetShown ||
  !result.textareaPresent
) {
  throw new Error(`视角 UI 验收失败：${JSON.stringify(result)}`);
}

console.log(JSON.stringify(result, null, 2));
window.close();
await delay(100);
process.exit(0);
