export type RunStatus = "completed" | "awaiting_action" | "failed";

export interface PendingAction {
  action_id: string;
  action_name: string;
  action_payload: Record<string, unknown>;
  reason: string;
  risk_level: string;
  display_payload: Record<string, unknown>;
}

export interface RunError {
  code: string;
  message: string;
}

export interface RunResponse {
  run_id: string;
  session_id: string;
  status: RunStatus | string;
  output?: string | null;
  pending_action?: PendingAction | null;
  error?: RunError | null;
}

export type StreamEventName =
  | "run.started"
  | "output.delta"
  | "action.started"
  | "action.completed"
  | "action.required"
  | "run.completed"
  | "run.failed";

export interface StreamEventMap {
  "run.started": {
    run_id: string;
    session_id: string;
  };
  "output.delta": {
    run_id: string;
    delta: string;
  };
  "action.started": {
    run_id: string;
    action_id: string;
    action_name: string;
    action_payload: Record<string, unknown>;
  };
  "action.completed": {
    run_id: string;
    action_id: string;
    action_name: string;
    action_payload: Record<string, unknown>;
    success: boolean;
    latency_ms: number;
    result?: Record<string, unknown> | Record<string, unknown>[] | null;
    error?: Record<string, unknown> | null;
  };
  "action.required": {
    run_id: string;
    pending_action: PendingAction;
  };
  "run.completed": RunResponse;
  "run.failed": {
    run_id: string;
    error: RunError;
  };
}

export type StreamEvent = {
  [TName in StreamEventName]: {
    type: TName;
    payload: StreamEventMap[TName];
  };
}[StreamEventName];

export interface OrderRecord {
  order_id: string;
  customer_id: string;
  status: string;
  total_amount: string;
  currency: string;
  item_summary: string;
  created_at: string;
}

export interface ShipmentRecord {
  shipment_id: string;
  order_id: string;
  carrier: string;
  tracking_no: string;
  status: string;
  latest_location?: string | null;
  estimated_delivery_at?: string | null;
  events_json: Array<Record<string, unknown>>;
  updated_at: string;
}

export interface CustomerRecord {
  customer_id: string;
  name: string;
  email: string;
  phone: string;
  created_at: string;
}

export interface TicketRecord {
  ticket_id: string;
  order_id: string;
  customer_id: string;
  issue_type: string;
  summary: string;
  priority: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface RefundRecord {
  refund_request_id: string;
  order_id: string;
  amount: string;
  reason: string;
  status: string;
  requires_approval: boolean;
  created_at: string;
  updated_at: string;
}

export interface PolicyRecord {
  article_id: string;
  title: string;
  category: string;
  keywords: string[];
  content: string;
  created_at: string;
}

export interface AuditLog {
  id: number;
  conversation_id?: string | null;
  event_type: string;
  payload_json: Record<string, unknown>;
  created_at: string;
}

export interface HealthStatus {
  status: string;
  runtime_store: {
    ok: boolean;
    backend: string;
    detail?: string | null;
  };
  business_database: {
    ok: boolean;
    schema_ready: boolean;
    detail?: string | null;
  };
  llm: {
    ok: boolean;
    provider: string;
    model: string;
    detail?: string | null;
  };
}
