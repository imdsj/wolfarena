<script setup lang="ts">
import { reactive } from "vue";

defineProps<{
  busy: boolean;
}>();

const emit = defineEmits<{
  create: [nickname: string];
  join: [payload: { roomId: string; nickname: string }];
}>();

const form = reactive({
  nickname: "",
  roomId: "",
});

function createRoom(): void {
  const name = form.nickname.trim();
  if (name) {
    emit("create", name);
  }
}

function joinRoom(): void {
  const name = form.nickname.trim();
  const code = form.roomId.trim();
  if (name && code) {
    emit("join", { roomId: code, nickname: name });
  }
}
</script>

<template>
  <section class="panel lobby-panel">
    <div class="eyebrow">WolfArena / 九人局入口</div>
    <h1>先进入房间，再观察真实事件流</h1>
    <p class="lede">
      页面只显示服务器已经返回的状态。连接断开时会明确标记，不会保留虚假的“在线”。
    </p>

    <label class="field">
      <span>你的昵称</span>
      <input
        v-model="form.nickname"
        maxlength="32"
        autocomplete="off"
        placeholder="例如：订书机"
      />
    </label>

    <button
      class="primary-button"
      type="button"
      :disabled="busy || !form.nickname.trim()"
      @click="createRoom"
    >
      创建房间
    </button>

    <div class="divider"><span>或者加入已有房间</span></div>

    <label class="field">
      <span>房间号</span>
      <input
        v-model="form.roomId"
        maxlength="32"
        autocomplete="off"
        placeholder="粘贴房主发来的房间号"
      />
    </label>

    <button
      class="secondary-button"
      type="button"
      :disabled="busy || !form.nickname.trim() || !form.roomId.trim()"
      @click="joinRoom"
    >
      加入房间
    </button>
  </section>
</template>
