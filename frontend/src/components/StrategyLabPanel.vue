<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";

import type {
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

onMounted(loadLibrary);
</script>

<template>
  <section class="panel strategy-lab" data-testid="strategy-lab">
    <div class="section-heading">
      <h2>策略实验室</h2>
      <span>
        候选 / 已验证 / 已拒绝 · 提交 → 200 局评测 → 审批
      </span>
    </div>

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
        v-for="card in library?.candidates ?? []"
        :key="card.strategy_id"
        class="lab-card"
      >
        <div class="lab-card-head">
          <strong>{{ card.title }}</strong>
          <code>{{ card.strategy_id }}</code>
        </div>
        <p class="muted">
          {{ roleLabel(card.role) }} · {{ actionLabel(card.action) }} ·
          {{ directiveLabel(card.directive) }}
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
