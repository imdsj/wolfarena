<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";

import type {
  ActionSubmission,
  GameEvent,
  RoomSnapshot,
} from "../types";
import ActionForm from "./ActionForm.vue";
import AgentInsightPanel from "./AgentInsightPanel.vue";
import ConnectionStatus from "./ConnectionStatus.vue";
import GameResultPanel from "./GameResultPanel.vue";

const props = defineProps<{
  room: RoomSnapshot;
  events: GameEvent[];
  spectatorPassword: string;
  connectionState:
    | "idle"
    | "connecting"
    | "authenticating"
    | "connected"
    | "disconnected"
    | "error";
  busy: boolean;
  aiNotice: string;
  actionNotice: string;
  chatLog: { role: "me" | "ai"; text: string; seat: number | null }[];
}>();

const emit = defineEmits<{
  action: [action: ActionSubmission];
  aiAction: [];
  chat: [message: string];
  continue: [];
  reconnect: [];
  leave: [];
}>();

const copyLabel = ref("复制房间号");
const chatInput = ref("");
const buildId =
  (globalThis as { __WOLFARENA_BUILD__?: string }).__WOLFARENA_BUILD__ ??
  "dev";

function submitChat(): void {
  const text = chatInput.value.trim();
  if (!text) {
    return;
  }
  emit("chat", text);
  chatInput.value = "";
}

const humanCount = computed(
  () => props.room.players.filter((player) => player.is_human).length,
);
const aiCount = computed(() => props.room.players.length - humanCount.value);
const isSpectator = computed(() => props.room.viewer.kind === "spectator");
const isDeadPlayer = computed(
  () => !isSpectator.value && props.room.viewer.is_alive === false,
);
const gameEnded = computed(() => props.room.phase === "END");
const speechEventTypes = new Set([
  "PUBLIC_SPEECH",
  "WOLF_SPEECH",
  "LAST_WORDS",
]);
const speechEvents = computed(() =>
  props.events.filter((event) => speechEventTypes.has(event.event_type)),
);
const playerById = computed(() =>
  new Map(props.room.players.map((player) => [player.player_id, player])),
);
const feedEventTypes = new Set([
  ...speechEventTypes,
  "PLAYER_DIED",
  "VOTE_RESULT",
  "BANISHMENT",
  "WINNER_DECIDED",
]);
const feedItems = computed(() =>
  props.events.filter((event) => feedEventTypes.has(event.event_type)),
);
const revealedCount = ref(0);
const feedList = ref<HTMLElement | null>(null);
const stickToBottom = ref(true);
const pendingFeedCount = computed(() =>
  Math.max(0, feedItems.value.length - revealedCount.value),
);

onMounted(() => {
  revealedCount.value = feedItems.value.length;
});

function revealNext(): void {
  if (pendingFeedCount.value > 0) {
    stickToBottom.value = true;
    revealedCount.value += 1;
  }
}

function revealAll(): void {
  stickToBottom.value = true;
  revealedCount.value = feedItems.value.length;
}

function onFeedScroll(): void {
  const element = feedList.value;
  if (!element) {
    return;
  }
  stickToBottom.value =
    element.scrollHeight - element.scrollTop - element.clientHeight < 48;
}

watch(
  () => revealedCount.value,
  async () => {
    await nextTick();
    const element = feedList.value;
    if (element && stickToBottom.value) {
      element.scrollTop = element.scrollHeight;
    }
  },
);

