<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";

import type { DeadlineKind } from "../types";

const props = defineProps<{
  deadlineKind: DeadlineKind;
  remainingMs: number;
  serverTime: number;
  deadlineAt: number;
}>();

const remainingMilliseconds = ref(Math.max(0, props.remainingMs));
let anchorMilliseconds = 0;
let anchorTimestamp = 0;
let updateTimer: ReturnType<typeof setInterval> | null = null;

const labels: Record<DeadlineKind, string> = {
  last_words: "遗言倒计时",
  speech: "公开发言倒计时",
  self_destruct: "自爆窗口",
  human_action: "行动倒计时",
};

const expired = computed(() => remainingMilliseconds.value <= 0);
const urgent = computed(
  () => !expired.value && remainingMilliseconds.value <= 5000,
);
const secondsText = computed(
  () => (remainingMilliseconds.value / 1000).toFixed(1),
);

function resetCountdown(): void {
  anchorMilliseconds = Math.max(0, props.remainingMs);
  anchorTimestamp = performance.now();
  remainingMilliseconds.value = anchorMilliseconds;
}

function updateCountdown(): void {
  const elapsed = performance.now() - anchorTimestamp;
  remainingMilliseconds.value = Math.max(
    0,
    anchorMilliseconds - elapsed,
  );
}

watch(
  () => [props.serverTime, props.deadlineAt, props.remainingMs],
  resetCountdown,
  { immediate: true },
);

onMounted(() => {
  updateTimer = setInterval(updateCountdown, 100);
});

onBeforeUnmount(() => {
  if (updateTimer !== null) {
    clearInterval(updateTimer);
  }
});
</script>

<template>
  <section
    class="phase-countdown"
    :class="{ 'phase-countdown-urgent': urgent || expired }"
    :data-deadline-kind="deadlineKind"
    role="timer"
    :aria-label="`${labels[deadlineKind]}，剩余 ${secondsText} 秒`"
  >
    <div>
      <span class="eyebrow">服务端截止时间</span>
      <strong>{{ labels[deadlineKind] }}</strong>
    </div>
    <div class="countdown-value" aria-hidden="true">
      <span>{{ expired ? "等待服务端推进" : secondsText }}</span>
      <small v-if="!expired">秒</small>
    </div>
  </section>
</template>
