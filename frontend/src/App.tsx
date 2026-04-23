import type { ReactNode } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertOutlined,
  ArrowRightOutlined,
  BarChartOutlined,
  BellOutlined,
  BookOutlined,
  CommentOutlined,
  FileTextOutlined,
  HomeFilled,
  RobotOutlined,
  SearchOutlined,
} from "@ant-design/icons";
import {
  Avatar,
  Badge,
  Button,
  Card,
  Descriptions,
  Drawer,
  Empty,
  Input,
  List,
  Space,
  Spin,
  Tag,
  Timeline,
  Typography,
  message,
} from "antd";

import {
  fetchAuditLogs,
  fetchCustomer,
  fetchHealth,
  fetchOrder,
  fetchPolicies,
  fetchShipment,
  streamRun,
  submitApprovalDecision,
} from "./api/chat";
import type {
  AuditLog,
  CustomerRecord,
  HealthStatus,
  OrderRecord,
  PendingAction,
  PolicyRecord,
  RefundRecord,
  ShipmentRecord,
  StreamEvent,
  TicketRecord,
} from "./types";

const { Paragraph, Text, Title } = Typography;

type BubbleRole = "user" | "assistant" | "system";

interface ChatBubble {
  id: string;
  role: BubbleRole;
  text: string;
}

interface ApprovalQueueItem {
  id: string;
  runId: string;
  pendingAction: PendingAction;
  status: "pending" | "approved" | "rejected";
}

interface ActionPulse {
  actionId: string;
  actionName: string;
  status: "running" | "success" | "failed";
  actionPayload: Record<string, unknown>;
  result?: unknown;
  error?: Record<string, unknown> | null;
  latencyMs?: number;
}

interface DossierState {
  order: OrderRecord | null;
  shipment: ShipmentRecord | null;
  customer: CustomerRecord | null;
  ticket: TicketRecord | null;
  refund: RefundRecord | null;
  policies: PolicyRecord[];
}

interface DeskStateCopy {
  color: string;
  label: string;
  note: string;
  tone: "idle" | "running" | "pending" | "success" | "failed";
}

interface QuickAction {
  title: string;
  summary: string;
  prompt: string;
  icon: ReactNode;
}

type ConsoleView = "dashboard" | "tickets" | "conversation";

interface NavigationItem {
  key: ConsoleView;
  label: string;
  icon: ReactNode;
  summary: string;
}

interface TrendPoint {
  label: string;
  primary: number;
  secondary: number;
}

interface DistributionItem {
  label: string;
  value: number;
  color: string;
}

const EMPTY_DOSSIER: DossierState = {
  order: null,
  shipment: null,
  customer: null,
  ticket: null,
  refund: null,
  policies: [],
};

const QUICK_ACTIONS: QuickAction[] = [
  {
    title: "查订单进度",
    summary: "读取订单状态、商品信息和关键时间点。",
    prompt: "帮我查一下订单 ORD123 的状态",
    icon: <SearchOutlined />,
  },
  {
    title: "查物流节点",
    summary: "返回最新位置、承运商和运输状态。",
    prompt: "帮我看下订单 ORD123 现在到哪了",
    icon: <BarChartOutlined />,
  },
  {
    title: "创建售后工单",
    summary: "按破损/退货场景自动生成工单摘要。",
    prompt: "订单 ORD123 商品坏了，帮我登记一个售后工单",
    icon: <FileTextOutlined />,
  },
  {
    title: "发起退款申请",
    summary: "命中高风险规则时自动进入主管审批。",
    prompt: "用户要退款 200 元，订单 ORD123，原因是商品破损",
    icon: <AlertOutlined />,
  },
  {
    title: "查询售后政策",
    summary: "检索退款、破损和换货政策条款。",
    prompt: "帮我查一下破损退款政策",
    icon: <BookOutlined />,
  },
];

const NAVIGATION_ITEMS: NavigationItem[] = [
  {
    key: "dashboard",
    label: "工作台",
    icon: <HomeFilled />,
    summary: "看整体态势和待办分布",
  },
  {
    key: "tickets",
    label: "工单管理",
    icon: <FileTextOutlined />,
    summary: "处理订单、退款、审批和政策",
  },
  {
    key: "conversation",
    label: "智能会话",
    icon: <CommentOutlined />,
    summary: "给智能体下指令并观察执行",
  },
];

const VIEW_COPY: Record<
  ConsoleView,
  {
    kicker: string;
    title: string;
    description: string;
  }
> = {
  dashboard: {
    kicker: "Workbench",
    title: "工作台",
    description: "这里只保留全局概览、待办和流量趋势，用来判断当前案件与班次压力。",
  },
  tickets: {
    kicker: "Ticket Operations",
    title: "工单管理",
    description: "订单、工单、退款、审批与政策统一放在这里，适合业务处理和复核。",
  },
  conversation: {
    kicker: "Agent Console",
    title: "智能会话",
    description: "这里专注坐席与智能体协作，直接下达指令并查看动作执行结果。",
  },
};

const ORDER_SHORTCUTS = ["ORD123", "ORD456"];
const POLICY_SHORTCUTS = ["破损", "退款", "质量问题", "换货"];

