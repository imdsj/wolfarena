export type ConnectionState =
  | "idle"
  | "connecting"
  | "authenticating"
  | "connected"
  | "disconnected"
  | "error";

export type DeadlineKind =
  | "last_words"
  | "speech"
  | "self_destruct"
  | "human_action"
  | "phase_pace";

export interface ViewerIdentity {
  kind: "player" | "spectator";
  player_id: string | null;
  seat: number | null;
  name: string;
  role: string | null;
  is_alive: boolean | null;
  is_host: boolean;
}

export interface PublicPlayer {
  player_id: string;
  seat: number;
  name: string;
  is_human: boolean;
  is_alive: boolean;
  archetype: string | null;
}

export interface GameEvent {
  event_seq: number;
  event_type: string;
  day: number;
  phase: string;
  actor_id: string | null;
  target_id: string | null;
  visibility: string;
  data: Record<string, unknown>;
}

export interface AvailableAction {
  action: string;
  label: string;
  target_ids: string[];
  choices: string[];
  requires_content: boolean;
  requires_target: boolean;
  allow_no_target: boolean;
}

export interface DecisionTraceView {
  day: number;
  phase: string;
  action: string;
  target_id: string | null;
  choice: string | null;
  persona: string;
  strategy_id: string;
  rationale: string | null;
  tool_calls: Array<Record<string, unknown>>;
  evidence_event_ids: number[];
  tactic_ids: string[];
  content: string | null;
}

export interface AgentInsight {
  player_id: string;
  seat: number;
  name: string;
  archetype: string | null;
  current_plan: string | null;
  decision_traces: DecisionTraceView[];
}

export interface WinRatePoint {
  event_seq: number;
  day: number;
  phase: string;
  event_type: string;
  label: string;
  good: number;
  wolf: number;
  delta: number;
  drivers: string[];
  actor_seat: number | null;
  target_seat: number | null;
}

export interface WinRatePrediction extends WinRatePoint {
  baseline_good: number;
  llm_good: number | null;
  source: "deepseek_hybrid" | "statistical_fallback" | "result_confirmed";
  model: string | null;
  reason: string;
  transcript_sha256: string;
  created_at: string;
}

export interface ActionSubmission {
  action: string;
  target_id: string | null;
  content: string | null;
  choice: string | null;
}

export interface RoomSnapshot {
  room_id: string;
  phase: string;
  day: number;
  server_time: number;
  deadline_at: number | null;
  deadline_kind: DeadlineKind | null;
  remaining_ms: number | null;
  witch_kill_target_visible: boolean;
  witch_kill_target_id: string | null;
  human_count: number;
  max_humans: number;
  viewer: ViewerIdentity;
  players: PublicPlayer[];
  visible_events: GameEvent[];
  available_actions: AvailableAction[];
  announcements: string[];
  last_night_summary: string | null;
  awaiting_continue: boolean;
  agent_insights: AgentInsight[];
  win_rate_timeline: WinRatePoint[];
  win_rate_predictions: WinRatePrediction[];
}

export interface RoomSessionResponse {
  room_id: string;
  player_token: string;
  spectator_password?: string;
  room: RoomSnapshot;
}

export interface AiActionResponse {
  decision: {
    candidate: {
      action: string;
      target_id: string | null;
      content: string | null;
      confidence: number;
      reason: string;
    };
    source: "deepseek" | "repair" | "fallback";
    attempts: number;
    fallback_reason: string | null;
  };
  executed: boolean;
  phase: string;
  event_seq: number;
}

export interface StrategyCardSummary {
  strategy_id: string;
  title: string;
  role: string;
  phase: string;
  action: string;
  trigger: string;
  recommendation: string;
  rationale: string;
  risk: string;
  evidence_level: string;
  source: string;
  status: string;
  directive: string | null;
  created_by: string;
  created_at: string;
  samples: number;
  win_rate: number | null;
  evaluation: Record<string, unknown> | null;
  tags: string[];
}

export interface LearningReceipt {
  seed: number;
  generated_at: string;
  policy: string;
  validated_tactics_in_play: string[];
  winner: "good" | "wolf";
  days: number;
  action_steps: number;
  replay_sha256: string;
  generation_source: "deepseek" | "rule_fallback";
  strategy_id: string;
  title: string;
}

export interface LearningResult {
  receipt: LearningReceipt;
  card: StrategyCardSummary;
  evidence_path: string;
}

export interface StrategyLibraryView {
  counts: {
    seed: number;
    candidate: number;
    validated: number;
    rejected: number;
  };
  candidates: StrategyCardSummary[];
  validated: StrategyCardSummary[];
  rejected: StrategyCardSummary[];
}

export interface StrategyEvaluation {
  candidate_id: string;
  decision: string;
  delta_good_win_rate: number;
  mcnemar_exact_p: number;
  sample_size: number;
  baseline_good_win_rate: number;
  candidate_good_win_rate: number;
  confidence_interval_95: number[];
  directive: string | null;
}

export interface ScreenshotFinding {
  kind: string;
  speaker_seat: number | null;
  detail: string;
}

export interface ScreenshotReviewResult {
  day: number;
  transcript: string[];
  findings: ScreenshotFinding[];
  claims: Record<string, string[]>;
  top_accused: Array<{ seat: number; count: number }>;
  reports: Record<string, string>;
}
