import { fetchEventSource } from "@microsoft/fetch-event-source";

import type {
  AuditLog,
  CustomerRecord,
  HealthStatus,
  OrderRecord,
  PolicyRecord,
  RefundRecord,
  RunResponse,
  ShipmentRecord,
  StreamEvent,
  StreamEventMap,
  TicketRecord,
} from "../types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";
const API_KEY = import.meta.env.VITE_API_KEY;

function buildHeaders(): Record<string, string> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (API_KEY) {
    headers["X-API-Key"] = API_KEY;
  }
  return headers;
}

async function parseJsonResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return (await response.json()) as T;
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: buildHeaders(),
  });
  return parseJsonResponse<T>(response);
}

async function postJson<T>(path: string, payload: Record<string, unknown>): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: buildHeaders(),
    body: JSON.stringify(payload),
  });
  return parseJsonResponse<T>(response);
}

export async function streamRun(
  payload: {
    message: string;
    session_id?: string | null;
    actor_id?: string | null;
    actor_metadata?: Record<string, unknown>;
  },
  onEvent: (event: StreamEvent) => void,
): Promise<void> {
  await fetchEventSource(`${API_BASE_URL}/api/after-sales/runs/stream`, {
    method: "POST",
    headers: buildHeaders(),
    body: JSON.stringify(payload),
    openWhenHidden: true,
    async onopen(response) {
      if (response.ok) {
        return;
      }
      throw new Error(await response.text());
    },
    onerror(error) {
      throw error;
    },
    onmessage(message) {
      if (!message.event || !message.data) {
        return;
      }
      const eventName = message.event as keyof StreamEventMap;
      const payload = JSON.parse(message.data) as StreamEventMap[typeof eventName];
      onEvent({
        type: eventName,
        payload,
      } as StreamEvent);
    },
  });
}

export async function submitApprovalDecision(payload: {
  run_id: string;
  action_id: string;
  decision: "approved" | "rejected";
  actor_id?: string | null;
  actor_metadata?: Record<string, unknown>;
}): Promise<RunResponse> {
  return postJson<RunResponse>("/api/after-sales/actions", payload);
}

export async function fetchOrder(orderId: string): Promise<OrderRecord> {
  return getJson<OrderRecord>(`/api/after-sales/orders/${encodeURIComponent(orderId)}`);
}

export async function fetchShipment(orderId: string): Promise<ShipmentRecord> {
  return getJson<ShipmentRecord>(
    `/api/after-sales/orders/${encodeURIComponent(orderId)}/shipment`,
  );
}

export async function fetchCustomer(customerId: string): Promise<CustomerRecord> {
  return getJson<CustomerRecord>(
    `/api/after-sales/customers/${encodeURIComponent(customerId)}`,
  );
}

export async function fetchPolicies(query: string): Promise<PolicyRecord[]> {
  return getJson<PolicyRecord[]>(
    `/api/after-sales/policies/search?q=${encodeURIComponent(query)}`,
  );
}

export async function fetchAuditLogs(runId: string): Promise<AuditLog[]> {
  return getJson<AuditLog[]>(
    `/api/after-sales/audit-logs?run_id=${encodeURIComponent(runId)}`,
  );
}

export async function fetchHealth(): Promise<HealthStatus> {
  return getJson<HealthStatus>("/health");
}

export async function createTicket(payload: {
  order_id: string;
  issue_type: "damaged" | "return" | "exchange" | "other";
  summary: string;
  priority?: "low" | "normal" | "high";
}): Promise<TicketRecord> {
  return postJson<TicketRecord>("/api/after-sales/tickets", payload);
}

export async function createRefundRequest(payload: {
  order_id: string;
  amount: number;
  reason: string;
  requires_approval?: boolean;
}): Promise<RefundRecord> {
  return postJson<RefundRecord>("/api/after-sales/refund-requests", payload);
}
