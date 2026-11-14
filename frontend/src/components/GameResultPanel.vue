<script setup lang="ts">
import { computed } from "vue";

import type { AgentInsight, GameEvent, PublicPlayer } from "../types";

const props = defineProps<{
  events: GameEvent[];
  players: PublicPlayer[];
  insights: AgentInsight[];
}>();

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

const archetypeLabels: Record<string, string> = {
  aggressive: "冲锋型",
  steady: "稳健型",
  logical: "逻辑型",
  chaotic: "搅局型",
};

const winner = computed(() => {
  const event = [...props.events]
    .reverse()
    .find((candidate) => candidate.event_type === "WINNER_DECIDED");
  const value = event?.data.winner;
  return value === "wolf"
    ? "狼人阵营"
    : value === "good"
      ? "好人阵营"
      : "未决出";
});

const roles = computed(() => {
  const result = new Map<string, string>();
  for (const event of props.events) {
    const role = event.data.role;
    if (
      event.event_type === "ROLE_ASSIGNED" &&
      event.target_id &&
      typeof role === "string"
    ) {
      result.set(event.target_id, role);
    }
  }
  return result;
});

const deathCauses = computed(() => {
  const result = new Map<string, string[]>();
  for (const event of props.events) {
    if (event.event_type !== "PLAYER_DIED" || !event.target_id) {
      continue;
    }
    const causes = Array.isArray(event.data.causes)
      ? event.data.causes.filter(
          (cause): cause is string => typeof cause === "string",
        )
      : [];
    result.set(event.target_id, causes);
  }
  return result;
});

function playerRole(playerId: string): string {
  const role = roles.value.get(playerId);
  return role ? roleLabels[role] ?? role : "已揭示";
}

function playerOutcome(player: PublicPlayer): string {
  if (player.is_alive) {
    return "存活";
  }
  const causes = deathCauses.value.get(player.player_id) ?? [];
  return causes.length
    ? causes.map((cause) => deathCauseLabels[cause] ?? cause).join("、")
    : "已出局";
}

function archetypeLabel(archetype: string | null | undefined): string {
  return archetype ? archetypeLabels[archetype] ?? archetype : "";
}

interface TacticUse {
  id: string;
  aiInvented: boolean;
}

function usedTactics(agent: AgentInsight): TacticUse[] {
  const seen = new Set<string>();
  const uses: TacticUse[] = [];
  for (const trace of agent.decision_traces) {
    for (const id of trace.tactic_ids) {
      if (seen.has(id)) {
        continue;
      }
      seen.add(id);
      uses.push({ id, aiInvented: id.startsWith("cand.") });
    }
  }
  return uses;
}

function toolCount(agent: AgentInsight): number {
  return agent.decision_traces.reduce(
    (sum, trace) => sum + trace.tool_calls.length,
    0,
  );
}
</script>

<template>
  <section class="panel result-panel" data-testid="game-result">
    <div class="section-heading">
      <h2>对局结束</h2>
      <strong>{{ winner }}获胜</strong>
    </div>
    <p class="muted">
      游戏结束后，服务端已向当前视角揭示完整身份与死因。
    </p>
    <div class="result-grid">
      <article
        v-for="player in players"
        :key="player.player_id"
        class="result-player"
        :data-alive="player.is_alive"
      >
        <span>{{ player.seat }}号</span>
        <strong>{{ player.name }}</strong>
        <small
          v-if="!player.is_human && archetypeLabel(player.archetype)"
          class="result-archetype"
        >
          {{ archetypeLabel(player.archetype) }}
        </small>
        <dl>
          <div>
            <dt>身份</dt>
            <dd>{{ playerRole(player.player_id) }}</dd>
          </div>
          <div>
            <dt>结果</dt>
            <dd>{{ playerOutcome(player) }}</dd>
          </div>
        </dl>
      </article>
    </div>

    <section v-if="insights.length" class="review-panel">
      <div class="section-heading">
        <h2>AI 策略复盘</h2>
        <span>人格 · 战术 · 工具</span>
      </div>
      <article
        v-for="agent in insights"
        :key="agent.player_id"
        class="review-agent"
      >
        <div class="review-agent-head">
          <strong>{{ agent.seat }}号 {{ agent.name }}</strong>
          <span class="chip" :class="'chip-' + agent.archetype">
            {{ archetypeLabel(agent.archetype) }}
          </span>
          <span class="muted">调用工具 {{ toolCount(agent) }} 次</span>
        </div>
        <p v-if="usedTactics(agent).length" class="review-tactics">
          <span
            v-for="use in usedTactics(agent)"
            :key="use.id"
            class="tactic-chip"
            :class="{ 'tactic-invented': use.aiInvented }"
          >
            {{ use.id }}<template v-if="use.aiInvented"> · AI 发明</template>
          </span>
        </p>
        <p v-else class="muted">本局未命中战术库。</p>
      </article>
    </section>
  </section>
</template>
