<script setup lang="ts">
import { computed } from "vue";

import type { AgentInsight, PublicPlayer } from "../types";

const props = defineProps<{
  agents: AgentInsight[];
  players: PublicPlayer[];
  spectator: boolean;
}>();

const archetypeLabels: Record<string, string> = {
  aggressive: "冲锋型",
  steady: "稳健型",
  logical: "逻辑型",
  chaotic: "搅局型",
};

const toolNameLabels: Record<string, string> = {
  audit_logic: "逻辑审计",
  analyze_votes: "票型分析",
  search_tactics: "战术检索",
};

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

const playerById = computed(
  () => new Map(props.players.map((player) => [player.player_id, player])),
);

function archetypeLabel(archetype: string | null | undefined): string {
  return archetype ? archetypeLabels[archetype] ?? archetype : "";
}

function toolNameLabel(name: unknown): string {
  return typeof name === "string" ? toolNameLabels[name] ?? name : "";
}

function phaseLabel(phase: string): string {
  return phaseLabels[phase] ?? phase;
}

function targetSeat(playerId: string | null): string {
  if (!playerId) {
    return "";
  }
  const player = playerById.value.get(playerId);
  return player ? `${player.seat}号` : playerId;
}
</script>

<template>
  <section class="panel agent-insight-panel" data-testid="agent-insights">
    <div class="section-heading">
      <h2>AI 决策</h2>
      <span>{{ spectator ? "上帝视角" : "赛后复盘" }}</span>
    </div>
    <article
      v-for="agent in agents"
      :key="agent.player_id"
      class="agent-insight"
    >
      <div class="agent-insight-head">
        <strong>{{ agent.seat }}号 {{ agent.name }}</strong>
        <span class="chip" :class="'chip-' + agent.archetype">
          {{ archetypeLabel(agent.archetype) }}
        </span>
      </div>
      <p v-if="agent.current_plan" class="agent-plan">
        {{ agent.current_plan }}
      </p>
      <ol v-if="agent.decision_traces.length" class="trace-list">
        <li
          v-for="(trace, index) in [...agent.decision_traces].reverse().slice(0, 5)"
          :key="index"
          class="trace-row"
        >
          <span class="trace-phase">{{ phaseLabel(trace.phase) }}</span>
          <span class="trace-action">
            {{ trace.action }}
            <template v-if="trace.target_id">
              → {{ targetSeat(trace.target_id) }}
            </template>
          </span>
          <span v-if="trace.tool_calls.length" class="trace-tools">
            <span
              v-for="(call, callIndex) in trace.tool_calls"
              :key="callIndex"
              class="tool-chip"
            >
              {{ toolNameLabel(call.name) }}
            </span>
          </span>
          <span v-if="trace.tactic_ids.length" class="trace-tactics">
            战术：{{ trace.tactic_ids.join("、") }}
          </span>
        </li>
      </ol>
      <p v-else class="muted">还没有决策记录。</p>
    </article>
  </section>
</template>
