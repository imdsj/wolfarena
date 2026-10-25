<script setup lang="ts">
import { computed, reactive, watch } from "vue";

import type {
  ActionSubmission,
  AvailableAction,
  PublicPlayer,
} from "../types";

const props = defineProps<{
  action: AvailableAction;
  players: PublicPlayer[];
  busy: boolean;
}>();

const emit = defineEmits<{
  submit: [payload: ActionSubmission];
}>();

const form = reactive({
  targetId: "",
  content: "",
  choice: "",
});

watch(
  () => props.action,
  (action) => {
    form.targetId = action.requires_target ? action.target_ids[0] ?? "" : "";
    form.content = "";
    form.choice = action.choices[0] ?? "";
  },
  { immediate: true },
);

const playersById = computed(
  () => new Map(props.players.map((player) => [player.player_id, player])),
);

const noTargetLabel = computed(() => {
  if (props.action.action === "vote") {
    return "弃权";
  }
  if (
    props.action.action === "night_hunter_shot" ||
    props.action.action === "day_hunter_shot"
  ) {
    return "不开枪";
  }
  if (props.action.action === "wolf_kill") {
    return "空刀";
  }
  return "不选择目标";
});

function playerLabel(playerId: string): string {
  const player = playersById.value.get(playerId);
  return player ? `${player.seat}号 ${player.name}` : playerId;
}

function submit(): void {
  emit("submit", {
    action: props.action.action,
    target_id:
      form.targetId && form.targetId !== "__none__" ? form.targetId : null,
    content: props.action.requires_content ? form.content.trim() : null,
    choice: props.action.choices.length ? form.choice : null,
  });
}
</script>

<template>
  <form class="action-card" @submit.prevent="submit">
    <div class="action-card-heading">
      <strong>{{ action.label }}</strong>
      <code>{{ action.action }}</code>
    </div>

    <label v-if="action.choices.length" class="compact-field">
      <span>行动选项</span>
      <select v-model="form.choice">
        <option v-for="choice in action.choices" :key="choice" :value="choice">
          {{ choice }}
        </option>
      </select>
    </label>

    <label v-if="action.target_ids.length" class="compact-field">
      <span>目标</span>
      <select v-model="form.targetId">
        <option v-if="action.allow_no_target" value="__none__">
          {{ noTargetLabel }}
        </option>
        <option
          v-for="targetId in action.target_ids"
          :key="targetId"
          :value="targetId"
        >
          {{ playerLabel(targetId) }}
        </option>
      </select>
    </label>

    <label v-if="action.requires_content" class="compact-field">
      <span>发言内容</span>
      <textarea
        v-model="form.content"
        maxlength="500"
        rows="3"
        placeholder="输入要提交给服务器的内容"
      />
    </label>

    <button
      class="primary-button"
      type="submit"
      :disabled="
        busy ||
        (action.requires_content && !form.content.trim()) ||
        (action.requires_target && (!form.targetId || form.targetId === '__none__'))
      "
    >
      执行
    </button>
  </form>
</template>
