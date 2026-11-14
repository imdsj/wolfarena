<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";

import type {
  LearningReceipt,
  LearningResult,
  StrategyCardSummary,
  StrategyEvaluation,
  StrategyLibraryView,
} from "../types";

const library = ref<StrategyLibraryView | null>(null);
const loading = ref(false);
const evaluating = ref(false);
const approving = ref(false);
const errorMessage = ref("");
const notice = ref("");
const lastEvaluation = ref<StrategyEvaluation | null>(null);
const showForm = ref(false);
const learning = ref(false);
const learningSeed = ref(20261114);
const learningResult = ref<LearningResult | null>(null);
const receipts = ref<LearningReceipt[]>([]);

const reviewerName = ref("");
const reviewerToken = ref("");
const rejectReason = ref("");

function updateReviewerName(event: Event): void {
  reviewerName.value = (event.target as HTMLInputElement).value;
}

function updateReviewerToken(event: Event): void {
  reviewerToken.value = (event.target as HTMLInputElement).value;
}

function updateRejectReason(event: Event): void {
  rejectReason.value = (event.target as HTMLInputElement).value;
}

const form = reactive({
  title: "",
  role: "villager",
  action: "vote",
  phase: "ANY",
  directive: "",
  trigger: "",
  recommendation: "",
  rationale: "",
  risk: "",
  created_by: "",
});

const roleLabels: Record<string, string> = {
  werewolf: "狼人",
  villager: "村民",
  seer: "预言家",
  witch: "女巫",
  hunter: "猎人",
};

const actionLabels: Record<string, string> = {
  vote: "投票",
  wolf_kill: "狼刀",
  seer_check: "查验",
  witch_action: "女巫行动",
  night_hunter_shot: "夜间开枪",
  day_hunter_shot: "白天开枪",
  speech: "公开发言",
  wolf_speech: "狼队讨论",
  last_words: "遗言",
};

const directiveLabels: Record<string, string> = {
  vote_most_accused: "跟最高嫌疑投票",
  vote_reported_wolf: "投被报查杀的狼",
  vote_silent: "投沉默玩家",
  witch_poison_most_accused: "毒最被怀疑者",
  witch_save_only_god: "只救自报神职",
  hunter_shoot_most_accused: "开枪打最被怀疑者",
  hunter_hold: "猎人按兵不动",
  seer_check_counterclaim: "查验对跳预言家",
  wolf_kill_accuser: "刀指控者",
};

const decisionLabels: Record<string, string> = {
  auto_promote: "自动晋级",
  reject: "自动驳回",
  human_review: "待人工审批",
};

const recentCandidates = computed(() =>
  [...(library.value?.candidates ?? [])]
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
    .slice(0, 10),
);

const aiValidatedCount = computed(
  () => library.value?.validated.filter((card) => card.created_by === "ai").length ?? 0,
);

function roleLabel(role: string): string {
  return roleLabels[role] ?? role;
}

function actionLabel(action: string): string {
  return actionLabels[action] ?? action;
}

function directiveLabel(directive: string | null): string {
  if (!directive) {
    return "自然语言（仅检索）";
  }
  return directiveLabels[directive] ?? directive;
}

async function requestJson<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(path, init);
  const payload = await response.json();
  if (!response.ok) {
    const detail = payload?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : detail?.message ?? `请求失败（${response.status}）`;
    throw new Error(message);
  }
  return payload as T;
}

async function loadLibrary(): Promise<void> {
  loading.value = true;
  errorMessage.value = "";
  try {
    library.value = await requestJson<StrategyLibraryView>(
      "/api/strategy/library",
    );
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "加载失败";
  } finally {
    loading.value = false;
  }
}

async function loadGrowth(): Promise<void> {
  try {
    const result = await requestJson<{ receipts: LearningReceipt[] }>(
      "/api/strategy/growth",
    );
    receipts.value = result.receipts;
  } catch {
    receipts.value = [];
  }
}

