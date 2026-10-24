<script setup lang="ts">
import { computed } from "vue";

import type { ConnectionState } from "../types";

const props = defineProps<{
  state: ConnectionState;
}>();

const emit = defineEmits<{
  reconnect: [];
}>();

const label = computed(() => {
  const labels: Record<ConnectionState, string> = {
    idle: "未连接",
    connecting: "正在连接",
    authenticating: "正在认证",
    connected: "已连接",
    disconnected: "连接已断开",
    error: "连接失败",
  };
  return labels[props.state];
});

const canReconnect = computed(
  () => props.state === "disconnected" || props.state === "error",
);
</script>

<template>
  <div class="connection-status" :data-state="state">
    <span class="status-dot" />
    <span>{{ label }}</span>
    <button
      v-if="canReconnect"
      class="text-button"
      type="button"
      @click="emit('reconnect')"
    >
      重新连接
    </button>
  </div>
</template>