const visibleFeed = computed(() =>
  feedItems.value.slice(0, revealedCount.value),
);
function isSpeech(event: GameEvent): boolean {
  return speechEventTypes.has(event.event_type);
}
function systemText(event: GameEvent): string {
  const target = event.target_id
    ? playerById.value.get(event.target_id)
    : undefined;
  const label = target
    ? `${target.seat} 号 ${target.name}`
    : (event.target_id ?? "");
  if (event.event_type === "PLAYER_DIED") {
    const causes = Array.isArray(event.data.causes)
      ? event.data.causes.filter(
          (cause): cause is string => typeof cause === "string",
        )
      : [];
    const causeText = causes
      .map((cause) => deathCauseLabels[cause] ?? cause)
      .join("、");
    return `${label} 出局${causeText ? `（${causeText}）` : ""}`;
  }
  if (event.event_type === "VOTE_RESULT") {
    const banishedId = event.data.banished_id;
    const banishedSeat =
      typeof banishedId === "string"
        ? playerById.value.get(banishedId)?.seat
        : null;
    if (banishedSeat) {
      return `投票结果：${banishedSeat} 号被放逐`;
    }
    return String(event.data.reason ?? "") === "tie"
      ? "投票结果：平票，无人出局"
      : "投票结果：无人出局";
  }
  if (event.event_type === "BANISHMENT") {
    return `${label} 被放逐`;
  }
  if (event.event_type === "WINNER_DECIDED") {
    const winner = String(event.data.winner ?? "");
    return `对局结束：${winner === "wolf" ? "狼人获胜" : "好人获胜"}`;
  }
  return event.event_type;
}
function speechText(event: GameEvent): string {
  const content = event.data.content;
  return typeof content === "string" ? content : "";
}
function speakerLabel(event: GameEvent): string {
  const player = event.actor_id
    ? playerById.value.get(event.actor_id)
    : undefined;
  const name = player ? player.name : (event.actor_id ?? "系统");
  const seat = player ? `${player.seat} 号` : "";
  return `${seat} ${name}`.trim();
}
const roleLabels: Record<string, string> = {
  werewolf: "狼人",
  villager: "村民",
  seer: "预言家",
  witch: "女巫",
  hunter: "猎人",
};
const archetypeLabels: Record<string, string> = {
  aggressive: "冲锋型",
  steady: "稳健型",
  logical: "逻辑型",
  chaotic: "搅局型",
};
const deathCauseLabels: Record<string, string> = {
  wolf_kill: "狼人击杀",
  poisoned: "女巫毒杀",
  banished: "投票放逐",
  hunter_shot: "猎人开枪",
  self_destruct: "自爆",
};
const visibleRoles = computed(() => {
  const roles = new Map<string, string>();
  for (const event of props.events) {
    const role = event.data.role;
    if (
      event.event_type === "ROLE_ASSIGNED" &&
      event.target_id &&
      typeof role === "string"
    ) {
      roles.set(event.target_id, role);
    }
  }
  return roles;
});
const visibleDeathCauses = computed(() => {
  const causes = new Map<string, string[]>();
  for (const event of props.events) {
    if (event.event_type !== "PLAYER_DIED" || !event.target_id) {
      continue;
    }
    const values = Array.isArray(event.data.causes)
      ? event.data.causes.filter(
          (cause): cause is string => typeof cause === "string",
        )
      : [];
    causes.set(event.target_id, values);
  }
  return causes;
});
const latestVoteResult = computed(() => {
  const results = props.events.filter(
    (event) => event.event_type === "VOTE_RESULT",
  );
  return results.length ? results[results.length - 1] : null;
});
const latestFeedEvent = computed(() =>
  props.events.length ? props.events[props.events.length - 1] : null,
);
const lastWordsJustEnded = computed(
  () => latestFeedEvent.value?.event_type === "LAST_WORDS",
);
const voteRows = computed(() => {
  const data = latestVoteResult.value?.data;
  const votes = data?.votes;
  if (!votes || typeof votes !== "object") {
    return [];
  }
  const seatOf = (playerId: unknown): number | null => {
    if (typeof playerId !== "string") {
      return null;
    }
    return playerById.value.get(playerId)?.seat ?? null;
  };
  return Object.entries(votes as Record<string, string | null>)
    .map(([voter, target]) => ({
      voter,
      voterSeat: seatOf(voter),
      targetSeat: seatOf(target),
    }))
    .sort((left, right) => (left.voterSeat ?? 0) - (right.voterSeat ?? 0));
});
const voteTally = computed(() => {
  const data = latestVoteResult.value?.data;
  const tally = data?.tally;
  if (!tally || typeof tally !== "object") {
    return [];
  }
  return Object.entries(tally as Record<string, number>)
    .map(([playerId, count]) => {
      const seat = playerById.value.get(playerId)?.seat;
      return seat === undefined ? null : { seat, count };
    })
    .filter(
      (item): item is { seat: number; count: number } => item !== null,
    )
    .sort((left, right) => right.count - left.count);
});
const witchKillTarget = computed(() => {
  if (!props.room.witch_kill_target_visible) {
    return null;
  }
  if (!props.room.witch_kill_target_id) {
    return "狼人今晚空刀，没有刀口";
  }
  const player = props.room.players.find(
    (candidate) =>
      candidate.player_id === props.room.witch_kill_target_id,
  );
  return player
    ? `今晚刀口：${player.seat}号 ${player.name}`
    : `今晚刀口：${props.room.witch_kill_target_id}`;
});
const canStartNight = computed(
  () =>
    !isSpectator.value &&
    props.room.viewer.is_host &&
    props.room.phase === "INIT" &&
    props.connectionState === "connected",
);
const canUseAiStart = computed(
  () =>
    canStartNight.value &&
    props.room.available_actions.some(
      (action) => action.action === "start_night",
    ),
);
const showAgentInsights = computed(
  () => isSpectator.value || gameEnded.value,
);

