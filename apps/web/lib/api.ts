export type Identity = { id: string; name: string; role: string; groups: string[]; session_version?: number; username?: string | null; blurb?: string };
export type WorkspaceStatus = { organization: string; mode: string; answering?: "live" | "rules"; generation_model?: string; auth_mode: string; database: string; model_ready: boolean; visible_documents: number; conversations: number; audit_entries: number | null; can_admin: boolean; can_audit: boolean };
export type WorkspaceSettings = { organization: string; generation_model: string; judge_model: string; max_tokens: number; mode: string; auth_mode: string; model_key_configured: boolean; model_base_url: string; oidc_configured: boolean; database: string };
export type Member = Identity & { active: boolean };
export type ConversationSummary = { id: string; title: string; updated: number; stale: boolean };
export type ChatTurn = { question: string; answer: AskResult };
export type Knowledge = { documents: { id: string; source: string; title: string; acl: string[]; container?: string | null; modality?: string | null }[]; total?: number; facts: number; revision: number };
export type Modality = "text" | "image" | "pdf" | "audio" | "video" | "sheet" | "slides";
export type Citation = { id: string; source: string; title: string; modality?: Modality; container?: string | null; url?: string | null; updated?: number | null; kind?: string | null; media?: boolean; mime?: string | null; parent?: string | null; file_name?: string | null; synced?: number | null };
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
export type AskTrace = { queries?: number; platforms?: Record<string, number>; expanded?: number; plan_source?: string };
export type AskResult = { trace?: AskTrace; text: string; citations: Citation[]; latency_ms: number; data_source: string; status?: AskStatus; guard_ms?: number; approval_id?: string; followups?: string[] };
export type AskStage = { stage: "planning" | "planned" | "retrieved" | "generating" | "checking"; docs?: { id: string; title: string; source: string }[]; queries?: string[]; platforms?: string[] | Record<string, number>; source?: string };
export type Approval = { id: string; user: string; fact_ids: string[]; conclusions: string[]; question_hash: string; status: "pending" | "approved" | "denied"; created: number; expires: number; decided_by: string | null; note: string };
export type ApprovalState = { id: string; status: "pending" | "approved" | "denied" | "expired"; expires: number | null };
export type Stats = { by_status: Record<string, number>; series: { t: number; asks: number; blocked: number }[]; approvals: { pending: number; approved: number; denied: number }; asks: number };
export type TamperResult = { index: number; relinked: boolean; chain_ok: boolean; first_bad_index: number | null; checkpoint_ok: boolean; checkpoint_bad_index: number | null; length: number; before: string; after: string };
export type LabSide = { text: string; citations: Citation[]; status: AskStatus; degraded: boolean; blocked_facts: string[]; latency_ms: number; guard_ms: number; leaked_facts?: string[] };
export type LabCompare = { baseline: LabSide; butler: LabSide; answering: "live" | "rules"; model: string };
export type LabScenario = { id: string; name: string; blurb: string; turns: string[] };
export type SourcesSummary = { visible: number; by_source: Record<string, number>; by_modality: Record<string, number>; containers: { source: string; name: string; count: number }[]; docs: { id: string; source: string; title: string }[] };
export type PlatformState = { state: "pending" | "loading" | "ready" | "error"; loaded: number; total: number; last_sync: number | null; last_changes: number; lag_seconds: number; errors: number };
export type SimStats = { confluence: { spaces: number; pages: number; restricted_pages: number }; jira: { projects: number; issues: number; secured_issues: number }; slack: { workspaces: number; channels: number; private_channels: number; threads: number; dms: number }; drive: { shared_drives: number; files: number; limited_files: number; external_links: number }; multimodal: Record<string, number>; people: number };
export type SimStatus = { enabled: boolean; ready?: boolean; interval_seconds?: number; platforms?: Record<string, PlatformState>; stats?: SimStats; documents?: number };
export type SimPreset = { id: string; platform: string; title: string; scenario: string; action: string; params: Record<string, unknown>; undo?: { action: string; params: Record<string, unknown> }; then?: { user: string; question: string } };
export type MutateResult = { result: { platform: string; object: string; title?: string }; sync: Record<string, unknown> };
export type AuditDoc = { id: string; title: string; platform: string; container: string; modality?: string; space?: string };
export type AuditHit = { ts: number; user: string; event: string; status: string; question_hash: string; allowed: AuditDoc[]; denied: AuditDoc[]; synthetic: boolean; hash: string };
export type AuditResult = { total: number; rows: AuditHit[]; scanned: number; filters?: Record<string, string | number>; via?: string };
export type ScenarioDef = { id: string; title: string; brief: string; steps: { label: string; kind: string; as?: string; q?: string }[] };
export type ScenarioEvent = { event: "step" | "result" | "done"; i?: number; label?: string; kind?: string; as?: string; q?: string; status?: "running" | "pass" | "fail"; seconds?: number; checks?: { label: string; ok: boolean }[]; answer?: { text: string; status: string; citations: { id: string; title: string; source: string; modality?: string }[]; trace?: AskTrace }; audit?: { filters: Record<string, unknown>; total: number }; passed?: number; total?: number };
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
  knowledge: (q = "", source = "") => call<Knowledge>(`/workspace/knowledge?q=${encodeURIComponent(q)}&source=${encodeURIComponent(source)}`),
  importKnowledge: (data: unknown) => call<{ documents: number; facts: number }>("/workspace/knowledge/import", { method: "POST", body: JSON.stringify(data) }),
  conversations: () => call<ConversationSummary[]>("/workspace/conversations"),
  conversation: (id: string) => call<{ id: string; turns: ChatTurn[]; stale: boolean }>(`/workspace/conversations/${id}`),
  ask: (question: string, session_id: string) => call<AskResult>("/workspace/ask", { method: "POST", body: JSON.stringify({ question, session_id }) }),
  /** Same flow as ask(), but reports the stages as they happen (NDJSON); resolves with the final answer. */
  askStream: async (question: string, session_id: string, onStage: (s: AskStage) => void): Promise<AskResult> => {
    const r = await fetch("/api/workspace/ask/stream", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ question, session_id }), cache: "no-store" });
    if (!r.ok || !r.body) { const e = await r.json().catch(() => null); throw new Error(typeof e?.error === "string" ? e.error : typeof e?.detail === "string" ? e.detail : "这次没有拿到回答，请稍后再试。"); }
    const reader = r.body.getReader(), decoder = new TextDecoder(); let buffer = "", answer: AskResult | null = null;
    for (;;) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const lines = buffer.split("\n"); buffer = lines.pop() ?? "";
      for (const line of lines) {
        if (!line.trim()) continue;
        const event = JSON.parse(line);
        if (event.event === "stage") onStage(event as AskStage);
        else if (event.event === "done") answer = event.answer as AskResult;
        else if (event.event === "error") throw new Error(event.message || "这次没有拿到回答。");
      }
      if (done) break;
    }
    if (!answer) throw new Error("这次没有拿到回答，请稍后再试。");
    return answer;
  },
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
  sourcesSummary: () => call<SourcesSummary>("/workspace/sources"),
  simStatus: () => call<SimStatus>("/workspace/sim/status"),
  simPresets: () => call<{ presets: SimPreset[]; actions: Record<string, string> }>("/workspace/sim/presets"),
  simMutate: (action: string, params: Record<string, unknown>) => call<MutateResult>("/workspace/sim/mutate", { method: "POST", body: JSON.stringify({ action, params }) }),
  simSync: () => call<{ seconds: number; result: Record<string, unknown> }>("/workspace/sim/sync", { method: "POST", body: "{}" }),
  simLookup: (kind: string, q: string) => call<{ items: { id: string; label: string }[] }>(`/workspace/sim/lookup?kind=${encodeURIComponent(kind)}&q=${encodeURIComponent(q)}`),
  auditQuery: (f: Record<string, string | number>) => call<AuditResult>(`/workspace/audit/query?${new URLSearchParams(Object.entries(f).filter(([, v]) => v !== "" && v !== 0).map(([k, v]) => [k, String(v)])).toString()}`),
  auditAsk: (text: string) => call<AuditResult>("/workspace/audit/ask", { method: "POST", body: JSON.stringify({ text }) }),
  scenarios: () => call<ScenarioDef[]>("/workspace/scenarios"),
  transcript: (id: string) => call<{ duration: number; segments: { speaker: string; start: number; end: number; text: string }[] }>(`/workspace/transcript/${encodeURIComponent(id)}`),
  /** Runs one acceptance scenario and reports each step as it happens (NDJSON). */
  runScenario: async (id: string, onEvent: (e: ScenarioEvent) => void): Promise<void> => {
    const r = await fetch(`/api/workspace/scenarios/${id}/run`, { method: "POST", headers: { "content-type": "application/json" }, body: "{}", cache: "no-store" });
    if (!r.ok || !r.body) { const e = await r.json().catch(() => null); throw new Error(typeof e?.error === "string" ? e.error : typeof e?.detail === "string" ? e.detail : "用例没有运行起来。"); }
    const reader = r.body.getReader(), decoder = new TextDecoder(); let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const lines = buffer.split("\n"); buffer = lines.pop() ?? "";
      for (const line of lines) if (line.trim()) onEvent(JSON.parse(line) as ScenarioEvent);
      if (done) break;
    }
  },
  scan: (text: string) => call<ScanResult>("/workspace/lab/scan", { method: "POST", body: JSON.stringify({ text }) }),
  cases: () => call<Cases>("/workspace/eval/cases"),
  eval: () => call<EvalReport>("/workspace/eval"),
};

export const MODALITY_LABEL: Record<string, string> = { text: "文字", image: "图片", pdf: "扫描件 PDF", audio: "录音", video: "视频", sheet: "表格", slides: "幻灯片" };
export const mediaUrl = (id: string) => `/api/workspace/media/${encodeURIComponent(id)}`;

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
