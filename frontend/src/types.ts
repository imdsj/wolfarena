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
}

export interface AgentInsight {
  player_id: string;
  seat: number;
  name: string;
  archetype: string | null;
  current_plan: string | null;
  decision_traces: DecisionTraceView[];
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