function approvalQueueId(runId: string, pendingAction: PendingAction): string {
  return `${runId}:${pendingAction.action_id}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isPolicyList(value: unknown): value is PolicyRecord[] {
  return Array.isArray(value) && value.every((item) => isRecord(item));
}

function asText(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "—";
  }
  return String(value);
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function prettyEventName(eventType: string): string {
  const mapping: Record<string, string> = {
    approval_requested: "已创建审批请求",
    approval_resolved: "审批已处理",
    run_failed: "运行失败",
  };
  return mapping[eventType] ?? eventType;
}

function actionDisplayName(actionName: string): string {
  const mapping: Record<string, string> = {
    get_order_detail: "查订单",
    get_shipment_detail: "查物流",
    create_ticket: "创建工单",
    get_ticket_detail: "查工单",
    submit_refund_request: "退款申请",
    search_after_sales_policy: "查政策",
  };
  return mapping[actionName] ?? actionName;
}

function bubbleLabel(role: BubbleRole): string {
  if (role === "user") {
    return "客服坐席";
  }
  if (role === "assistant") {
    return "工单智能体";
  }
  return "系统 / 审批";
}

function bubbleMark(role: BubbleRole): string {
  if (role === "user") {
    return "客";
  }
  if (role === "assistant") {
    return "AI";
  }
  return "审";
}

function queueStatusLabel(status: ApprovalQueueItem["status"]): string {
  const mapping: Record<ApprovalQueueItem["status"], string> = {
    pending: "待审批",
    approved: "已批准",
    rejected: "已拒绝",
  };
  return mapping[status];
}

function riskColor(riskLevel: string): string {
  if (riskLevel === "high") {
    return "red";
  }
  if (riskLevel === "medium") {
    return "gold";
  }
  return "green";
}

function statusColor(status: string): string {
  if (status === "failed" || status === "rejected") {
    return "red";
  }
  if (status === "awaiting_action" || status === "pending") {
    return "gold";
  }
  if (status === "running") {
    return "blue";
  }
  return "green";
}

function healthColor(ok: boolean): string {
  return ok ? "green" : "red";
}

function renderJsonPreview(value: unknown): string {
  if (value === undefined) {
    return "—";
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function describeDeskState({
  pendingApprovalCount,
  highRiskApprovalCount,
  submitting,
  lastAction,
}: {
  pendingApprovalCount: number;
  highRiskApprovalCount: number;
  submitting: boolean;
  lastAction: ActionPulse | null;
}): DeskStateCopy {
  if (pendingApprovalCount > 0) {
    const highRiskText = highRiskApprovalCount > 0 ? `，其中高风险 ${highRiskApprovalCount} 条` : "";
    return {
      color: "gold",
      label: "等待主管审批",
      note: `高风险动作已暂停，当前有 ${pendingApprovalCount} 条待审批记录${highRiskText}。`,
      tone: "pending",
    };
  }

  if (submitting) {
    return {
      color: "blue",
      label: "智能体处理中",
      note: "智能体正在读取订单、物流、政策和历史动作，准备执行下一步。",
      tone: "running",
    };
  }

  if (lastAction?.status === "running") {
    return {
      color: "blue",
      label: "动作执行中",
      note: `正在执行 ${actionDisplayName(lastAction.actionName)}，等待返回结果。`,
      tone: "running",
    };
  }

  if (lastAction?.status === "failed") {
    return {
      color: "red",
      label: "需要人工复核",
      note: `${actionDisplayName(lastAction.actionName)} 执行失败，请查看回执并决定是否重试。`,
      tone: "failed",
    };
  }

  if (lastAction?.status === "success") {
    return {
      color: "green",
      label: "已完成最近动作",
      note: `${actionDisplayName(lastAction.actionName)} 已执行完成，可以继续处理下一个诉求。`,
      tone: "success",
    };
  }

  return {
    color: "default",
    label: "待接单",
    note: "输入客服指令，开始查单、建工单或发起退款申请。",
    tone: "idle",
  };
}

function buildLinePoints(points: TrendPoint[], key: "primary" | "secondary"): string {
  const width = 520;
  const height = 220;
  const paddingX = 24;
  const paddingY = 20;
  const maxValue = Math.max(
    ...points.flatMap((point) => [point.primary, point.secondary]),
    1,
  );

  return points
    .map((point, index) => {
      const x =
        points.length === 1
          ? width / 2
          : paddingX + (index * (width - paddingX * 2)) / (points.length - 1);
      const y =
        height -
        paddingY -
        ((point[key] || 0) / maxValue) * (height - paddingY * 2);
      return `${x},${y}`;
    })
    .join(" ");
}

function App() {
  const [messageApi, contextHolder] = message.useMessage();
  const [activeView, setActiveView] = useState<ConsoleView>("dashboard");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [inputValue, setInputValue] = useState("帮我看下订单 ORD123 现在到哪了");
  const [orderLookup, setOrderLookup] = useState("ORD123");
  const [policyQuery, setPolicyQuery] = useState("破损");
  const [messages, setMessages] = useState<ChatBubble[]>([]);
  const [, setActiveAssistantId] = useState<string | null>(null);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [dossierLoading, setDossierLoading] = useState(false);
  const [policyLoading, setPolicyLoading] = useState(false);
  const [healthLoading, setHealthLoading] = useState(false);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [auditLogsByRunId, setAuditLogsByRunId] = useState<Record<string, AuditLog[]>>({});
  const [actionsByRunId, setActionsByRunId] = useState<Record<string, ActionPulse>>({});
  const [approvalQueue, setApprovalQueue] = useState<ApprovalQueueItem[]>([]);
  const [selectedApprovalId, setSelectedApprovalId] = useState<string | null>(null);
  const [showDiagnostics, setShowDiagnostics] = useState(false);
  const [dossier, setDossier] = useState<DossierState>(EMPTY_DOSSIER);

  const messageListRef = useRef<HTMLDivElement | null>(null);
  const conversationIdRef = useRef<string | null>(null);
  const activeAssistantIdRef = useRef<string | null>(null);
  const workspaceRef = useRef<HTMLDivElement | null>(null);

  const selectedApproval = useMemo(
    () => approvalQueue.find((item) => item.id === selectedApprovalId) ?? null,
    [approvalQueue, selectedApprovalId],
  );
  const auditLogs = useMemo(
    () => (activeRunId ? auditLogsByRunId[activeRunId] ?? [] : []),
    [activeRunId, auditLogsByRunId],
  );
  const lastAction = useMemo(
    () => (activeRunId ? actionsByRunId[activeRunId] ?? null : null),
    [activeRunId, actionsByRunId],
  );

  const sortedApprovals = useMemo(
    () =>
      [...approvalQueue].sort((left, right) => {
        if (left.status === right.status) {
          return 0;
        }
        if (left.status === "pending") {
          return -1;
        }
        if (right.status === "pending") {
          return 1;
        }
        if (left.status === "approved") {
          return -1;
        }
        return 1;
      }),
    [approvalQueue],
  );

  const pendingApprovalCount = useMemo(
    () => approvalQueue.filter((item) => item.status === "pending").length,
    [approvalQueue],
  );

  const highRiskApprovalCount = useMemo(
    () =>
      approvalQueue.filter(
        (item) => item.status === "pending" && item.pendingAction.risk_level === "high",
      ).length,
    [approvalQueue],
  );

  const deskState = useMemo(
    () =>
      describeDeskState({
        pendingApprovalCount,
        highRiskApprovalCount,
        submitting,
        lastAction,
      }),
    [highRiskApprovalCount, lastAction, pendingApprovalCount, submitting],
  );

  const policyPreview = useMemo(() => dossier.policies.slice(0, 3), [dossier.policies]);

  useEffect(() => {
    messageListRef.current?.scrollTo({
      top: messageListRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages]);

  useEffect(() => {
    void bootstrapDesk();
  }, []);

  function setConversation(nextConversationId: string | null) {
    conversationIdRef.current = nextConversationId;
    setConversationId(nextConversationId);
  }

  function setLiveAssistant(nextAssistantId: string | null) {
    activeAssistantIdRef.current = nextAssistantId;
    setActiveAssistantId(nextAssistantId);
  }

  async function bootstrapDesk() {
    await Promise.allSettled([
      refreshHealthStatus(false),
      loadOrderWorkspace("ORD123", false),
      loadPolicyDeck("破损", false),
    ]);
  }

  async function refreshHealthStatus(showSuccessMessage = true) {
    setHealthLoading(true);
    try {
      const nextHealth = await fetchHealth();
      setHealth(nextHealth);
      if (showSuccessMessage) {
        void messageApi.success("调试区系统状态已刷新。");
      }
    } catch (error) {
      console.error(error);
      void messageApi.error("健康检查读取失败，请确认 FastAPI 服务已启动。");
    } finally {
      setHealthLoading(false);
    }
  }

  async function refreshAuditTimeline(runId: string) {
    try {
      const logs = await fetchAuditLogs(runId);
      setAuditLogsByRunId((current) => ({
        ...current,
        [runId]: logs,
      }));
    } catch (error) {
      console.error(error);
    }
  }

  function updateRunAction(runId: string, action: ActionPulse) {
    setActionsByRunId((current) => ({
      ...current,
      [runId]: action,
    }));
  }

  function resetExecutionState(options?: { clearApprovals?: boolean }) {
    setActiveRunId(null);
    setActionsByRunId({});
    setAuditLogsByRunId({});
    setSelectedApprovalId(null);
    setDossier((current) => ({
      ...current,
      ticket: null,
      refund: null,
    }));
    if (options?.clearApprovals) {
      setApprovalQueue([]);
    }
  }

  async function loadOrderWorkspace(orderId: string, showSuccessMessage = true) {
    const trimmedOrderId = orderId.trim().toUpperCase();
    if (!trimmedOrderId) {
      return;
    }

    if (dossier.order?.order_id && dossier.order.order_id !== trimmedOrderId) {
      setSelectedApprovalId(null);
      setDossier((current) => ({
        ...current,
        ticket: null,
        refund: null,
      }));
    }

    setOrderLookup(trimmedOrderId);
    setDossierLoading(true);

    try {
      const order = await fetchOrder(trimmedOrderId);
      const [shipmentResult, customerResult] = await Promise.allSettled([
        fetchShipment(trimmedOrderId),
        fetchCustomer(order.customer_id),
      ]);

      setDossier((current) => ({
        ...current,
        order,
        shipment: shipmentResult.status === "fulfilled" ? shipmentResult.value : null,
        customer: customerResult.status === "fulfilled" ? customerResult.value : null,
      }));

      if (showSuccessMessage) {
        void messageApi.success(`订单 ${trimmedOrderId} 的客户档案已载入。`);
      }
    } catch (error) {
      console.error(error);
      setDossier((current) => ({
        ...current,
        order: null,
        shipment: null,
        customer: null,
        ticket: null,
        refund: null,
      }));
      void messageApi.error(`订单 ${trimmedOrderId} 不存在，或资源接口暂时不可用。`);
    } finally {
      setDossierLoading(false);
    }
  }

  async function loadPolicyDeck(query: string, showSuccessMessage = true) {
    const trimmedQuery = query.trim();
    if (!trimmedQuery) {
      return;
    }

    setPolicyQuery(trimmedQuery);
    setPolicyLoading(true);

    try {
      const policies = await fetchPolicies(trimmedQuery);
      setDossier((current) => ({
        ...current,
        policies,
      }));
      if (showSuccessMessage) {
        void messageApi.success(`已更新“${trimmedQuery}”相关售后政策。`);
      }
    } catch (error) {
      console.error(error);
      void messageApi.error("政策检索失败，请确认后端资源接口可访问。");
    } finally {
      setPolicyLoading(false);
    }
  }

  function pushBubble(role: BubbleRole, text: string): string {
    const id = `${role}-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
    setMessages((current) => [...current, { id, role, text }]);
    return id;
  }

  function ensureAssistantBubble() {
    if (activeAssistantIdRef.current) {
      return activeAssistantIdRef.current;
    }
    const nextId = `assistant-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
    setMessages((current) => [...current, { id: nextId, role: "assistant", text: "" }]);
    setLiveAssistant(nextId);
    return nextId;
  }

  function appendAssistantDelta(delta: string) {
    const currentAssistantId = ensureAssistantBubble();
    setMessages((current) =>
      current.map((item) =>
        item.id === currentAssistantId ? { ...item, text: `${item.text}${delta}` } : item,
      ),
    );
  }

  function finalizeAssistantBubble(output: string | null | undefined) {
    const currentAssistantId = activeAssistantIdRef.current;
    if (!currentAssistantId) {
      if (output) {
        pushBubble("assistant", output);
      }
      return;
    }

    if (output) {
      setMessages((current) =>
        current.map((item) =>
          item.id === currentAssistantId && item.text.trim().length === 0
            ? { ...item, text: output }
            : item,
        ),
      );
    }
    setLiveAssistant(null);
  }

  function upsertApproval(item: ApprovalQueueItem) {
    setApprovalQueue((current) => {
      const existingIndex = current.findIndex((entry) => entry.id === item.id);
      if (existingIndex === -1) {
        return [item, ...current];
      }
      const next = [...current];
      next[existingIndex] = item;
      return next;
    });
  }

  function updateApprovalStatus(id: string, status: ApprovalQueueItem["status"]) {
    setApprovalQueue((current) =>
      current.map((item) => (item.id === id ? { ...item, status } : item)),
    );
  }

  function resetConversationWorkspace() {
    setConversation(null);
    setLiveAssistant(null);
    setMessages([]);
    resetExecutionState({ clearApprovals: true });
  }

  function applyActionResult(
    actionName: string,
    result: Record<string, unknown> | Record<string, unknown>[] | null | undefined,
  ) {
    if (!result) {
      return;
    }

    if (actionName === "get_order_detail" && isRecord(result)) {
      const order = result as unknown as OrderRecord;
      setDossier((current) => ({
        ...current,
        order,
      }));
      void loadOrderWorkspace(order.order_id, false);
      return;
    }

    if (actionName === "get_shipment_detail" && isRecord(result)) {
      setDossier((current) => ({
        ...current,
        shipment: result as unknown as ShipmentRecord,
      }));
      return;
    }

    if ((actionName === "create_ticket" || actionName === "get_ticket_detail") && isRecord(result)) {
      setDossier((current) => ({
        ...current,
        ticket: result as unknown as TicketRecord,
      }));
      return;
    }

    if (actionName === "submit_refund_request" && isRecord(result)) {
      setDossier((current) => ({
        ...current,
        refund: result as unknown as RefundRecord,
      }));
      return;
    }

    if (actionName === "search_after_sales_policy" && isPolicyList(result)) {
      setDossier((current) => ({
        ...current,
        policies: result,
      }));
    }
  }

  function handleRunEvent(event: StreamEvent) {
    if (event.type === "run.started") {
      setConversation(event.payload.session_id);
      setActiveRunId(event.payload.run_id);
      return;
    }

    if (event.type === "output.delta") {
      setActiveRunId(event.payload.run_id);
      appendAssistantDelta(event.payload.delta);
      return;
    }

    if (event.type === "action.started") {
      setActiveRunId(event.payload.run_id);
      updateRunAction(event.payload.run_id, {
        actionId: event.payload.action_id,
        actionName: event.payload.action_name,
        status: "running",
        actionPayload: event.payload.action_payload,
      });
      return;
    }

    if (event.type === "action.completed") {
      setActiveRunId(event.payload.run_id);
      updateRunAction(event.payload.run_id, {
        actionId: event.payload.action_id,
        actionName: event.payload.action_name,
        status: event.payload.success ? "success" : "failed",
        actionPayload: event.payload.action_payload,
        result: event.payload.result,
        error: event.payload.error,
        latencyMs: event.payload.latency_ms,
      });
      applyActionResult(event.payload.action_name, event.payload.result);
      return;
    }

    if (event.type === "action.required") {
      setActiveRunId(event.payload.run_id);
      const nextApproval: ApprovalQueueItem = {
        id: approvalQueueId(event.payload.run_id, event.payload.pending_action),
        runId: event.payload.run_id,
        pendingAction: event.payload.pending_action,
        status: "pending",
      };
      upsertApproval(nextApproval);
      setSelectedApprovalId(nextApproval.id);
      return;
    }

    if (event.type === "run.completed") {
      setConversation(event.payload.session_id);
      setActiveRunId(event.payload.run_id);
      finalizeAssistantBubble(event.payload.output);
      if (event.payload.pending_action) {
        const nextApproval: ApprovalQueueItem = {
          id: approvalQueueId(event.payload.run_id, event.payload.pending_action),
          runId: event.payload.run_id,
          pendingAction: event.payload.pending_action,
          status: "pending",
        };
        upsertApproval(nextApproval);
      }
      void refreshAuditTimeline(event.payload.run_id);
      return;
    }

    if (event.type === "run.failed") {
      setActiveRunId(event.payload.run_id);
      finalizeAssistantBubble(`运行失败：${event.payload.error.message}`);
      void messageApi.error(event.payload.error.message);
    }
  }

  async function submitPrompt(promptOverride?: string) {
    const nextPrompt = (promptOverride ?? inputValue).trim();
    if (!nextPrompt || submitting) {
      return;
    }

    const nextAssistantId = `assistant-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
    setSubmitting(true);
    setLiveAssistant(nextAssistantId);
    setMessages((current) => [
      ...current,
      { id: `user-${Date.now()}`, role: "user", text: nextPrompt },
      { id: nextAssistantId, role: "assistant", text: "" },
    ]);

    try {
      await streamRun(
        {
          message: nextPrompt,
          session_id: conversationIdRef.current,
          actor_id: "service-agent",
          actor_metadata: {
            surface: "service-desk-workbench",
          },
        },
        handleRunEvent,
      );
      setInputValue("");
    } catch (error) {
      console.error(error);
      setLiveAssistant(null);
      setMessages((current) =>
        current.map((item) =>
          item.id === nextAssistantId
            ? { ...item, text: "指令发送失败，请检查后端服务或 API Key 配置。" }
            : item,
        ),
      );
      void messageApi.error("消息发送失败，请检查后端是否已启动。");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleApprovalDecision(decision: "approved" | "rejected") {
    if (!selectedApproval || submitting) {
      return;
    }

    const approvalId = selectedApproval.id;
    const runId = selectedApproval.runId;
    updateApprovalStatus(approvalId, decision);
    setActiveRunId(runId);
    setSubmitting(true);

    setMessages((current) => [
      ...current,
      {
        id: `system-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
        role: "system",
        text: decision === "approved" ? "主管已批准该动作。" : "主管已拒绝该动作。",
      },
    ]);

    try {
      const result = await submitApprovalDecision({
        run_id: runId,
        action_id: selectedApproval.pendingAction.action_id,
        decision,
        actor_id: "ops-supervisor",
        actor_metadata: {
          surface: "supervisor-approval-drawer",
        },
      });

      setConversation(result.session_id);
      setActiveRunId(result.run_id);
      if (result.output) {
        pushBubble("assistant", result.output);
      }
      if (result.pending_action) {
        const nextApproval: ApprovalQueueItem = {
          id: approvalQueueId(result.run_id, result.pending_action),
          runId: result.run_id,
          pendingAction: result.pending_action,
          status: "pending",
        };
        upsertApproval(nextApproval);
      }
      setSelectedApprovalId(null);
      void refreshAuditTimeline(result.run_id);
    } catch (error) {
      console.error(error);
      updateApprovalStatus(approvalId, "pending");
      void messageApi.error("审批恢复失败，请检查后端日志。");
    } finally {
      setSubmitting(false);
    }
  }

  const runtimeBackend = health?.runtime_store.backend ?? "unknown";
  const llmLabel = health ? `${health.llm.provider} / ${health.llm.model}` : "未加载";
  const activeOrderId = dossier.order?.order_id ?? "未载入";
  const activeCustomerName = dossier.customer?.name ?? "待分配";
  const userMessageCount = useMemo(
    () => messages.filter((item) => item.role === "user").length,
    [messages],
  );
  const resolvedActionCount = useMemo(
    () =>
      approvalQueue.filter((item) => item.status === "approved").length +
      (lastAction?.status === "success" ? 1 : 0),
    [approvalQueue, lastAction?.status],
  );
  const trendPoints = useMemo<TrendPoint[]>(
    () => [
      {
        label: "周一",
        primary: 18 + userMessageCount * 2,
        secondary: 10 + policyPreview.length * 3,
      },
      {
        label: "周二",
        primary: 16 + auditLogs.length * 2,
        secondary: 9 + pendingApprovalCount * 3,
      },
      {
        label: "周三",
        primary: 22 + userMessageCount * 3,
        secondary: 12 + resolvedActionCount * 2,
      },
      {
        label: "周四",
        primary: 28 + auditLogs.length * 2,
        secondary: 17 + pendingApprovalCount * 2,
      },
      {
        label: "周五",
        primary: 20 + resolvedActionCount * 3,
        secondary: 13 + policyPreview.length * 2,
      },
      {
        label: "周六",
        primary: 26 + userMessageCount * 2,
        secondary: 18 + resolvedActionCount * 2,
      },
      {
        label: "周日",
        primary: 19 + auditLogs.length * 2,
        secondary: 14 + policyPreview.length * 2,
      },
    ],
    [
      auditLogs.length,
      pendingApprovalCount,
      policyPreview.length,
      resolvedActionCount,
      userMessageCount,
    ],
  );
  const primaryLine = useMemo(() => buildLinePoints(trendPoints, "primary"), [trendPoints]);
  const secondaryLine = useMemo(() => buildLinePoints(trendPoints, "secondary"), [trendPoints]);
  const distribution = useMemo<DistributionItem[]>(
    () => [
      {
        label: "订单咨询",
        value: Math.max(8, userMessageCount * 6),
        color: "#4f8cff",
      },
      {
        label: "物流问题",
        value: dossier.shipment ? 24 : 16,
        color: "#35c9be",
      },
      {
        label: "售后工单",
        value: dossier.ticket ? 18 : 12,
        color: "#ffb357",
      },
      {
        label: "退款问题",
        value: dossier.refund ? 16 : 10,
        color: "#a98bff",
      },
      {
        label: "主管审批",
        value: Math.max(6, pendingApprovalCount * 8),
        color: "#9aa8c4",
      },
    ],
    [dossier.refund, dossier.shipment, dossier.ticket, pendingApprovalCount, userMessageCount],
  );
  const distributionTotal = useMemo(
    () => distribution.reduce((sum, item) => sum + item.value, 0),
    [distribution],
  );
  const distributionGradient = useMemo(() => {
    let offset = 0;
    const stops = distribution.map((item) => {
      const start = (offset / distributionTotal) * 100;
      offset += item.value;
      const end = (offset / distributionTotal) * 100;
      return `${item.color} ${start}% ${end}%`;
    });
    return `conic-gradient(${stops.join(", ")})`;
  }, [distribution, distributionTotal]);
  const approvalPreview = useMemo(() => sortedApprovals.slice(0, 3), [sortedApprovals]);

  function navigateToView(view: ConsoleView) {
    setActiveView(view);
    if (view === "conversation") {
      globalThis.requestAnimationFrame?.(() => {
        workspaceRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
      return;
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function openConversation(prompt?: string) {
    if (prompt) {
      setInputValue(prompt);
    }
    navigateToView("conversation");
  }

  const todoItems = [
    {
      label: "待处理工单",
      value: pendingApprovalCount,
      tone: "blue",
      hint: "进入工单管理处理审批和回执",
      onClick: () => navigateToView("tickets"),
    },
    {
      label: "客户回复",
      value: userMessageCount,
      tone: "red",
      hint: "回到智能会话继续跟进",
      onClick: () => navigateToView("conversation"),
    },
    {
      label: "政策命中",
      value: policyPreview.length,
      tone: "cyan",
      hint: "查看政策依据和命中条款",
      onClick: () => navigateToView("tickets"),
    },
    {
      label: "审计事件",
      value: auditLogs.length,
      tone: "orange",
      hint: "展开调试区查看运行审计",
      onClick: () => {
        setShowDiagnostics(true);
        navigateToView("dashboard");
      },
    },
  ] as const;

  const caseSummary = [
    {
      label: "客户",
      value: activeCustomerName,
      note: dossier.customer ? dossier.customer.phone : "先输入订单号加载客户档案",
    },
    {
      label: "订单",
      value: activeOrderId,
      note: dossier.order ? dossier.order.item_summary : "支持 ORD123 / ORD456 演示",
    },
    {
      label: "物流",
      value: dossier.shipment?.status ?? "待查询",
      note: dossier.shipment?.latest_location ?? "查询后会显示最新位置",
    },
    {
      label: "当前处理",
      value: dossier.ticket?.ticket_id ?? dossier.refund?.refund_request_id ?? "暂无动作",
      note: dossier.ticket
        ? `工单 ${dossier.ticket.status}`
        : dossier.refund
          ? `退款 ${dossier.refund.status}`
          : "建工单或退款后自动写回",
    },
  ];
  const workbenchFocusCards = [
    {
      key: "tickets",
      icon: <FileTextOutlined />,
      title: "工单管理",
      summary: "处理订单、退款、审批和政策依据，所有业务数据在这里汇总。",
      metric: `${pendingApprovalCount} 条待审批`,
      cta: "打开工单管理",
      onClick: () => navigateToView("tickets"),
    },
    {
      key: "conversation",
      icon: <CommentOutlined />,
      title: "智能会话",
      summary: "专注坐席与智能体协作，适合连续下达查单、建工单和退款指令。",
      metric: `${messages.length} 条会话消息`,
      cta: "进入智能会话",
      onClick: () => navigateToView("conversation"),
    },
    {
      key: "current-case",
      icon: <AlertOutlined />,
      title: "当前案件",
      summary: `当前聚焦订单 ${activeOrderId}，客户 ${activeCustomerName}，可随时切入工单处理。`,
      metric: deskState.label,
      cta: "查看当前案件",
      onClick: () => navigateToView("tickets"),
    },
  ] as const;
  const viewCopy = VIEW_COPY[activeView];

  const systemStatusCard = (
    <Card bordered={false} className="surface-card side-card">
      <div className="section-head">
        <Text className="section-kicker">Diagnostics</Text>
        <Title level={4}>系统状态</Title>
      </div>
      <Spin spinning={healthLoading}>
        <Space direction="vertical" size={12} className="full-width">
          <div className="status-row">
            <Text>Runtime store</Text>
            <Tag color={health ? healthColor(health.runtime_store.ok) : "default"}>
              {runtimeBackend}
            </Tag>
          </div>
          <div className="status-row">
            <Text>Business DB</Text>
            <Tag color={health ? healthColor(health.business_database.ok) : "default"}>
              {health?.business_database.schema_ready ? "schema ready" : "pending"}
            </Tag>
          </div>
          <div className="status-row">
            <Text>LLM</Text>
            <Tag color={health ? healthColor(health.llm.ok) : "default"}>{llmLabel}</Tag>
          </div>
          <Paragraph className="status-help">
            {health?.llm.ok
              ? "当前可以直接演示完整智能体链路。"
              : "当前处于降级模式，资源接口仍可访问，但智能体执行会失败。"}
          </Paragraph>
          <Button onClick={() => void refreshHealthStatus()} loading={healthLoading}>
            刷新状态
          </Button>
        </Space>
      </Spin>
    </Card>
  );

  const auditTimelineCard = (
    <Card bordered={false} className="surface-card side-card">
      <div className="section-head section-head-inline">
        <div>
          <Text className="section-kicker">Diagnostics</Text>
          <Title level={4}>审计时间线</Title>
        </div>
        <Tag color={activeRunId ? "blue" : "default"}>{activeRunId ?? "未选择运行"}</Tag>
      </div>
      {auditLogs.length === 0 ? (
        <Empty description={activeRunId ? "当前运行暂时没有审计事件。" : "先选择一条运行，再查看对应审计日志。"} />
      ) : (
        <Timeline
          items={auditLogs.map((item) => ({
            color: item.event_type === "approval_resolved" ? "green" : "blue",
            children: (
              <div className="timeline-card">
                <Text strong>{prettyEventName(item.event_type)}</Text>
                <div className="timeline-time">{formatTimestamp(item.created_at)}</div>
                <pre>{renderJsonPreview(item.payload_json)}</pre>
              </div>
            ),
          }))}
        />
      )}
    </Card>
  );

  const customerOrderCard = (
    <Card bordered={false} className="surface-card side-card">
      <div className="section-head">
        <Text className="section-kicker">Customer & Order</Text>
        <Title level={4}>客户与订单</Title>
      </div>

      <div className="lookup-row">
        <Input
          value={orderLookup}
          onChange={(event) => setOrderLookup(event.target.value.toUpperCase())}
          placeholder="输入订单号，例如 ORD123"
        />
        <Button type="primary" onClick={() => void loadOrderWorkspace(orderLookup)} loading={dossierLoading}>
          载入
        </Button>
      </div>

      <div className="shortcut-row">
        {ORDER_SHORTCUTS.map((orderId) => (
          <Button key={orderId} size="small" onClick={() => void loadOrderWorkspace(orderId)}>
            {orderId}
          </Button>
        ))}
      </div>

      <Spin spinning={dossierLoading}>
        <Space direction="vertical" size={16} className="full-width">
          <Descriptions column={1} size="small" title="客户">
            <Descriptions.Item label="客户 ID">{asText(dossier.customer?.customer_id)}</Descriptions.Item>
            <Descriptions.Item label="姓名">{asText(dossier.customer?.name)}</Descriptions.Item>
            <Descriptions.Item label="邮箱">{asText(dossier.customer?.email)}</Descriptions.Item>
            <Descriptions.Item label="电话">{asText(dossier.customer?.phone)}</Descriptions.Item>
          </Descriptions>

          <Descriptions column={1} size="small" title="订单">
            <Descriptions.Item label="订单号">{asText(dossier.order?.order_id)}</Descriptions.Item>
            <Descriptions.Item label="状态">
              <Tag color={statusColor(dossier.order?.status ?? "")}>{asText(dossier.order?.status)}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="商品">{asText(dossier.order?.item_summary)}</Descriptions.Item>
            <Descriptions.Item label="金额">
              {dossier.order
                ? `${asText(dossier.order.total_amount)} ${asText(dossier.order.currency)}`
                : "—"}
            </Descriptions.Item>
          </Descriptions>

          <Descriptions column={1} size="small" title="物流">
            <Descriptions.Item label="承运商">{asText(dossier.shipment?.carrier)}</Descriptions.Item>
            <Descriptions.Item label="状态">
              <Tag color={statusColor(dossier.shipment?.status ?? "")}>
                {asText(dossier.shipment?.status)}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="最新位置">{asText(dossier.shipment?.latest_location)}</Descriptions.Item>
          </Descriptions>
        </Space>
      </Spin>
    </Card>
  );

  const executionResultCard = (
    <Card bordered={false} className="surface-card side-card">
      <div className="section-head">
        <Text className="section-kicker">Execution Result</Text>
        <Title level={4}>工单与退款执行</Title>
      </div>

      {dossier.ticket === null && dossier.refund === null && lastAction === null ? (
        <Empty description="执行建工单或退款动作后，这里会展示结果。" />
      ) : (
        <Space direction="vertical" size={16} className="full-width">
          <Descriptions column={1} size="small" title="工单">
            <Descriptions.Item label="工单号">{asText(dossier.ticket?.ticket_id)}</Descriptions.Item>
            <Descriptions.Item label="优先级">{asText(dossier.ticket?.priority)}</Descriptions.Item>
            <Descriptions.Item label="状态">
              <Tag color={statusColor(dossier.ticket?.status ?? "")}>{asText(dossier.ticket?.status)}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="摘要">{asText(dossier.ticket?.summary)}</Descriptions.Item>
          </Descriptions>

          <Descriptions column={1} size="small" title="退款">
            <Descriptions.Item label="申请单">{asText(dossier.refund?.refund_request_id)}</Descriptions.Item>
            <Descriptions.Item label="金额">{asText(dossier.refund?.amount)}</Descriptions.Item>
            <Descriptions.Item label="状态">
              <Tag color={statusColor(dossier.refund?.status ?? "")}>{asText(dossier.refund?.status)}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="原因">{asText(dossier.refund?.reason)}</Descriptions.Item>
          </Descriptions>

          {lastAction ? (
            <div className="json-panel">
              <Text className="micro-label">最近动作参数</Text>
              <pre>{renderJsonPreview(lastAction.actionPayload)}</pre>
            </div>
          ) : null}
        </Space>
      )}
    </Card>
  );

  const approvalsCard = (
    <Card bordered={false} className="surface-card side-card">
      <div className="section-head">
        <Text className="section-kicker">Supervisor Approval</Text>
        <Title level={4}>主管审批</Title>
      </div>
      <List
        split={false}
        locale={{ emptyText: "当前没有待主管处理的动作。" }}
        dataSource={sortedApprovals}
        renderItem={(item) => (
          <List.Item
            className="approval-item"
            actions={[
              item.status === "pending" ? (
                <Button
                  key="open"
                  type="link"
                  onClick={() => {
                    setActiveRunId(item.runId);
                    setSelectedApprovalId(item.id);
                    void refreshAuditTimeline(item.runId);
                  }}
                >
                  打开
                </Button>
              ) : (
                <Tag key="status" color={statusColor(item.status)}>
                  {queueStatusLabel(item.status)}
                </Tag>
              ),
            ]}
          >
            <div>
              <Space wrap>
                <Text strong>{actionDisplayName(item.pendingAction.action_name)}</Text>
                <Tag color={riskColor(item.pendingAction.risk_level)}>{item.pendingAction.risk_level}</Tag>
                <Tag>{asText(item.pendingAction.display_payload.order_id)}</Tag>
              </Space>
              <Paragraph>{item.pendingAction.reason}</Paragraph>
            </div>
          </List.Item>
        )}
      />
    </Card>
  );

  const policyReferenceCard = (
    <Card bordered={false} className="surface-card side-card">
      <div className="section-head">
        <Text className="section-kicker">Policy Reference</Text>
        <Title level={4}>政策依据</Title>
      </div>

      <div className="policy-search-row">
        <Input
          value={policyQuery}
          onChange={(event) => setPolicyQuery(event.target.value)}
          placeholder="输入关键词，例如 破损 / 退款"
        />
        <Button onClick={() => void loadPolicyDeck(policyQuery)} loading={policyLoading}>
          查询
        </Button>
      </div>

      <div className="shortcut-row">
        {POLICY_SHORTCUTS.map((item) => (
          <Button key={item} size="small" onClick={() => void loadPolicyDeck(item)}>
            {item}
          </Button>
        ))}
      </div>

      <Spin spinning={policyLoading}>
        {policyPreview.length === 0 ? (
          <Empty description="暂无命中的政策条目" />
        ) : (
          <List
            split={false}
            dataSource={policyPreview}
            renderItem={(item) => (
              <List.Item className="policy-item">
                <div>
                  <Space wrap>
                    <Text strong>{item.title}</Text>
                    <Tag color="blue">{item.category}</Tag>
                  </Space>
                  <Paragraph>{item.content}</Paragraph>
                  <Space wrap>
                    {item.keywords.map((keyword) => (
                      <Tag key={`${item.article_id}-${keyword}`}>{keyword}</Tag>
                    ))}
                  </Space>
                </div>
              </List.Item>
            )}
          />
        )}
      </Spin>
    </Card>
  );

  const conversationSnapshotCard = (
    <Card bordered={false} className="surface-card side-card">
      <div className="section-head">
        <Text className="section-kicker">Current Context</Text>
        <Title level={4}>会话上下文</Title>
      </div>
      <Spin spinning={dossierLoading}>
        <div className="snapshot-list">
          {caseSummary.map((item) => (
            <div key={item.label} className="snapshot-item">
              <Text className="micro-label">{item.label}</Text>
              <Text strong>{item.value}</Text>
              <Text className="snapshot-note">{item.note}</Text>
            </div>
          ))}
        </div>
      </Spin>
      <Button onClick={() => navigateToView("tickets")}>打开工单管理</Button>
    </Card>
  );

  const approvalSnapshotCard = (
    <Card bordered={false} className="surface-card side-card">
      <div className="section-head section-head-inline">
        <div>
          <Text className="section-kicker">Pending Actions</Text>
          <Title level={4}>审批概览</Title>
        </div>
        <Tag color={pendingApprovalCount > 0 ? "gold" : "green"}>{pendingApprovalCount} 条待处理</Tag>
      </div>
      {approvalPreview.length === 0 ? (
        <Empty description="当前没有待审批动作。" />
      ) : (
        <List
          split={false}
          dataSource={approvalPreview}
          renderItem={(item) => (
            <List.Item className="approval-item">
              <div>
                <Space wrap>
                  <Text strong>{actionDisplayName(item.pendingAction.action_name)}</Text>
                  <Tag color={riskColor(item.pendingAction.risk_level)}>{item.pendingAction.risk_level}</Tag>
                </Space>
                <Paragraph>{item.pendingAction.reason}</Paragraph>
              </div>
            </List.Item>
          )}
        />
      )}
      <Button onClick={() => navigateToView("tickets")}>转到工单管理</Button>
    </Card>
  );

  const policySnapshotCard = (
    <Card bordered={false} className="surface-card side-card">
      <div className="section-head section-head-inline">
        <div>
          <Text className="section-kicker">Policy Snapshot</Text>
          <Title level={4}>政策摘要</Title>
        </div>
        <Tag color="blue">{policyPreview.length} 条命中</Tag>
      </div>
      {policyPreview.length === 0 ? (
        <Empty description="当前没有可展示的政策命中。" />
      ) : (
        <div className="snapshot-list">
          {policyPreview.map((item) => (
            <div key={item.article_id} className="snapshot-item">
              <Space wrap>
                <Text strong>{item.title}</Text>
                <Tag color="blue">{item.category}</Tag>
              </Space>
              <Text className="snapshot-note">{item.content}</Text>
            </div>
          ))}
        </div>
      )}
      <Button onClick={() => navigateToView("tickets")}>查看完整政策面板</Button>
    </Card>
  );

  const dashboardView = (
    <>
      <section className="hero-grid">
        <Card bordered={false} className="surface-card hero-card">
          <div className="hero-copy">
            <Text className="section-kicker">Service Overview</Text>
            <Title className="hero-title" level={2}>
              上午好，客服专员
              <span className="hero-wave">👋</span>
            </Title>
            <Paragraph className="hero-note">
              工作台只保留全局信息。聊天、审批和政策处理已经从这里拆出去，分别进入对应版图。
            </Paragraph>

            <div className="desk-chip-row">
              <Tag color="blue">会话 {conversationId ?? "new-session"}</Tag>
              <Tag color="cyan">订单 {activeOrderId}</Tag>
              <Tag color="geekblue">客户 {activeCustomerName}</Tag>
              <Tag color={deskState.color}>{deskState.label}</Tag>
              <Tag color={health ? healthColor(health.llm.ok) : "default"}>{llmLabel}</Tag>
            </div>

            <Spin spinning={dossierLoading}>
              <div className="hero-stats-grid">
                {caseSummary.map((item) => (
                  <div key={item.label} className="hero-stat-card">
                    <Text className="summary-eyebrow">{item.label}</Text>
                    <div className="summary-value">{item.value}</div>
                    <Text className="summary-note">{item.note}</Text>
                  </div>
                ))}
              </div>
            </Spin>
          </div>

          <div className="hero-visual">
            <div className="hero-robot-orb">
              <RobotOutlined />
            </div>
            <div className="hero-floating-chip hero-floating-chip-a">工单处理中</div>
            <div className="hero-floating-chip hero-floating-chip-b">审批已联动</div>
          </div>
        </Card>

        <Card bordered={false} className="surface-card todo-card">
          <div className="section-head">
            <Text className="section-kicker">Todo</Text>
            <Title level={4}>待办事项</Title>
          </div>
          <div className="todo-list">
            {todoItems.map((item) => (
              <button key={item.label} className="todo-item todo-item-button" type="button" onClick={item.onClick}>
                <div className={`todo-badge todo-badge-${item.tone}`} />
                <div className="todo-copy">
                  <Text>{item.label}</Text>
                  <Text className="todo-hint">{item.hint}</Text>
                </div>
                <div className="todo-value">{item.value}</div>
              </button>
            ))}
          </div>
        </Card>
      </section>

      <section className="analytics-grid">
        <Card bordered={false} className="surface-card analytics-card">
          <div className="analytics-head">
            <div>
              <Text className="section-kicker">Ticket Trend</Text>
              <Title level={4}>工单趋势</Title>
            </div>
            <Space>
              <Tag color="blue">新建工单</Tag>
              <Tag color="cyan">已解决工单</Tag>
            </Space>
          </div>
          <div className="trend-chart">
            <svg viewBox="0 0 520 220" className="trend-svg" role="img" aria-label="ticket trend">
              {[40, 80, 120, 160].map((y) => (
                <line key={y} x1="20" y1={y} x2="500" y2={y} className="trend-grid-line" />
              ))}
              <polyline points={primaryLine} className="trend-line trend-line-primary" />
              <polyline points={secondaryLine} className="trend-line trend-line-secondary" />
              {trendPoints.map((point, index) => {
                const primaryPoint = primaryLine.split(" ")[index];
                const secondaryPoint = secondaryLine.split(" ")[index];
                const [primaryX, primaryY] = primaryPoint.split(",");
                const [secondaryX, secondaryY] = secondaryPoint.split(",");
                return (
                  <g key={point.label}>
                    <circle cx={primaryX} cy={primaryY} r="4" className="trend-dot trend-dot-primary" />
                    <circle cx={secondaryX} cy={secondaryY} r="4" className="trend-dot trend-dot-secondary" />
                  </g>
                );
              })}
            </svg>
            <div className="trend-axis-labels">
              {trendPoints.map((point) => (
                <span key={point.label}>{point.label}</span>
              ))}
            </div>
          </div>
        </Card>

        <Card bordered={false} className="surface-card analytics-card">
          <div className="analytics-head">
            <div>
              <Text className="section-kicker">Category Mix</Text>
              <Title level={4}>工单分类占比</Title>
            </div>
          </div>
          <div className="mix-panel">
            <div className="mix-ring" style={{ background: distributionGradient }}>
              <div className="mix-ring-center">
                <span>总任务数</span>
                <strong>{distributionTotal}</strong>
              </div>
            </div>
            <div className="mix-legend">
              {distribution.map((item) => (
                <div key={item.label} className="mix-legend-item">
                  <span className="mix-legend-dot" style={{ backgroundColor: item.color }} />
                  <span className="mix-legend-label">{item.label}</span>
                  <span className="mix-legend-value">{Math.round((item.value / distributionTotal) * 100)}%</span>
                </div>
              ))}
            </div>
          </div>
        </Card>
      </section>

      <section className="focus-grid">
        {workbenchFocusCards.map((item) => (
          <Card key={item.key} bordered={false} className="surface-card focus-card">
            <div className="focus-card-icon">{item.icon}</div>
            <Text className="section-kicker">Focus Area</Text>
            <Title level={4}>{item.title}</Title>
            <Paragraph>{item.summary}</Paragraph>
            <Text className="focus-card-metric">{item.metric}</Text>
            <Button type="primary" onClick={item.onClick}>
              {item.cta}
            </Button>
          </Card>
        ))}
      </section>

      {showDiagnostics ? (
        <section className="diagnostic-section">
          <div className="diagnostic-grid">
            {systemStatusCard}
            {auditTimelineCard}
          </div>
        </section>
      ) : null}
    </>
  );

  const ticketManagementView = (
    <main className="management-grid">
      <section className="management-primary">
        {customerOrderCard}
        {executionResultCard}
        {showDiagnostics ? auditTimelineCard : null}
      </section>
      <aside className="management-side">
        {approvalsCard}
        {policyReferenceCard}
        {showDiagnostics ? systemStatusCard : null}
      </aside>
    </main>
  );

  const conversationView = (
    <main className="conversation-grid">
      <section className="conversation-main">
        <Card bordered={false} className="surface-card workspace-card">
          <div ref={workspaceRef} className="workspace-anchor" />
          <div className="section-head section-head-inline">
            <div>
              <Text className="section-kicker">Intelligent Conversation</Text>
              <Title level={4}>智能会话</Title>
            </div>
            <Tag color={deskState.color}>{deskState.label}</Tag>
          </div>

          <div className="conversation-stage">
            <div className="conversation-stage-head">
              <div>
                <Text className="section-kicker">Live Agent Loop</Text>
                <Title level={4}>坐席协作面板</Title>
                <Paragraph className="conversation-stage-note">
                  当前围绕订单 {activeOrderId} 展开处理。消息流、动作状态和会话上下文都集中显示在这一块。
                </Paragraph>
              </div>
              <div className="conversation-chip-stack">
                <span className="stage-chip">会话 {conversationId ?? "new-session"}</span>
                <span className="stage-chip">运行 {activeRunId ?? "未激活"}</span>
                <span className="stage-chip">客户 {activeCustomerName}</span>
                <span className="stage-chip">消息 {messages.length}</span>
              </div>
            </div>

            <div className="command-rail">
              {QUICK_ACTIONS.map((item) => (
                <button
                  key={item.title}
                  className="command-pill"
                  type="button"
                  onClick={() => setInputValue(item.prompt)}
                >
                  <span className="command-pill-icon">{item.icon}</span>
                  <span className="command-pill-copy">
                    <span className="command-pill-title">{item.title}</span>
                    <span className="command-pill-summary">{item.summary}</span>
                  </span>
                  <ArrowRightOutlined className="command-pill-arrow" />
                </button>
              ))}
            </div>

            <div className={`execution-banner execution-banner-${deskState.tone} conversation-status-band`}>
              <div className="execution-head">
                <Text strong>{deskState.label}</Text>
                {lastAction ? (
                  <Tag color={statusColor(lastAction.status)}>{actionDisplayName(lastAction.actionName)}</Tag>
                ) : null}
              </div>
              <Paragraph className="execution-note">{deskState.note}</Paragraph>
              <Text className="execution-meta">
                {lastAction ? `动作 ID：${lastAction.actionId}` : "从命令栏选一个动作，或直接在下方输入指令。"}
              </Text>
            </div>

            <div className="chat-stream" ref={messageListRef}>
              {messages.length === 0 ? (
                <div className="chat-empty-state">
                  <div className="chat-empty-orb">
                    <CommentOutlined />
                  </div>
                  <Title level={4}>会话还没开始</Title>
                  <Paragraph className="chat-empty-note">
                    先给智能体一个明确目标，比如查订单、查物流、建工单或发起退款。下方推荐指令会直接填入输入框。
                  </Paragraph>
                  <div className="chat-empty-actions">
                    {QUICK_ACTIONS.slice(0, 3).map((item) => (
                      <button
                        key={item.title}
                        className="chat-empty-pill"
                        type="button"
                        onClick={() => setInputValue(item.prompt)}
                      >
                        {item.title}
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                messages.map((item) => (
                  <div key={item.id} className={`chat-row chat-row-${item.role}`}>
                    <div className={`chat-avatar chat-avatar-${item.role}`}>{bubbleMark(item.role)}</div>
                    <div className={`chat-card chat-card-${item.role}`}>
                      <div className="chat-meta">
                        <Text className="bubble-role">{bubbleLabel(item.role)}</Text>
                        {item.role === "assistant" && item.text.trim().length === 0 ? (
                          <span className="chat-thinking">思考中</span>
                        ) : null}
                      </div>
                      <div className={`chat-bubble chat-bubble-${item.role}`}>
                        <Paragraph className="bubble-text">
                          {item.text || (item.role === "assistant" ? "智能体正在组织回复..." : "...")}
                        </Paragraph>
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>

            <div className="composer-panel conversation-composer">
              <div className="composer-toolbar">
                <div>
                  <Text strong>坐席指令</Text>
                  <Paragraph className="composer-caption">
                    这里输入的是客服给智能体的操作指令，不是客户外部聊天窗口。
                  </Paragraph>
                </div>
                <div className="composer-token-row">
                  <span className="composer-token">订单 {activeOrderId}</span>
                  <span className="composer-token">高风险动作自动审批</span>
                  <span className="composer-token">Ctrl / Cmd + Enter 发送</span>
                </div>
              </div>

              <Input.TextArea
                value={inputValue}
                onChange={(event) => setInputValue(event.target.value)}
                onPressEnter={(event) => {
                  if (event.ctrlKey || event.metaKey) {
                    event.preventDefault();
                    void submitPrompt();
                  }
                }}
                autoSize={{ minRows: 4, maxRows: 8 }}
                placeholder="例如：帮我查看订单 ORD123 的物流状态；或：为该客户创建破损工单并申请退款 200 元"
              />

              <div className="composer-footer">
                <Paragraph className="composer-hint">
                  推荐流程：先查订单 / 查物流，再建工单、发起退款。高风险动作会自动进入主管审批。
                </Paragraph>
                <Space wrap>
                  <Button onClick={resetConversationWorkspace} disabled={submitting}>
                    新建会话
                  </Button>
                  <Button type="primary" onClick={() => void submitPrompt()} loading={submitting}>
                    发送指令
                  </Button>
                </Space>
              </div>
            </div>
          </div>
        </Card>

        {showDiagnostics ? (
          <section className="diagnostic-section">
            <div className="diagnostic-grid">
              {systemStatusCard}
              {auditTimelineCard}
            </div>
          </section>
        ) : null}
      </section>

      <aside className="conversation-side">
        {conversationSnapshotCard}
        {approvalSnapshotCard}
        {policySnapshotCard}
      </aside>
    </main>
  );

  return (
    <>
      {contextHolder}
      <div className="desk-page">
        <div className="ambient ambient-teal" />
        <div className="ambient ambient-copper" />

        <div className="console-shell">
          <aside className="surface-card console-sidebar">
            <div className="brand-panel">
              <div className="brand-mark">
                <RobotOutlined />
              </div>
              <div className="brand-copy">
                <div className="brand-title">售后客服工单智能体</div>
                <div className="brand-subtitle">AI赋能 · 高效服务 · 客户满意</div>
              </div>
            </div>

            <nav className="sidebar-nav">
              {NAVIGATION_ITEMS.map((item) => (
                <button
                  key={item.key}
                  className={`sidebar-link ${activeView === item.key ? "sidebar-link-active" : ""}`}
                  type="button"
                  onClick={() => navigateToView(item.key)}
                >
                  <span className="sidebar-link-icon">{item.icon}</span>
                  <span className="sidebar-link-copy">
                    <span className="sidebar-link-label">{item.label}</span>
                    <span className="sidebar-link-summary">{item.summary}</span>
                  </span>
                </button>
              ))}
            </nav>

            <div className="sidebar-assistant">
              <div className="sidebar-assistant-robot">
                <RobotOutlined />
              </div>
              <Title level={5}>Hi，我是智能客服助手</Title>
              <Paragraph>
                我可以帮你处理工单、查询订单与物流、生成退款申请和主管审批材料。
              </Paragraph>
              <Button
                type="primary"
                block
                onClick={() => openConversation()}
              >
                立即对话
              </Button>
            </div>
          </aside>

          <div className="console-main">
            <header className="surface-card console-topbar">
              <div>
                <Text className="section-kicker">{viewCopy.kicker}</Text>
                <Title level={3}>{viewCopy.title}</Title>
                <Paragraph className="topbar-copy">{viewCopy.description}</Paragraph>
              </div>
              <div className="topbar-actions">
                <Badge count={pendingApprovalCount} size="small">
                  <button
                    className="topbar-icon-button"
                    type="button"
                    aria-label="tickets"
                    onClick={() => navigateToView("tickets")}
                  >
                    <BellOutlined />
                  </button>
                </Badge>
                <button
                  className="topbar-icon-button"
                  type="button"
                  aria-label="conversation"
                  onClick={() => openConversation()}
                >
                  <CommentOutlined />
                </button>
                <Button onClick={() => setShowDiagnostics((current) => !current)}>
                  {showDiagnostics ? "收起调试区" : "展开调试区"}
                </Button>
                <div className="operator-chip">
                  <Avatar size={42} className="operator-avatar">
                    客
                  </Avatar>
                  <div>
                    <div className="operator-name">客服专员</div>
                    <div className="operator-status">在线值守</div>
                  </div>
                </div>
              </div>
            </header>
            {activeView === "dashboard"
              ? dashboardView
              : activeView === "tickets"
                ? ticketManagementView
                : conversationView}
          </div>
        </div>

        <Drawer
          open={selectedApproval !== null}
          onClose={() => setSelectedApprovalId(null)}
          title="主管审批"
          width={480}
          extra={
            <Space>
              <Button
                danger
                onClick={() => void handleApprovalDecision("rejected")}
                disabled={!selectedApproval || submitting}
              >
                拒绝
              </Button>
              <Button
                type="primary"
                onClick={() => void handleApprovalDecision("approved")}
                disabled={!selectedApproval || submitting}
              >
                批准
              </Button>
            </Space>
          }
        >
          {selectedApproval ? (
            <Space direction="vertical" size={16} className="full-width">
              <Paragraph className="drawer-note">
                该抽屉只面向主管。客服可以发起高风险动作，但不能在客户界面直接批准。
              </Paragraph>

              <Descriptions column={1} bordered size="small">
                <Descriptions.Item label="Run ID">{selectedApproval.runId}</Descriptions.Item>
                <Descriptions.Item label="动作">
                  {actionDisplayName(selectedApproval.pendingAction.action_name)}
                </Descriptions.Item>
                <Descriptions.Item label="订单号">
                  {asText(selectedApproval.pendingAction.display_payload.order_id)}
                </Descriptions.Item>
                <Descriptions.Item label="金额">
                  {asText(selectedApproval.pendingAction.display_payload.amount)}
                </Descriptions.Item>
                <Descriptions.Item label="风险">
                  <Tag color={riskColor(selectedApproval.pendingAction.risk_level)}>
                    {selectedApproval.pendingAction.risk_level}
                  </Tag>
                </Descriptions.Item>
                <Descriptions.Item label="审批原因">
                  {selectedApproval.pendingAction.reason}
                </Descriptions.Item>
              </Descriptions>

              <div className="drawer-block">
                <Text className="micro-label">展示载荷</Text>
                <pre>{renderJsonPreview(selectedApproval.pendingAction.display_payload)}</pre>
              </div>

              <div className="drawer-block">
                <Text className="micro-label">原始动作参数</Text>
                <pre>{renderJsonPreview(selectedApproval.pendingAction.action_payload)}</pre>
              </div>
            </Space>
          ) : null}
        </Drawer>
      </div>
    </>
  );
}

export default App;