async function runLearning(): Promise<void> {
  learning.value = true;
  errorMessage.value = "";
  notice.value = "";
  learningResult.value = null;
  try {
    const result = await requestJson<LearningResult>("/api/strategy/learn", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ seed: learningSeed.value }),
    });
    learningResult.value = result;
    notice.value = `真实自对弈 seed=${result.receipt.seed} 已完成，AI 复盘候选已入库。`;
    learningSeed.value += 1;
    await Promise.all([loadLibrary(), loadGrowth()]);
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "AI 学习失败";
  } finally {
    learning.value = false;
  }
}

function generationLabel(card: StrategyCardSummary): string {
  if (card.tags.includes("generation:deepseek")) return "DeepSeek 复盘生成";
  if (card.tags.includes("generation:rule_fallback")) return "规则复盘兜底";
  return card.created_by === "ai" ? "AI 历史复盘" : "人工提交";
}

function evaluationText(card: StrategyCardSummary): string {
  const evaluation = card.evaluation;
  if (!evaluation) return "尚未评测";
  const sample = Number(evaluation.sample_size ?? 0);
  const delta = evaluation.delta_good_win_rate;
  const reviewer = String(evaluation.reviewer ?? "未记录");
  const skipped = evaluation.baseline_run_id === "skipped";
  if (skipped) return `人工直接通过 · ${reviewer} · 未评测`;
  return `${sample} 局 · Δ ${typeof delta === "number" ? delta : "未记录"} · ${reviewer}`;
}

function reviewerHeaders(): Record<string, string> {
  return {
    "Content-Type": "application/json",
    "X-Reviewer-Token": reviewerToken.value.trim(),
  };
}

function requireReviewer(): boolean {
  if (!reviewerName.value.trim() || !reviewerToken.value.trim()) {
    errorMessage.value = "请先填写审核人姓名和审核凭证";
    return false;
  }
  return true;
}

async function submitCandidate(): Promise<void> {
  errorMessage.value = "";
  notice.value = "";
  try {
    await requestJson("/api/strategy/candidates", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...form,
        directive: form.directive || null,
      }),
    });
    notice.value = "战术已提交为候选，等待评测。";
    showForm.value = false;
    await loadLibrary();
  } catch (error) {
    errorMessage.value =
      error instanceof Error ? error.message : "提交失败";
  }
}

async function evaluateCandidate(candidateId: string): Promise<void> {
  errorMessage.value = "";
  notice.value = "";
  lastEvaluation.value = null;
  evaluating.value = true;
  try {
    const result = await requestJson<StrategyEvaluation>(
      `/api/strategy/candidates/${encodeURIComponent(candidateId)}/evaluate`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ seed_start: 7000, games: 200 }),
      },
    );
    lastEvaluation.value = result;
    notice.value = `评测完成：${decisionLabels[result.decision] ?? result.decision}`;
    await loadLibrary();
  } catch (error) {
    errorMessage.value =
      error instanceof Error ? error.message : "评测失败";
  } finally {
    evaluating.value = false;
  }
}

async function approveCandidate(
  candidateId: string,
  skipEvaluation = false,
): Promise<void> {
  if (!requireReviewer()) {
    return;
  }
  errorMessage.value = "";
  notice.value = "";
  approving.value = true;
  try {
    await requestJson(
      `/api/strategy/candidates/${encodeURIComponent(candidateId)}/approve`,
      {
        method: "POST",
        headers: reviewerHeaders(),
        body: JSON.stringify({
          reviewer: reviewerName.value.trim(),
          skip_evaluation: skipEvaluation,
        }),
      },
    );
    notice.value = skipEvaluation
      ? "已直接通过（跳过评测），进入正式检索与执行。"
      : "已批准并通过人工审核，进入正式检索与执行。";
    await loadLibrary();
  } catch (error) {
    errorMessage.value =
      error instanceof Error ? error.message : "批准失败";
  } finally {
    approving.value = false;
  }
}

async function rejectCandidate(candidateId: string): Promise<void> {
  if (!requireReviewer()) {
    return;
  }
  if (!rejectReason.value.trim()) {
    errorMessage.value = "请填写驳回理由";
    return;
  }
  errorMessage.value = "";
  notice.value = "";
  try {
    await requestJson(
      `/api/strategy/candidates/${encodeURIComponent(candidateId)}/reject`,
      {
        method: "POST",
        headers: reviewerHeaders(),
        body: JSON.stringify({ reason: rejectReason.value.trim() }),
      },
    );
    notice.value = "已驳回。";
    rejectReason.value = "";
    await loadLibrary();
  } catch (error) {
    errorMessage.value =
      error instanceof Error ? error.message : "驳回失败";
  }
}

