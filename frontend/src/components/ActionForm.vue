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

const aliveTargetIds = computed(() => {
  const aliveIds = new Set(
    props.players
      .filter((player) => player.is_alive)
      .map((player) => player.player_id),
  );
  return props.action.target_ids.filter((playerId) => aliveIds.has(playerId));
});

const showTargetPicker = computed(() => {
  if (props.action.action !== "witch_action") {
    return (
      aliveTargetIds.value.length > 0 &&
      (props.action.requires_target || props.action.allow_no_target)
    );
  }
  return (
    aliveTargetIds.value.length > 0 &&
    (form.choice === "antidote" || form.choice === "poison")
  );
});

const needsSelectedTarget = computed(() => {
  if (props.action.action !== "witch_action") {
    return props.action.requires_target;
  }
  return form.choice === "antidote" || form.choice === "poison";
});

const actionSignature = computed(() =>
  [
    props.action.action,
    props.action.requires_target,
    props.action.allow_no_target,
    props.action.requires_content,
    props.action.target_ids.join(","),
    props.action.choices.join(","),
  ].join("|"),
);

let lastActionName = "";

watch(
  actionSignature,
  () => {
    if (props.action.action !== lastActionName) {
      form.content = "";
      lastActionName = props.action.action;
    }
    form.targetId = props.action.requires_target
      ? aliveTargetIds.value[0] ?? ""
      : props.action.allow_no_target
        ? "__none__"
        : aliveTargetIds.value[0] ?? "";
    form.choice = props.action.choices[0] ?? "";
  },
  { immediate: true },
);

watch(
  () => form.choice,
  (choice) => {
    if (
      props.action.action === "witch_action" &&
      (choice === "none" || choice === "")
    ) {
      form.targetId = "__none__";
    } else if (form.targetId === "__none__") {
      form.targetId = aliveTargetIds.value[0] ?? "";
    }
  },
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

const choiceLabels: Record<string, string> = {
  none: "不使用",
  antidote: "解药",
  poison: "毒药",
};

function choiceLabel(choice: string): string {
  return choiceLabels[choice] ?? choice;
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

    <div v-if="action.choices.length" class="compact-field">
      <span>行动选项</span>
      <div class="chip-grid">
        <button
          v-for="choice in action.choices"
          :key="choice"
          type="button"
          class="chip"
          :class="{ 'chip-active': form.choice === choice }"
          @click="form.choice = choice"
        >
          {{ choiceLabel(choice) }}
        </button>
      </div>
    </div>

    <div
      v-if="showTargetPicker"
      class="compact-field"
    >
      <span>目标</span>
      <div class="chip-grid">
        <button
          v-if="action.allow_no_target"
          type="button"
          class="chip"
          :class="{ 'chip-active': form.targetId === '__none__' }"
          @click="form.targetId = '__none__'"
        >
          {{ noTargetLabel }}
        </button>
        <button
          v-for="targetId in aliveTargetIds"
          :key="targetId"
          type="button"
          class="chip"
          :class="{ 'chip-active': form.targetId === targetId }"
          @click="form.targetId = targetId"
        >
          {{ playerLabel(targetId) }}
        </button>
      </div>
    </div>

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
      :data-busy="busy"
      :data-target="form.targetId"
      :data-choice="form.choice"
      :disabled="
        busy ||
        (action.requires_content && !form.content.trim()) ||
        (needsSelectedTarget &&
          (!form.targetId || form.targetId === '__none__'))
      "
    >
      提交{{ action.label }}
    </button>
  </form>
</template>
