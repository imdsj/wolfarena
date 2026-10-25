<script setup lang="ts">
import { computed, ref } from "vue";

import type {
  ActionSubmission,
  GameEvent,
  RoomSnapshot,
} from "../types";
import ActionForm from "./ActionForm.vue";
import ConnectionStatus from "./ConnectionStatus.vue";
import GameResultPanel from "./GameResultPanel.vue";
import PhaseCountdown from "./PhaseCountdown.vue";

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
}>();

const emit = defineEmits<{
  action: [action: ActionSubmission];
  aiAction: [];
  reconnect: [];
  leave: [];
}>();

const copyLabel = ref("复制房间号");

const humanCount = computed(
  () => props.room.players.filter((player) => player.is_human).length,
);
const aiCount = computed(() => props.room.players.length - humanCount.value);
const isSpectator = computed(() => props.room.viewer.kind === "spectator");
const isDeadPlayer = computed(
  () => !isSpectator.value && props.room.viewer.is_alive === false,
);
const gameEnded = computed(() => props.room.phase === "END");
const roleLabels: Record<string, string> = {
  werewolf: "狼人",
  villager: "村民",
  seer: "预言家",
  witch: "女巫",
  hunter: "猎人",
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
</script>

<template>
  <section class="room-shell">
    <header class="room-header">
      <div>
        <div class="room-identity">
          <div class="eyebrow room-code">
            房间 <code>{{ room.room_id }}</code>
          </div>
          <button class="text-button copy-room-id" type="button" @click="copyRoomId">
            {{ copyLabel }}
          </button>
        </div>
        <h1>{{ phaseLabel(room.phase) }}</h1>
      </div>
      <button class="text-button" type="button" @click="emit('leave')">
        离开
      </button>
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
      <span>页面仍保持玩家视角，只能看到服务端允许你看到的信息。</span>
    </section>

    <PhaseCountdown
      v-if="
        room.deadline_kind !== null &&
        room.deadline_at !== null &&
        room.remaining_ms !== null
      "
      :deadline-kind="room.deadline_kind"
      :remaining-ms="room.remaining_ms"
      :server-time="room.server_time"
      :deadline-at="room.deadline_at"
    />

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
            <small>{{ player.is_human ? "真人" : "AI" }}</small>
          </div>
          <div class="roster-meta">
            <span>{{ visibleRole(player.player_id) }}</span>
            <span>{{ playerStatus(player) }}</span>
          </div>
        </article>
      </div>
    </section>

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
    />

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
  </section>
</template>
