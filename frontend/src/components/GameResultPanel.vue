<script setup lang="ts">
import { computed } from "vue";

import type { GameEvent, PublicPlayer } from "../types";

const props = defineProps<{
  events: GameEvent[];
  players: PublicPlayer[];
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
  </section>
</template>
