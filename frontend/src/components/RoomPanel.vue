<script setup lang="ts">
import { computed, ref } from "vue";

import type {
  ActionSubmission,
  GameEvent,
  RoomSnapshot,
} from "../types";
import ActionForm from "./ActionForm.vue";
import ConnectionStatus from "./ConnectionStatus.vue";
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
const canStartNight = computed(
  () =>
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
        <span>当前身份</span>
        <strong>{{ room.viewer.role ?? "观战者" }}</strong>
      </article>
      <article class="metric">
        <span>座位</span>
        <strong>{{ room.viewer.seat ?? "-" }}</strong>
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

    <div v-if="spectatorPassword" class="credential-row">
      <span>本局观战密码</span>
      <code>{{ spectatorPassword }}</code>
    </div>

    <section class="panel action-panel">
      <div class="section-heading">
        <h2>当前动作</h2>
        <span>{{ room.viewer.is_host ? "房主" : "等待房主" }}</span>
      </div>

      <div v-if="room.available_actions.length" class="action-grid">
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
      <p v-else class="muted">
        当前没有属于你的合法动作。请等待其他玩家或系统推进。
      </p>
      <p v-if="aiNotice" class="ai-notice">{{ aiNotice }}</p>
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
  </section>
</template>