const phaseLabels: Record<string, string> = {
  INIT: "等待开始",
  NIGHT_WOLF_DISCUSSION_R1: "首夜狼队讨论",
  NIGHT_WOLF_DISCUSSION_R2: "首夜狼队讨论（第二轮）",
  NIGHT_WOLF_KILL: "狼队选择目标",
  NIGHT_SEER_CHECK: "预言家查验",
  NIGHT_WITCH_ACTION: "女巫行动",
  NIGHT_RESOLUTION: "夜间结算",
  NIGHT_HUNTER_SHOT: "夜间猎人开枪",
  DAY_ANNOUNCEMENT: "天亮公告",
  DAY_LAST_WORDS: "遗言",
  DAY_DISCUSSION: "白天讨论",
  SELF_DESTRUCT: "自爆结算",
  VOTE: "投票",
  DAY_HUNTER_SHOT: "白天猎人开枪",
  END: "对局结束",
};

function phaseLabel(phase: string): string {
  return phaseLabels[phase] ?? phase;
}

function roleLabel(role: string | null | undefined): string {
  return role ? roleLabels[role] ?? role : "未公开";
}

function visibleRole(playerId: string): string {
  return roleLabel(visibleRoles.value.get(playerId));
}

function archetypeLabel(archetype: string | null | undefined): string {
  return archetype ? archetypeLabels[archetype] ?? archetype : "";
}

function playerStatus(player: { player_id: string; is_alive: boolean }): string {
  if (player.is_alive) {
    return "存活";
  }
  const causes = visibleDeathCauses.value.get(player.player_id) ?? [];
  return causes.length
    ? causes.map((cause) => deathCauseLabels[cause] ?? cause).join("、")
    : "已出局";
}

async function copyRoomId(): Promise<void> {
  try {
    await navigator.clipboard.writeText(props.room.room_id);
    copyLabel.value = "已复制";
    window.setTimeout(() => {
      copyLabel.value = "复制房间号";
    }, 1500);
  } catch {
    copyLabel.value = "请手动选择";
  }
}

function openStrategyLab(): void {
  window.open("/?view=lab", "_blank", "noopener");
}
</script>

