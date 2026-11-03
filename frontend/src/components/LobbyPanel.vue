<script setup lang="ts">
import { reactive, ref } from "vue";

defineProps<{
  busy: boolean;
}>();

const emit = defineEmits<{
  create: [nickname: string];
  join: [payload: { roomId: string; nickname: string; seat: number }];
  watch: [payload: { roomId: string; password: string }];
}>();

const form = reactive({
  nickname: "",
  roomId: "",
  spectatorPassword: "",
});
const seats = ref<number[]>([]);
const selectedSeat = ref<number | null>(null);
const seatsLoading = ref(false);
const seatsError = ref("");

function createRoom(): void {
  const name = form.nickname.trim();
  if (name) {
    emit("create", name);
  }
}

async function loadSeats(): Promise<void> {
  const code = form.roomId.trim();
  if (!code) {
    return;
  }
  seatsLoading.value = true;
  seatsError.value = "";
  try {
    const response = await fetch(
      `/api/rooms/${encodeURIComponent(code)}/seats`,
    );
    if (!response.ok) {
      throw new Error("查询空座失败");
    }
    const payload = (await response.json()) as {
      available_seats: number[];
    };
    seats.value = payload.available_seats ?? [];
    if (
      selectedSeat.value !== null &&
      !seats.value.includes(selectedSeat.value)
    ) {
      selectedSeat.value = null;
    }
  } catch {
    seats.value = [];
    seatsError.value = "查不到这个房间或房间已满";
  } finally {
    seatsLoading.value = false;
  }
}

function pickSeat(seat: number): void {
  selectedSeat.value = seat;
}

function joinRoom(): void {
  const name = form.nickname.trim();
  const code = form.roomId.trim();
  const seat = selectedSeat.value ?? (seats.value[0] ?? null);
  if (name && code && seat !== null) {
    emit("join", { roomId: code, nickname: name, seat });
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
        class="text-button"
        type="button"
        :disabled="busy || seatsLoading || !form.roomId.trim()"
        @click="loadSeats"
      >
        {{ seatsLoading ? "查询中…" : "查询空座" }}
      </button>

      <div v-if="seats.length" class="seat-picker">
        <span class="seat-picker-label">选择座位</span>
        <div class="seat-grid">
          <button
            v-for="seat in 9"
            :key="seat"
            type="button"
            class="seat-cell"
            :class="{
              'seat-taken': !seats.includes(seat),
              'seat-selected': selectedSeat === seat,
            }"
            :disabled="!seats.includes(seat)"
            @click="pickSeat(seat)"
          >
            {{ seat }}
          </button>
        </div>
      </div>
      <p v-if="seatsError" class="muted">{{ seatsError }}</p>

      <button
        class="secondary-button"
        type="button"
        :disabled="
          busy ||
          !form.nickname.trim() ||
          !form.roomId.trim() ||
          selectedSeat === null
        "
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