async function rollbackStrategy(strategyId: string): Promise<void> {
  if (!requireReviewer()) {
    return;
  }
  errorMessage.value = "";
  notice.value = "";
  try {
    await requestJson(
      `/api/strategy/validated/${encodeURIComponent(strategyId)}/rollback`,
      {
        method: "POST",
        headers: reviewerHeaders(),
        body: JSON.stringify({ reason: "网页人工回滚" }),
      },
    );
    notice.value = "已回滚到候选。";
    await loadLibrary();
  } catch (error) {
    errorMessage.value =
      error instanceof Error ? error.message : "回滚失败";
  }
}

function cardEvaluation(card: StrategyCardSummary): Record<string, unknown> | null {
  return card.evaluation;
}

onMounted(() => {
  void loadLibrary();
  void loadGrowth();
});
</script>

<template>
  <section class="panel strategy-lab" data-testid="strategy-lab">
    <div class="section-heading">
      <h2>策略实验室</h2>
      <span>AI 对局 → 自主复盘 → 200 局验证 → 正式上场</span>
    </div>

    <section class="growth-hero">
      <div class="growth-title">
        <div>
          <div class="eyebrow">AI STRATEGY EVOLUTION</div>
          <h3>策略不是提示词写死的，是从对局里学出来的</h3>
        </div>
        <strong>{{ aiValidatedCount }} 条 AI 策略正在上场</strong>
      </div>
      <ol class="growth-pipeline">
        <li><b>01</b><span>真实自对弈</span><small>固定 seed，全程留日志</small></li>
        <li><b>02</b><span>AI 自主复盘</span><small>生成新的候选战术卡</small></li>
        <li><b>03</b><span>200 局对照</span><small>同 seed + McNemar 检验</small></li>
        <li><b>04</b><span>审批并上场</span><small>检索、决策轨迹可追踪</small></li>
      </ol>
      <div class="learning-controls">
        <label>
          <span>自对弈 seed</span>
          <input v-model.number="learningSeed" type="number" min="0" :disabled="learning" />
        </label>
        <button class="primary-button" type="button" :disabled="learning" @click="runLearning">
          {{ learning ? "AI 正在对局并复盘…" : "跑 1 局，让 AI 生成新策略" }}
        </button>
      </div>
      <p class="muted">
        按钮触发真实后端对局和复盘。生成来源、回放哈希和原始动作日志都会保留；候选未经评测不会自动上场。
      </p>
    </section>

    <article v-if="learningResult" class="learning-result">
      <div class="learning-result-head">
        <div>
          <span class="eyebrow">刚刚学到</span>
          <h3>{{ learningResult.card.title }}</h3>
        </div>
        <span class="source-badge" :class="'source-' + learningResult.receipt.generation_source">
          {{ learningResult.receipt.generation_source === "deepseek" ? "DeepSeek 复盘" : "规则复盘兜底" }}
        </span>
      </div>
      <div class="learning-metrics">
        <span>seed <b>{{ learningResult.receipt.seed }}</b></span>
        <span>胜方 <b>{{ learningResult.receipt.winner === "good" ? "好人" : "狼人" }}</b></span>
        <span>天数 <b>{{ learningResult.receipt.days }}</b></span>
        <span>动作 <b>{{ learningResult.receipt.action_steps }}</b></span>
      </div>
      <p><b>触发：</b>{{ learningResult.card.trigger }}</p>
      <p><b>建议：</b>{{ learningResult.card.recommendation }}</p>
      <p><b>可执行指令：</b>{{ directiveLabel(learningResult.card.directive) }}</p>
      <code>replay {{ learningResult.receipt.replay_sha256.slice(0, 16) }}… · {{ learningResult.evidence_path }}</code>
    </article>

    <section v-if="receipts.length" class="growth-history">
      <div class="section-heading">
        <h3>AI 成长记录</h3>
        <span>{{ receipts.length }} 次有原始证据的学习</span>
      </div>
      <ol>
        <li v-for="receipt in [...receipts].reverse().slice(0, 8)" :key="receipt.strategy_id">
          <span class="growth-dot" />
          <div>
            <strong>{{ receipt.title }}</strong>
            <p>
              seed {{ receipt.seed }} · {{ receipt.action_steps }} 个真实动作 ·
              {{ receipt.generation_source === "deepseek" ? "DeepSeek 生成" : "规则兜底" }}
            </p>
          </div>
          <code>{{ receipt.replay_sha256.slice(0, 8) }}</code>
        </li>
      </ol>
    </section>

    <div v-if="library" class="lab-counts">
      <span>种子 {{ library.counts.seed }}</span>
      <span>候选 {{ library.counts.candidate }}</span>
      <span>已验证 {{ library.counts.validated }}</span>
      <span>已拒绝 {{ library.counts.rejected }}</span>
    </div>

    <p v-if="errorMessage" class="lab-error">{{ errorMessage }}</p>
    <p v-if="notice" class="lab-notice">{{ notice }}</p>

    <div class="lab-actions">
      <button
        class="primary-button"
        type="button"
        :disabled="loading"
        @click="showForm = !showForm"
      >
        {{ showForm ? "收起表单" : "提交我的战术" }}
      </button>
      <button class="text-button" type="button" :disabled="loading" @click="loadLibrary">
        刷新
      </button>
    </div>

    <form v-if="showForm" class="lab-form" @submit.prevent="submitCandidate">
      <label class="field">
        <span>标题</span>
        <input v-model="form.title" maxlength="120" required />
      </label>
      <div class="lab-form-row">
        <label class="field">
          <span>角色</span>
          <select v-model="form.role">
            <option v-for="(label, value) in roleLabels" :key="value" :value="value">
              {{ label }}
            </option>
          </select>
        </label>
        <label class="field">
          <span>动作</span>
          <select v-model="form.action">
            <option v-for="(label, value) in actionLabels" :key="value" :value="value">
              {{ label }}
            </option>
          </select>
        </label>
        <label class="field">
          <span>可执行指令</span>
          <select v-model="form.directive">
            <option value="">自然语言（仅检索）</option>
            <option
              v-for="(label, value) in directiveLabels"
              :key="value"
              :value="value"
            >
              {{ label }}
            </option>
          </select>
        </label>
      </div>
      <label class="field">
        <span>触发条件</span>
        <textarea v-model="form.trigger" maxlength="600" required />
      </label>
      <label class="field">
        <span>行动建议</span>
        <textarea v-model="form.recommendation" maxlength="600" required />
      </label>
      <label class="field">
        <span>理由</span>
        <textarea v-model="form.rationale" maxlength="1000" required />
      </label>
      <label class="field">
        <span>风险</span>
        <textarea v-model="form.risk" maxlength="600" required />
      </label>
      <label class="field">
        <span>提交人</span>
        <input v-model="form.created_by" maxlength="64" required />
      </label>
      <button class="primary-button" type="submit">提交为候选</button>
    </form>

    <div v-if="lastEvaluation" class="lab-evaluation">
      <div class="section-heading">
        <h3>最近评测</h3>
        <strong>{{ decisionLabels[lastEvaluation.decision] ?? lastEvaluation.decision }}</strong>
      </div>
      <p class="muted">
        {{ lastEvaluation.candidate_id }} · 好人胜率差
        {{ lastEvaluation.delta_good_win_rate >= 0 ? "+" : "" }}{{ lastEvaluation.delta_good_win_rate }}
        · McNemar p={{ lastEvaluation.mcnemar_exact_p }}
        · 样本 {{ lastEvaluation.sample_size }} 局
      </p>
    </div>

    <section class="lab-section">
      <div class="section-heading">
        <h3>候选</h3>
        <span>{{ library?.candidates.length ?? 0 }}</span>
      </div>
      <article
        v-for="card in recentCandidates"
        :key="card.strategy_id"
        class="lab-card"
      >
        <div class="lab-card-head">
          <strong>{{ card.title }}</strong>
          <code>{{ card.strategy_id }}</code>
        </div>
        <p class="muted">
          {{ roleLabel(card.role) }} · {{ actionLabel(card.action) }} ·
          {{ directiveLabel(card.directive) }} · {{ generationLabel(card) }}
        </p>
        <p class="lab-card-body">
          触发：{{ card.trigger }}<br />
          建议：{{ card.recommendation }}<br />
          风险：{{ card.risk }}
        </p>
        <div v-if="cardEvaluation(card)" class="lab-card-eval">
          <code>{{ JSON.stringify(cardEvaluation(card)) }}</code>
        </div>
        <div class="lab-card-actions">
          <button
            class="secondary-button"
            type="button"
            :disabled="evaluating"
            @click="evaluateCandidate(card.strategy_id)"
          >
            {{ evaluating ? "评测中…" : "开始评测" }}
          </button>
          <button
            class="secondary-button"
            type="button"
            :disabled="approving"
            @click="approveCandidate(card.strategy_id, false)"
          >
            {{ approving ? "审批中…" : "通过（评测）" }}
          </button>
          <button
            class="text-button"
            type="button"
            :disabled="approving"
            @click="approveCandidate(card.strategy_id, true)"
          >
            直接通过
          </button>
          <button
            class="text-button"
            type="button"
            @click="rejectCandidate(card.strategy_id)"
          >
            驳回
          </button>
        </div>
      </article>
      <p v-if="!library?.candidates.length" class="muted">没有候选。</p>
    </section>

    <section class="lab-section">
      <div class="section-heading">
        <h3>已验证</h3>
        <span>{{ library?.validated.length ?? 0 }}</span>
      </div>
      <article
        v-for="card in library?.validated ?? []"
        :key="card.strategy_id"
        class="lab-card lab-card-validated"
      >
        <div class="lab-card-head">
          <strong>{{ card.title }}</strong>
          <code>{{ card.strategy_id }}</code>
        </div>
        <p class="muted">
          {{ roleLabel(card.role) }} · {{ actionLabel(card.action) }} ·
          {{ directiveLabel(card.directive) }} · 参与正式检索与执行
        </p>
        <p class="lab-card-evidence">
          {{ generationLabel(card) }} · {{ evaluationText(card) }}
        </p>
        <div class="lab-card-actions">
          <button
            class="text-button"
            type="button"
            @click="rollbackStrategy(card.strategy_id)"
          >
            回滚到候选
          </button>
        </div>
      </article>
      <p v-if="!library?.validated.length" class="muted">没有已验证策略。</p>
    </section>

    <section class="lab-section">
      <div class="section-heading">
        <h3>已拒绝</h3>
        <span>{{ library?.rejected.length ?? 0 }}</span>
      </div>
      <article
        v-for="card in library?.rejected ?? []"
        :key="card.strategy_id"
        class="lab-card lab-card-rejected"
      >
        <div class="lab-card-head">
          <strong>{{ card.title }}</strong>
          <code>{{ card.strategy_id }}</code>
        </div>
        <p class="muted">已拒绝 · {{ card.source }}</p>
      </article>
      <p v-if="!library?.rejected.length" class="muted">没有已拒绝策略。</p>
    </section>

    <section class="lab-section">
      <div class="section-heading">
        <h3>人工审批</h3>
        <span>需要服务端配置的审核凭证</span>
      </div>
      <div class="lab-form-row">
        <label class="field">
          <span>审核人姓名</span>
          <input
            :value="reviewerName"
            maxlength="64"
            @input="updateReviewerName"
          />
        </label>
        <label class="field">
          <span>审核凭证（X-Reviewer-Token）</span>
          <input
            :value="reviewerToken"
            type="password"
            maxlength="128"
            @input="updateReviewerToken"
          />
        </label>
      </div>
      <label class="field">
        <span>驳回理由</span>
        <input
          :value="rejectReason"
          maxlength="400"
          @input="updateRejectReason"
        />
      </label>
    </section>

    <div
      v-if="errorMessage || notice"
      class="lab-toast"
      :class="{ 'lab-toast-error': Boolean(errorMessage) }"
    >
      {{ errorMessage || notice }}
    </div>
  </section>
</template>
