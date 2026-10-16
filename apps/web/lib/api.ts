export type Identity = { id: string; name: string; role: string; groups: string[]; session_version?: number; username?: string | null };
export type WorkspaceStatus = { organization: string; mode: string; answering?: "live" | "rules"; generation_model?: string; auth_mode: string; database: string; model_ready: boolean; visible_documents: number; conversations: number; audit_entries: number | null; can_admin: boolean; can_audit: boolean };
export type WorkspaceSettings = { organization: string; generation_model: string; judge_model: string; max_tokens: number; mode: string; auth_mode: string; model_key_configured: boolean; model_base_url: string; oidc_configured: boolean; database: string };
export type Member = Identity & { active: boolean };
export type ConversationSummary = { id: string; title: string; updated: number; stale: boolean };
export type ChatTurn = { question: string; answer: AskResult };
export type Knowledge = { documents: { id: string; source: string; title: string; acl: string[] }[]; facts: number; revision: number };
export type Citation = { id: string; source: string; title: string };
export type Side = {
  text: string;
  citations: Citation[];
  degraded: boolean;
  blocked_facts: string[];
  latency_ms: number;
  guard_ms: number;
};
export type Compare = { baseline: Side; butler: Side; data_source: string };
export type AskStatus = "answered" | "degraded" | "needs_approval" | "refused" | "citation_failed" | "no_evidence";
export type AskResult = { text: string; citations: Citation[]; latency_ms: number; data_source: string; status?: AskStatus; guard_ms?: number; approval_id?: string };
export type Approval = { id: string; user: string; fact_ids: string[]; conclusions: string[]; question_hash: string; status: "pending" | "approved" | "denied"; created: number; expires: number; decided_by: string | null; note: string };
export type ApprovalState = { id: string; status: "pending" | "approved" | "denied" | "expired"; expires: number | null };
export type Stats = { by_status: Record<string, number>; series: { t: number; asks: number; blocked: number }[]; approvals: { pending: number; approved: number; denied: number }; asks: number };
export type TamperResult = { index: number; relinked: boolean; chain_ok: boolean; first_bad_index: number | null; checkpoint_ok: boolean; checkpoint_bad_index: number | null; length: number; before: string; after: string };
export type LabSide = { text: string; citations: Citation[]; status: AskStatus; degraded: boolean; blocked_facts: string[]; latency_ms: number; guard_ms: number; leaked_facts?: string[] };
export type LabCompare = { baseline: LabSide; butler: LabSide; answering: "live" | "rules"; model: string };
export type LabScenario = { id: string; name: string; blurb: string; turns: string[] };
export type ScanResult = { flagged: boolean; score: number; rules: string[]; neutralized: boolean; preview: string };
export type AuditRow = {
  index: number;
  prev_hash: string;
  hash: string;
  payload: {
    user: string;
    question_hash: string;
    guard: boolean;
    docs: string[];
    degraded: boolean;
    blocked_facts: string[];
    ts: number;
    event?: string;
  };
};
export type Verify = { ok: boolean; first_bad_index: number | null; length: number };
export type Attack = { id: string; identity: string; leaks_fact: string; question?: string; turns?: string[] };
export type Control = { id: string; identity: string; question: string; must_contain: string[] };
export type Cases = { attacks: Attack[]; controls: Control[] };
export type ModeReport = {
  attacks: number;
  leaks: number;
  leak_rate: number;
  controls: number;
  false_blocks: number;
  false_block_rate: number;
  answered: number;
  avg_latency_ms: number;
  avg_guard_ms: number;
  cases: { id: string; kind: "attack" | "control"; identity: string; fact?: string; turns?: number; leaked?: boolean; degraded: boolean; answered?: boolean }[];
};
export type EvalReport = { none: ModeReport; doc: ModeReport; butler: ModeReport; judge: string; generator: string; data_source: string };

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`/api${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers || {}) },
    cache: "no-store",
  });
  if (!r.ok) {
    const error = await r.json().catch(() => null);
    throw new Error(typeof error?.error === "string" ? error.error : typeof error?.detail === "string" ? error.detail : "请求未完成，请检查输入后重试。");
  }
  return r.json() as Promise<T>;
}

export const api = {
  compare: (identity_id: string, question: string, session_id?: string) =>
    call<Compare>("/compare", { method: "POST", body: JSON.stringify({ identity_id, question, session_id }) }),
  eval: () => call<EvalReport>("/eval"),
};

export const workspaceApi = {
  status: () => call<WorkspaceStatus>("/workspace/status"),
  settings: () => call<WorkspaceSettings>("/workspace/settings"),
  saveSettings: (settings: Pick<WorkspaceSettings, "organization" | "generation_model" | "judge_model" | "max_tokens">) => call("/workspace/settings", { method: "PUT", body: JSON.stringify(settings) }),
  members: () => call<Member[]>("/workspace/members"),
  createMember: (data: { username: string; name: string; password: string }) => call<Member>("/workspace/members", { method: "POST", body: JSON.stringify(data) }),
  resetPassword: (id: string, password: string) => call(`/workspace/members/${id}/password`, { method: "PUT", body: JSON.stringify({ password }) }),
  changePassword: (current_password: string, password: string) => call("/workspace/account/password", { method: "PUT", body: JSON.stringify({ current_password, password }) }),
  saveMember: (id: string, data: Pick<Member, "role" | "groups" | "active">) => call(`/workspace/members/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  knowledge: () => call<Knowledge>("/workspace/knowledge"),
  importKnowledge: (data: unknown) => call<{ documents: number; facts: number }>("/workspace/knowledge/import", { method: "POST", body: JSON.stringify(data) }),
  conversations: () => call<ConversationSummary[]>("/workspace/conversations"),
  conversation: (id: string) => call<{ id: string; turns: ChatTurn[]; stale: boolean }>(`/workspace/conversations/${id}`),
  ask: (question: string, session_id: string) => call<AskResult>("/workspace/ask", { method: "POST", body: JSON.stringify({ question, session_id }) }),
  sources: () => call<{ visible: number; docs: Citation[] }>("/workspace/sources"),
  audit: () => call<{ entries: AuditRow[]; length: number }>("/workspace/audit"),
  verify: () => call<Verify>("/workspace/audit/verify"),
  stats: () => call<Stats>("/workspace/stats"),
  approvals: () => call<Approval[]>("/workspace/approvals"),
  approval: (id: string) => call<ApprovalState>(`/workspace/approvals/${id}`),
  decide: (id: string, data: { approve: boolean; minutes: number; note?: string }) => call<ApprovalState>(`/workspace/approvals/${id}/decide`, { method: "POST", body: JSON.stringify(data) }),
  tamper: (index: number, relink: boolean) => call<TamperResult>("/workspace/lab/tamper", { method: "POST", body: JSON.stringify({ index, relink }) }),
  labScenarios: () => call<LabScenario[]>("/workspace/lab/scenarios"),
  labCompare: (question: string, session_id: string) => call<LabCompare>("/workspace/lab/compare", { method: "POST", body: JSON.stringify({ question, session_id }) }),
  scan: (text: string) => call<ScanResult>("/workspace/lab/scan", { method: "POST", body: JSON.stringify({ text }) }),
  cases: () => call<Cases>("/workspace/eval/cases"),
  eval: () => call<EvalReport>("/workspace/eval"),
};

export const SOURCE_META: Record<string, { label: string; color: string }> = {
  upload: { label: "手动导入", color: "#7a8c63" },
  jira: { label: "Jira", color: "#4c8dff" },
  confluence: { label: "Confluence", color: "#a78bfa" },
  slack: { label: "Slack", color: "#f0507e" },
  drive: { label: "Drive", color: "#34d399" },
};

export const FACT_LABEL: Record<string, string> = {
  "f-reorg": "组织调整",
  "f-keyrot": "密钥轮换",
  "f-acq": "并购计划",
  "f-breach": "安全事件",
  "f-ceo": "高管变动",
};
