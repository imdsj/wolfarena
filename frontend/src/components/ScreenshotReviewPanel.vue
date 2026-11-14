<script setup lang="ts">
import { ref } from "vue";

import type { ScreenshotReviewResult } from "../types";

const imagePreview = ref("");
const transcript = ref("");
const day = ref(1);
const result = ref<ScreenshotReviewResult | null>(null);
const busy = ref(false);
const errorMessage = ref("");

const kindLabels: Record<string, string> = {
  role_flip: "自报多个神职",
  impossible_seer_checks: "一晚报多个查验",
  report_vs_vote: "金水反投",
  two_nights_day_one: "第一天提到两晚",
};

const claimLabels: Record<string, string> = {
  seer: "预言家",
  witch: "女巫",
  hunter: "猎人",
  villager: "村民",
};

function onFileChange(event: Event): void {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) {
    return;
  }
  const reader = new FileReader();
  reader.onload = () => {
    imagePreview.value = String(reader.result ?? "");
  };
  reader.readAsDataURL(file);
}

async function submitReview(): Promise<void> {
  busy.value = true;
  errorMessage.value = "";
  result.value = null;
  const lines = transcript.value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  try {
    const response = await fetch("/api/review/screenshot", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ day: day.value, lines }),
    });
    const payload = await response.json();
    if (!response.ok) {
      const detail = payload?.detail;
      throw new Error(
        typeof detail === "string"
          ? detail
          : detail?.message ?? `请求失败（${response.status}）`,
      );
    }
    result.value = payload as ScreenshotReviewResult;
  } catch (error) {
    errorMessage.value =
      error instanceof Error ? error.message : "复盘失败";
  } finally {
    busy.value = false;
  }
}

function kindLabel(kind: string): string {
  return kindLabels[kind] ?? kind;
}

function claimLabel(value: string): string {
  return claimLabels[value] ?? value;
}
</script>

<template>
  <section class="panel review-panel" data-testid="screenshot-review">
    <div class="section-heading">
      <h2>截图复盘</h2>
      <span>上传对局截图 → 确认识别文本 → AI 逻辑复盘</span>
    </div>

    <p class="muted">
      把狼人杀的发言截图传上来，再逐行确认截图里的发言，AI 会按硬规则做逻辑复盘。
      自动识别当前采用人机协同：你确认文字，分析交给系统。
    </p>

    <div class="review-upload">
      <label class="field">
        <span>对局截图（可选）</span>
        <input type="file" accept="image/*" @change="onFileChange" />
      </label>
      <img
        v-if="imagePreview"
        :src="imagePreview"
        alt="对局截图预览"
        class="review-image"
      />
    </div>

    <div class="review-forms">
      <label class="field">
        <span>第几天</span>
        <input v-model.number="day" type="number" min="1" max="20" />
      </label>
      <label class="field">
        <span>发言文本（每行一条，格式“6号：我是预言家…”）</span>
        <textarea
          v-model="transcript"
          rows="8"
          placeholder="6号：我是预言家，昨晚验4号金水、2号查杀。&#10;3号：今天票6号。"
        />
      </label>
      <button
        class="primary-button"
        type="button"
        :disabled="busy || !transcript.trim()"
        @click="submitReview"
      >
        {{ busy ? "复盘生成中…" : "生成逻辑复盘" }}
      </button>
    </div>

    <p v-if="errorMessage" class="lab-error">{{ errorMessage }}</p>

    <section v-if="result" class="review-result">
      <div class="section-heading">
        <h3>复盘结果</h3>
        <span>发现 {{ result.findings.length }} 处矛盾</span>
      </div>

      <div v-if="result.findings.length" class="review-findings">
        <div
          v-for="(finding, index) in result.findings"
          :key="index"
          class="review-finding"
        >
          <span class="finding-kind">{{ kindLabel(finding.kind) }}</span>
          <span>{{ finding.detail }}</span>
        </div>
      </div>
      <p v-else class="muted">没有发现硬规则矛盾。</p>

      <div v-if="Object.keys(result.claims).length" class="review-meta">
        <span>身份声明：</span>
        <template v-for="(values, seat) in result.claims" :key="seat">
          <span class="chip">{{ seat }}号 {{ values.map(claimLabel).join("、") }}</span>
        </template>
      </div>

      <div v-if="result.top_accused.length" class="review-meta">
        <span>票型嫌疑：</span>
        <span
          v-for="entry in result.top_accused"
          :key="entry.seat"
          class="chip"
        >
          {{ entry.seat }}号 × {{ entry.count }}
        </span>
      </div>

      <div v-if="Object.keys(result.reports).length" class="review-meta">
        <span>查验报告：</span>
        <template v-for="(value, seat) in result.reports" :key="seat">
          <span class="chip">
            {{ seat }}号 {{ value === "wolf" ? "查杀" : "金水" }}
          </span>
        </template>
      </div>
    </section>
  </section>
</template>
