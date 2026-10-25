<script setup lang="ts">
import { reactive } from "vue";

defineProps<{
  busy: boolean;
}>();

const emit = defineEmits<{
  create: [nickname: string];
  join: [payload: { roomId: string; nickname: string }];
  watch: [payload: { roomId: string; password: string }];
}>();

const form = reactive({
  nickname: "",
  roomId: "",
  spectatorPassword: "",
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

function watchRoom(): void {
  const code = form.roomId.trim();
  const password = form.spectatorPassword.trim();
  if (code && password) {
    emit("watch", { roomId: code, password });
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

    <section class="lobby-section">
      <h2>玩家入口</h2>
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
          autocapitalize="off"
          spellcheck="false"
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

    <section class="lobby-section spectator-entry">
      <h2>观战入口</h2>
      <p class="lobby-note">
        观战者通过 WebSocket 认证后进入上帝视角，不能提交玩家动作。
      </p>
      <label class="field">
        <span>观战密码</span>
        <input
          v-model="form.spectatorPassword"
          type="password"
          maxlength="64"
          autocomplete="off"
          placeholder="输入房主提供的本局密码"
        />
      </label>
      <button
        class="secondary-button"
        type="button"
        :disabled="
          busy || !form.roomId.trim() || !form.spectatorPassword.trim()
        "
        @click="watchRoom"
      >
        进入观战
      </button>
    </section>
  </section>
</template>
