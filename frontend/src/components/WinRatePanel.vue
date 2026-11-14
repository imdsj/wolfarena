<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";

import type { WinRatePoint, WinRatePrediction } from "../types";

const props = defineProps<{
  roomId: string;
  timeline: WinRatePoint[];
  predictions: WinRatePrediction[];
  accessPassword: string;
}>();

const localPredictions = ref<Record<number, WinRatePrediction>>({});
const running = ref(false);
const errorMessage = ref("");
let disposed = false;
let generation = 0;

const predictionMap = computed(() => {
  const merged: Record<number, WinRatePrediction> = {};
  for (const prediction of props.predictions) {
    merged[prediction.event_seq] = prediction;
  }
  return { ...merged, ...localPredictions.value };
});

const displayPoints = computed(() =>
  props.timeline.map((point) => {
    const prediction = predictionMap.value[point.event_seq];
    return prediction
      ? { ...point, good: prediction.good, wolf: prediction.wolf }
      : point;
  }),
);

const latest = computed(() => displayPoints.value.at(-1) ?? null);
const latestPrediction = computed(() => {
  const values = Object.values(predictionMap.value);
  return values.sort((a, b) => a.event_seq - b.event_seq).at(-1) ?? null;
});

function percent(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${(value * 100).toFixed(1)}%`;
}

function coordinates(points: Array<{ good: number }>): string {
  if (!points.length) {
    return "";
  }
  return points
    .map((point, index) => {
      const x = points.length === 1 ? 360 : 36 + (index * 648) / (points.length - 1);
      const y = 150 - point.good * 120;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

const baselinePath = computed(() => coordinates(props.timeline));
const combinedPath = computed(() => coordinates(displayPoints.value));
const recentPoints = computed(() => [...displayPoints.value].reverse().slice(0, 6));

function sourceLabel(source: string | undefined): string {
  if (source === "deepseek_hybrid") return "DeepSeek + 统计模型";
  if (source === "result_confirmed") return "规则引擎确认";
  return "统计模型回退";
}

async function pump(): Promise<void> {
  if (running.value || !props.accessPassword || !props.roomId) return;
  const currentGeneration = generation;
  running.value = true;
  errorMessage.value = "";
  try {
    while (true) {
      const point = props.timeline.find(
        (candidate) => !predictionMap.value[candidate.event_seq],
      );
      if (!point) break;
      if (disposed || currentGeneration !== generation) return;
      const response = await fetch(
        `/api/rooms/${encodeURIComponent(props.roomId)}/win-rate/${point.event_seq}`,
        {
          method: "POST",
          headers: { "X-Spectator-Password": props.accessPassword },
        },
      );
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload?.detail?.message ?? "胜率预测失败");
      }
      if (disposed || currentGeneration !== generation) return;
      localPredictions.value = {
        ...localPredictions.value,
        [point.event_seq]: payload as WinRatePrediction,
      };
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "胜率预测失败";
  } finally {
    if (currentGeneration === generation) running.value = false;
  }
}

watch(
  () => props.predictions,
  (values) => {
    const merged = { ...localPredictions.value };
    for (const value of values) merged[value.event_seq] = value;
    localPredictions.value = merged;
  },
  { immediate: true, deep: true },
);

watch(
  () => props.roomId,
  () => {
    generation += 1;
    localPredictions.value = {};
    running.value = false;
    void pump();
  },
  { immediate: true },
);

watch(
  () => props.timeline.length,
  () => void pump(),
);

onBeforeUnmount(() => {
  disposed = true;
  generation += 1;
});
</script>

<template>
  <section class="panel win-rate-panel" data-testid="win-rate-panel">
    <div class="section-heading">
      <div>
        <div class="eyebrow">PUBLIC INFORMATION ONLY</div>
        <h2>阵营胜率预测</h2>
      </div>
      <span class="model-live" :class="{ 'model-loading': running }">
        {{ running ? "DeepSeek 评估中…" : sourceLabel(latestPrediction?.source) }}
      </span>
    </div>

    <p class="muted win-rate-note">
      只读取公开发言、公开票型和出局事件，不读取真实身份、狼队私聊或夜间刀口。
    </p>

    <div class="win-rate-summary">
      <article class="faction-good">
        <span>好人阵营</span>
        <strong>{{ percent(latest?.good) }}</strong>
      </article>
      <article class="faction-wolf">
        <span>狼人阵营</span>
        <strong>{{ percent(latest?.wolf) }}</strong>
      </article>
      <article>
        <span>统计基线</span>
        <strong>{{ percent(latestPrediction?.baseline_good ?? latest?.good) }}</strong>
      </article>
      <article>
        <span>大模型独立判断</span>
        <strong>{{ percent(latestPrediction?.llm_good) }}</strong>
      </article>
    </div>

    <div class="probability-track" aria-label="好人与狼人胜率">
      <span class="probability-good" :style="{ width: percent(latest?.good) }" />
      <span class="probability-wolf" :style="{ width: percent(latest?.wolf) }" />
    </div>

    <div v-if="displayPoints.length" class="win-chart">
      <svg viewBox="0 0 720 180" role="img" aria-label="胜率随公开事件变化曲线">
        <line x1="36" y1="90" x2="684" y2="90" class="chart-midline" />
        <line x1="36" y1="30" x2="36" y2="150" class="chart-axis" />
        <line x1="36" y1="150" x2="684" y2="150" class="chart-axis" />
        <polyline :points="baselinePath" class="chart-baseline" />
        <polyline :points="combinedPath" class="chart-combined" />
        <circle
          v-for="(point, index) in displayPoints"
          :key="point.event_seq"
          :cx="displayPoints.length === 1 ? 360 : 36 + (index * 648) / (displayPoints.length - 1)"
          :cy="150 - point.good * 120"
          r="4"
          class="chart-point"
        />
        <text x="4" y="35">100%</text>
        <text x="12" y="95">50%</text>
        <text x="16" y="155">0%</text>
      </svg>
      <div class="chart-legend">
        <span><i class="legend-combined" />综合预测</span>
        <span><i class="legend-baseline" />统计基线</span>
        <span>共 {{ displayPoints.length }} 次公开信息更新</span>
      </div>
    </div>
    <p v-else class="muted">开始首夜并出现公开发言后，胜率曲线会在这里生成。</p>

    <article v-if="latestPrediction" class="model-reasoning">
      <div class="model-reasoning-head">
        <strong>{{ latestPrediction.label }}</strong>
        <span>{{ sourceLabel(latestPrediction.source) }}</span>
      </div>
      <p>{{ latestPrediction.reason }}</p>
      <ul>
        <li v-for="driver in latestPrediction.drivers" :key="driver">{{ driver }}</li>
      </ul>
    </article>

    <ol class="win-event-list">
      <li v-for="point in recentPoints" :key="point.event_seq" class="win-event-row">
        <span class="win-event-label">第{{ point.day }}天 · {{ point.label }}</span>
        <strong>{{ percent(point.good) }}</strong>
        <span :class="point.delta >= 0 ? 'delta-up' : 'delta-down'">
          {{ point.delta >= 0 ? "+" : "" }}{{ (point.delta * 100).toFixed(1) }}
        </span>
      </li>
    </ol>
    <p v-if="errorMessage" class="lab-error">{{ errorMessage }}</p>
  </section>
</template>
