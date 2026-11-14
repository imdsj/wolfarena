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
const entryMode = ref<"create" | "join" | "watch">("create");
const buildId =
  (globalThis as { __WOLFARENA_BUILD__?: string }).__WOLFARENA_BUILD__ ??
  "dev";

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
  <section class="lobby-shell">
    <div class="lobby-hero">
      <div class="game-brand">
        <span class="brand-mark">狼</span>
        <div><strong>WOLFARENA</strong><small>狼 域 · 社 交 推 理 竞 技 场</small></div>
      </div>

      <div class="hero-copy">
        <div class="hero-kicker"><span /> 九名玩家入场，真相开始发酵</div>
        <h1>天黑请闭眼。<br /><em>AI 已入场。</em></h1>
        <p>
          每一次发言都在改变阵营胜率。九个独立 Agent 现场制定战术、
          识别漏洞，并从上一局学会下一局的打法。
        </p>
      </div>

      <div class="arena-orbit" aria-hidden="true">
        <div class="orbit-ring orbit-ring-outer" />
        <div class="orbit-ring orbit-ring-inner" />
        <div class="orbit-core"><span>狼</span><small>第 1 夜</small></div>
        <span
          v-for="seat in 9"
          :key="seat"
          class="orbit-seat"
          :style="{ '--seat-index': seat - 1 }"
        >{{ seat }}</span>
        <span class="orbit-caption">9 SEATS · 4 PERSONAS · 1 HIDDEN TRUTH</span>
      </div>

      <div class="hero-features">
        <article><b>09</b><span>独立 AI Agent</span></article>
        <article><b>04</b><span>差异化策略人格</span></article>
        <article><b>LIVE</b><span>实时胜率与战术演化</span></article>
      </div>
    </div>

    <section class="panel lobby-panel">
      <div class="lobby-card-head">
        <div>
          <div class="eyebrow">GAME LOBBY</div>
          <h2>进入狼域</h2>
        </div>
        <span class="online-pill"><i /> 服务在线</span>
      </div>

      <div class="entry-tabs" role="tablist" aria-label="进入方式">
        <button type="button" :class="{ active: entryMode === 'create' }" @click="entryMode = 'create'">创建对局</button>
        <button type="button" :class="{ active: entryMode === 'join' }" @click="entryMode = 'join'">加入房间</button>
        <button type="button" :class="{ active: entryMode === 'watch' }" @click="entryMode = 'watch'">上帝观战</button>
      </div>

      <form v-if="entryMode === 'create'" class="entry-form" @submit.prevent="createRoom">
        <div class="entry-intro">
          <strong>主持一场九人局</strong>
          <span>你与八位 AI 玩家同场竞技，可随时邀请好友观战。</span>
        </div>
        <label class="field">
          <span>你的昵称</span>
          <input v-model="form.nickname" maxlength="32" autocomplete="off" placeholder="输入入场昵称" autofocus />
        </label>
        <button class="primary-button game-entry-button" type="submit" :disabled="busy || !form.nickname.trim()">
          <span>{{ busy ? "正在布置牌桌…" : "创建房间" }}</span>
        </button>
        <p class="entry-hint">创建后会获得房间号和专属观战密码</p>
      </form>

      <form v-else-if="entryMode === 'join'" class="entry-form" @submit.prevent="joinRoom">
        <div class="entry-intro">
          <strong>回到你的座位</strong>
          <span>输入房主分享的房间号，选择空座加入。</span>
        </div>
        <label class="field">
          <span>你的昵称</span>
          <input v-model="form.nickname" maxlength="32" autocomplete="off" placeholder="输入入场昵称" />
        </label>
        <label class="field">
          <span>房间号</span>
          <div class="room-code-input">
            <input v-model="form.roomId" maxlength="32" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="区分大小写" />
            <button class="text-button" type="button" :disabled="busy || seatsLoading || !form.roomId.trim()" @click="loadSeats">
              {{ seatsLoading ? "查询中" : "查空座" }}
            </button>
          </div>
        </label>
        <div v-if="seats.length" class="seat-picker">
          <span class="seat-picker-label">选择你的座位</span>
          <div class="seat-grid">
            <button v-for="seat in 9" :key="seat" type="button" class="seat-cell" :class="{ 'seat-taken': !seats.includes(seat), 'seat-selected': selectedSeat === seat }" :disabled="!seats.includes(seat)" @click="pickSeat(seat)">
              {{ seat }}
            </button>
          </div>
        </div>
        <p v-if="seatsError" class="entry-error">{{ seatsError }}</p>
        <button class="primary-button game-entry-button" type="submit" :disabled="busy || !form.nickname.trim() || !form.roomId.trim() || selectedSeat === null">
          <span>加入房间</span>
        </button>
      </form>

      <form v-else class="entry-form" @submit.prevent="watchRoom">
        <div class="entry-intro">
          <strong>以上帝视角观看</strong>
          <span>查看全部身份、狼队夜间战术、AI 决策和阵营胜率。</span>
        </div>
        <label class="field">
          <span>房间号</span>
          <input v-model="form.roomId" maxlength="32" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="输入要观战的房间号" />
        </label>
        <label class="field">
          <span>观战密码</span>
          <input v-model="form.spectatorPassword" type="password" maxlength="64" autocomplete="off" placeholder="输入房主提供的密码" />
        </label>
        <button class="primary-button game-entry-button" type="submit" :disabled="busy || !form.roomId.trim() || !form.spectatorPassword.trim()">
          <span>进入观战</span>
        </button>
        <p class="entry-hint">观战为只读模式，不会干扰对局</p>
      </form>

      <div class="lobby-assurance">
        <span>服务端权威规则</span><i />
        <span>实时 WebSocket</span><i />
        <span>AI 决策可解释</span>
      </div>
      <p class="lobby-build">WOLFARENA BUILD {{ buildId }}</p>
    </section>
  </section>
</template>