<template>
  <section class="room-shell">
    <header class="room-header">
      <div>
        <div class="room-identity">
          <div class="eyebrow room-code">
            房间 <code>{{ room.room_id }}</code>
            <span class="build-tag">build {{ buildId }}</span>
          </div>
          <button class="text-button copy-room-id" type="button" @click="copyRoomId">
            {{ copyLabel }}
          </button>
        </div>
        <h1>{{ phaseLabel(room.phase) }}</h1>
      </div>
      <div class="room-header-actions">
        <button
          class="text-button"
          type="button"
          @click="openStrategyLab"
        >
          策略实验室
        </button>
        <button class="text-button" type="button" @click="emit('leave')">
          离开
        </button>
      </div>
    </header>

    <ConnectionStatus
      :state="connectionState"
      @reconnect="emit('reconnect')"
    />

    <section
      v-if="isSpectator"
      class="view-mode-banner spectator-banner"
      data-testid="spectator-mode"
    >
      <strong>上帝视角</strong>
      <span>可见全部身份、狼人私聊与死因；不能提交玩家动作。</span>
    </section>
    <section
      v-else-if="isDeadPlayer && !gameEnded"
      class="view-mode-banner dead-banner"
      data-testid="dead-player-mode"
    >
      <strong>你已出局</strong>
      <span>本局继续，你现在是观战视角：能看所有公开信息（天亮公告、票型、发言、死亡），但不能发言和投票。</span>
    </section>

    <div class="room-layout">
      <main class="room-main">
    <section
      v-if="room.last_night_summary"
      class="night-result-banner"
      data-testid="night-result"
    >
      <span class="night-result-label">天亮公告</span>
      <strong>{{ room.last_night_summary }}</strong>
    </section>

    <section
      v-if="!isSpectator && !gameEnded && room.available_actions.length"
      class="turn-banner"
      data-testid="your-turn"
    >
      <strong>轮到你行动</strong>
      <span>
        {{ room.available_actions.map((item) => item.label).join("、") }}
      </span>
    </section>

    <section
      v-if="latestVoteResult && voteRows.length"
      class="panel vote-board"
      data-testid="vote-board"
    >
      <div class="section-heading">
        <h2>票型</h2>
        <span>第 {{ latestVoteResult.day }} 天</span>
      </div>
      <div class="vote-rows">
        <div v-for="row in voteRows" :key="row.voter" class="vote-row">
          <span class="vote-voter">{{ row.voterSeat }} 号</span>
          <span class="vote-arrow">→</span>
          <span
            class="vote-target"
            :class="{ 'vote-abstain': !row.targetSeat }"
          >
            {{ row.targetSeat ? row.targetSeat + " 号" : "弃权" }}
          </span>
        </div>
      </div>
      <div class="vote-tally">
        <span v-for="item in voteTally" :key="item.seat" class="vote-chip">
          {{ item.seat }} 号 · {{ item.count }} 票
        </span>
      </div>
    </section>

    <section
      v-if="room.awaiting_continue"
      class="continue-banner"
      data-testid="continue-banner"
    >
      <div>
        <strong>{{
          lastWordsJustEnded
            ? "遗言已结束"
            : room.phase === "VOTE"
              ? "投票已结束"
              : "本阶段结束"
        }}</strong>
        <span>{{
          lastWordsJustEnded
            ? "看完遗言再继续。所有存活玩家都点继续后，才进入黑夜。"
            : "看完票型和遗言再继续。所有存活玩家都点继续后，才往下走。"
        }}</span>
      </div>
      <button
        class="primary-button"
        type="button"
        :disabled="busy"
        @click="emit('continue')"
      >
        {{
          room.phase.startsWith("NIGHT_") || room.phase === "VOTE"
            ? "继续进入黑夜"
            : "继续游戏"
        }}
      </button>
    </section>

    <section v-if="room.announcements.length" class="panel narrator-panel">
      <p
        v-for="(line, index) in room.announcements"
        :key="index"
        class="narrator-line"
      >
        {{ line }}
      </p>
    </section>

    <div class="metric-grid">
      <article class="metric">
        <span>{{ isSpectator ? "访问方式" : "当前身份" }}</span>
        <strong>
          {{ isSpectator ? "观战者" : roleLabel(room.viewer.role) }}
        </strong>
      </article>
      <article class="metric">
        <span>{{ isSpectator ? "视角" : "座位 / 状态" }}</span>
        <strong>
          {{
            isSpectator
              ? "上帝"
              : `${room.viewer.seat ?? "-"} / ${
                  room.viewer.is_alive === false ? "已出局" : "存活"
                }`
          }}
        </strong>
      </article>
      <article class="metric">
        <span>真人 / AI</span>
        <strong>{{ humanCount }} / {{ aiCount }}</strong>
      </article>
      <article class="metric">
        <span>天数 / 阶段</span>
        <strong>{{ room.day }} / {{ room.phase }}</strong>
      </article>
    </div>

    <div v-if="spectatorPassword && !isSpectator" class="credential-row">
      <span>本局观战密码</span>
      <code>{{ spectatorPassword }}</code>
    </div>

    <section
      v-if="witchKillTarget"
      class="private-info-panel"
      data-testid="witch-kill-target"
    >
      <span>女巫夜间信息</span>
      <strong>{{ witchKillTarget }}</strong>
    </section>

    <section class="panel roster-panel" data-testid="player-roster">
      <div class="section-heading">
        <h2>九人席位</h2>
        <span>{{ isSpectator ? "上帝视角" : "按可见事件显示" }}</span>
      </div>
      <div class="roster-grid">
        <article
          v-for="player in room.players"
          :key="player.player_id"
          class="roster-player"
          :data-alive="player.is_alive"
          :data-player-id="player.player_id"
        >
          <div class="roster-heading">
            <span>{{ player.seat }}号</span>
            <strong>{{ player.name }}</strong>
            <small>
              {{
                player.is_human
                  ? "真人"
                  : archetypeLabel(player.archetype)
                    ? `AI · ${archetypeLabel(player.archetype)}`
                    : "AI"
              }}
            </small>
          </div>
          <div class="roster-meta">
            <span>{{ visibleRole(player.player_id) }}</span>
            <span>{{ playerStatus(player) }}</span>
          </div>
        </article>
      </div>
    </section>

    <AgentInsightPanel
      v-if="showAgentInsights && room.agent_insights.length"
      :agents="room.agent_insights"
      :players="room.players"
      :spectator="isSpectator"
    />

    <section class="panel action-panel">
      <div class="section-heading">
        <h2>{{ isSpectator ? "观战模式" : "当前动作" }}</h2>
        <span>
          {{
            isSpectator
              ? "只读"
              : room.viewer.is_host
                ? "房主"
                : "等待房主"
          }}
        </span>
      </div>

      <div
        v-if="!isSpectator && room.available_actions.length"
        class="action-grid"
      >
        <ActionForm
          v-for="availableAction in room.available_actions"
          :key="availableAction.action"
          :action="availableAction"
          :players="room.players"
          :busy="busy"
          @submit="emit('action', $event)"
        />
        <button
          v-if="canUseAiStart"
          class="secondary-button"
          type="button"
          :disabled="busy"
          @click="emit('aiAction')"
        >
          AI 推荐并执行
        </button>
      </div>
      <p v-else-if="isSpectator" class="muted" data-testid="spectator-readonly">
        观战者没有玩家动作。身份与死因只来自服务端返回的可见事件。
      </p>
      <p v-else-if="gameEnded" class="muted">
        对局已经结束，不能继续提交动作。
      </p>
      <p v-else class="muted">
        当前没有属于你的合法动作。请等待其他玩家或系统推进。
      </p>
      <p v-if="aiNotice" class="ai-notice">{{ aiNotice }}</p>
      <p
        v-if="actionNotice"
        class="action-notice"
        data-testid="action-notice"
      >
        {{ actionNotice }}
      </p>
    </section>

    <GameResultPanel
      v-if="gameEnded"
      :events="events"
      :players="room.players"
      :insights="room.agent_insights"
    />

    <section class="panel chat-panel">
      <div class="section-heading">
        <h2>与 AI 对话</h2>
        <span class="muted">只使用公开信息</span>
      </div>
      <ol v-if="chatLog.length" class="chat-list">
        <li
          v-for="(item, index) in chatLog"
          :key="index"
          class="chat-line"
          :class="item.role === 'me' ? 'chat-me' : 'chat-ai'"
        >
          <span class="chat-who">{{
            item.role === "me"
              ? "我"
              : item.seat
                ? `${item.seat} 号`
                : "AI"
          }}</span>
          <p class="chat-text">{{ item.text }}</p>
        </li>
      </ol>
      <p v-else class="muted">
        问 AI 一句，比如“你怎么看 5 号？”
      </p>
      <form class="chat-form" @submit.prevent="submitChat">
        <input
          v-model="chatInput"
          maxlength="200"
          placeholder="对 AI 说点什么…"
        />
        <button
          class="primary-button"
          type="submit"
          :disabled="!chatInput.trim()"
        >
          发送
        </button>
      </form>
    </section>

    <section class="panel">
      <div class="section-heading">
        <h2>服务器事件</h2>
        <span>{{ events.length }} 条</span>
      </div>
      <ol class="event-list">
        <li
          v-for="event in [...events].reverse()"
          :key="event.event_seq"
          class="event-row"
        >
          <span class="event-index">#{{ event.event_seq }}</span>
          <div>
            <strong>{{ event.event_type }}</strong>
            <p>
              {{ event.actor_id ?? "系统" }}
              <template v-if="event.target_id">
                → {{ event.target_id }}
              </template>
            </p>
            <code v-if="Object.keys(event.data).length">
              {{ JSON.stringify(event.data) }}
            </code>
          </div>
        </li>
      </ol>
      <p v-if="!events.length" class="muted">还没有收到事件。</p>
    </section>
      </main>

      <aside class="room-side">
        <section class="panel feed-panel">
          <div class="section-heading">
            <h2>对局直播</h2>
            <span v-if="isSpectator" class="muted">上帝视角</span>
            <span v-else class="muted">
              {{ visibleFeed.length }}/{{ feedItems.length }} 条
            </span>
          </div>
          <ol
            v-if="feedItems.length"
            ref="feedList"
            class="speech-list feed-scroll"
            @scroll="onFeedScroll"
          >
            <template v-for="event in visibleFeed" :key="event.event_seq">
              <li
                v-if="isSpeech(event)"
                class="speech-bubble"
                :class="{
                  'speech-wolf': event.event_type === 'WOLF_SPEECH',
                  'speech-last-words': event.event_type === 'LAST_WORDS',
                  'speech-own': event.actor_id === room.viewer.player_id,
                }"
              >
                <div class="speech-meta">
                  <span class="speech-speaker">{{ speakerLabel(event) }}</span>
                  <span class="speech-kind">{{
                    event.event_type === "WOLF_SPEECH"
                      ? "狼队频道"
                      : event.event_type === "LAST_WORDS"
                        ? "遗言"
                        : "公开发言"
                  }}</span>
                </div>
                <p class="speech-text">{{ speechText(event) }}</p>
              </li>
              <li v-else class="feed-system">
                <span class="feed-tag">系统</span>
                <span>{{ systemText(event) }}</span>
              </li>
            </template>
          </ol>
          <p v-else class="muted">还没有对局事件。</p>
          <div v-if="pendingFeedCount" class="feed-more">
            <button class="primary-button" type="button" @click="revealNext">
              继续 · 还有 {{ pendingFeedCount }} 条
            </button>
            <button class="text-button" type="button" @click="revealAll">
              全部显示
            </button>
          </div>
        </section>
      </aside>
    </div>
  </section>
</template>
