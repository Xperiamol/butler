"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import StatsPanel from "./StatsPanel";
import { CountUp, Reveal } from "./motion";
import { workspaceApi as api, type WorkspaceSettings, type WorkspaceStatus, type Knowledge, type Member } from "@/lib/api";

const message = (e: unknown) => e instanceof Error ? e.message : "操作未完成，请重试。";
const changed = () => window.dispatchEvent(new Event("workspace-updated"));

function useResource<T>(loader: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null), [error, setError] = useState("");
  const load = useCallback(async () => { try { setData(await loader()); setError(""); } catch (e) { setError(message(e)); } }, [loader]);
  useEffect(() => { void load(); }, [load]);
  return { data, error, load };
}

function ResourceState({ error, retry }: { error: string; retry: () => void }) {
  return error ? <div className="admin-error" role="alert"><p>{error}</p><button className="btn sm" onClick={retry}>重试</button></div> : <p className="admin-loading" role="status"><span className="spinner" />正在读取…</p>;
}

export function WorkspaceOverview() {
  const { data: s, error, load } = useResource<WorkspaceStatus>(api.status);
  return <main className="admin-page"><div className="admin-heading"><div><span className="overline">工作区概览</span><h1>{s?.organization || "工作区"}</h1><p>资料、问答与管理，从这里开始。</p></div><Link className="btn primary" href="/workspace">开始提问 <span>↗</span></Link></div>
    {!s ? <ResourceState error={error} retry={load} /> : <>
      <div className="workspace-metrics reveal-stagger"><div><span>可用资料</span><strong><CountUp value={s.visible_documents} /><small>份</small></strong><Link href={s.can_admin ? "/workspace/knowledge" : "/workspace"}>查看知识范围 ↗</Link></div><div><span>我的会话</span><strong><CountUp value={s.conversations} /><small>个</small></strong><Link href="/workspace">继续会话 ↗</Link></div><div><span>{s.can_audit ? "审计记录" : "回答保护"}</span><strong>{s.can_audit ? <CountUp value={s.audit_entries ?? 0} /> : "已启用"}{s.can_audit && <small>条</small>}</strong><span>{s.can_audit ? "包含问答和管理变更" : "按身份检索与检查"}</span></div></div>
      {s.can_audit && <StatsPanel admin={s.can_admin} />}
      <section className="admin-section"><div className="section-title"><h2>{s.can_admin ? "工作区运行状态" : "工作区服务"}</h2><span className="quiet-tag">{s.mode === "enterprise" ? "企业环境" : "演示环境"}</span></div><div className="service-grid"><div><span className="service-icon">↪</span><h3>身份认证</h3><p>{s.auth_mode === "local" ? "账号密码" : "企业 SSO"}</p><span className="service-state ready">已登录</span></div><div><span className="service-icon">▤</span><h3>数据存储</h3><p>{s.database === "postgresql" ? "PostgreSQL" : "SQLite · 本地预览"}</p><span className="service-state ready">已连接</span></div><div><span className="service-icon">✳</span><h3>回答服务</h3><p>{s.mode === "demo" ? "规则演示" : s.model_ready ? "生成 + 安全检查" : "等待模型配置"}</p><span className={`service-state ${s.model_ready ? "ready" : "waiting"}`}>{s.mode === "demo" ? "可体验" : s.model_ready ? "已配置" : "待配置"}</span></div></div></section>
      {s.can_admin && <section className="admin-section"><div className="section-title"><h2>管理工作区</h2></div><div className="admin-destinations"><Link href="/workspace/approvals"><span>00</span><div><h3>预授权审批</h3><p>处理被拦下的回答，限时放行</p></div><b>↗</b></Link><Link href="/workspace/settings"><span>01</span><div><h3>配置中心</h3><p>组织名称、生成模型与检查模型</p></div><b>↗</b></Link><Link href="/workspace/knowledge"><span>02</span><div><h3>知识资料</h3><p>导入资料，设置来源权限</p></div><b>↗</b></Link><Link href="/workspace/members"><span>03</span><div><h3>成员与权限</h3><p>管理角色、权限组和账号状态</p></div><b>↗</b></Link></div></section>}
    </>}
  </main>;
}

export function SettingsPanel() {
  const { data, error, load } = useResource<WorkspaceSettings>(api.settings);
  return <main className="admin-page"><div className="admin-heading"><div><span className="overline">管理 / 配置</span><h1>配置中心</h1><p>配置会保存到工作区，下一次请求生效。</p></div></div>{data ? <SettingsForm initial={data} /> : <ResourceState error={error} retry={load} />}</main>;
}

function SettingsForm({ initial }: { initial: WorkspaceSettings }) {
  const [values, setValues] = useState({ organization: initial.organization, generation_model: initial.generation_model, judge_model: initial.judge_model, max_tokens: initial.max_tokens });
  const [busy, setBusy] = useState(false), [notice, setNotice] = useState(""), [error, setError] = useState("");
  return <form onSubmit={async (e) => { e.preventDefault(); setBusy(true); setNotice(""); setError(""); try { await api.saveSettings(values); setNotice("配置已保存"); changed(); } catch (e) { setError(message(e)); } finally { setBusy(false); } }}>
    <fieldset className="settings-fields" disabled={busy}>
      <section className="admin-section settings-section"><div><h2>工作区</h2><p>显示在侧栏和概览中。</p></div><label className="field">组织名称<input name="organization" required maxLength={80} value={values.organization} onChange={(e) => setValues({ ...values, organization: e.target.value })} /></label></section>
      <section className="admin-section settings-section"><div><h2>模型服务</h2><p>生成回答和安全检查分别配置。</p>{initial.mode === "demo" && <span className="quiet-tag">演示环境使用规则引擎</span>}</div><div className="field-stack"><div className="provider-summary"><span>腾讯混元 · 兼容接口</span><span className={`service-state ${initial.model_key_configured ? "ready" : "waiting"}`}>{initial.model_key_configured ? "服务端密钥已设置" : "服务端密钥未设置"}</span><code>{initial.model_base_url}</code></div><label className="field">生成模型<input name="generation_model" maxLength={100} placeholder="模型 ID" value={values.generation_model} onChange={(e) => setValues({ ...values, generation_model: e.target.value })} /></label><label className="field">安全检查模型<input name="judge_model" maxLength={100} placeholder="模型 ID" value={values.judge_model} onChange={(e) => setValues({ ...values, judge_model: e.target.value })} /></label><label className="field">最大输出 Token<input name="max_tokens" type="number" min={256} max={4096} required value={values.max_tokens} onChange={(e) => setValues({ ...values, max_tokens: Number(e.target.value) })} /></label><p className="field-help">API 密钥通过服务端 HUNYUAN_API_KEY 设置。</p></div></section>
    </fieldset>
    <section className="admin-section"><div className="section-title"><h2>部署信息</h2><span className="quiet-tag">由部署环境管理</span></div><dl className="deployment-details"><div><dt>运行模式</dt><dd>{initial.mode === "enterprise" ? "企业" : "演示"}</dd></div><div><dt>数据库</dt><dd>{initial.database === "postgresql" ? "PostgreSQL" : "SQLite"}</dd></div><div><dt>登录方式</dt><dd>{initial.auth_mode === "local" ? "账号密码" : "企业 SSO · OIDC"}</dd></div><div><dt>回答保护</dt><dd>文档权限 + 结论检查，始终启用</dd></div></dl></section>
    <div className="admin-savebar"><span role="status">{notice}</span>{error && <span className="error" role="alert">{error}</span>}<button className="btn primary" disabled={busy}>{busy ? "正在保存…" : "保存配置"}</button></div>
  </form>;
}

const sample = { documents: [{ id: "handbook-001", source: "upload", title: "员工手册", text: "报销申请需要附上发票，每月 25 日前提交。", acl: ["employees"] }], facts: [] };

export function KnowledgePanel() {
  const { data, error, load } = useResource<Knowledge>(api.knowledge);
  const [payload, setPayload] = useState(""), [busy, setBusy] = useState(false), [notice, setNotice] = useState(""), [failure, setFailure] = useState("");
  const [filter, setFilter] = useState("");
  return <main className="admin-page"><div className="admin-heading"><div><span className="overline">管理 / 资料</span><h1>知识资料</h1><p>导入内容和权限，再交给员工检索。</p></div><a className="btn" download="butler-import-example.json" href={`data:application/json;charset=utf-8,${encodeURIComponent(JSON.stringify(sample, null, 2))}`}>下载导入示例 ↓</a></div>
    {!data ? <ResourceState error={error} retry={load} /> : <>
      <div className="knowledge-stats"><span><b>{data.documents.length}</b> 份资料</span><span><b>{data.facts}</b> 条受限事实</span><span>版本 {data.revision}</span></div>
      <section className="admin-section"><div className="section-title"><h2>导入资料</h2><span className="quiet-tag">JSON · 同编号更新</span></div><form onSubmit={async (e) => { e.preventDefault(); setBusy(true); setFailure(""); setNotice(""); try { let parsed; try { parsed = JSON.parse(payload); } catch { throw new Error("JSON 格式不正确，请参照导入示例。"); } const r = await api.importKnowledge(parsed); setNotice(`已导入 ${r.documents} 份资料、${r.facts} 条受限事实`); setPayload(""); await load(); changed(); } catch (e) { setFailure(message(e)); } finally { setBusy(false); } }}><fieldset className="settings-fields" disabled={busy}><div className="import-toolbar"><label className="btn sm file-pick">选择 JSON 文件<input type="file" accept=".json,application/json" onChange={async (e) => { const file = e.target.files?.[0]; if (!file) return; if (file.size > 2_000_000) { setFailure("文件不能超过 2 MB。"); return; } try { setPayload(await file.text()); setFailure(""); } catch { setFailure("文件读取失败。"); } }} /></label><span>每份资料必须包含 acl 权限组。</span></div><label className="field"><span className="sr-only">资料 JSON</span><textarea name="knowledge-json" rows={6} value={payload} onChange={(e) => setPayload(e.target.value)} placeholder={'{"documents": [...], "facts": [...]}'} required /></label><div className="admin-savebar"><span role="status">{notice}</span>{failure && <span className="error" role="alert">{failure}</span>}<button className="btn primary" disabled={busy || !payload.trim()}>{busy ? "正在导入…" : "导入资料"}</button></div></fieldset></form></section>
      <section className="admin-section"><div className="section-title"><h2>资料目录</h2><label className="search-field"><span className="sr-only">搜索资料</span><input placeholder="搜索名称或来源" value={filter} onChange={(e) => setFilter(e.target.value)} /></label></div><div className="admin-table-wrap"><table className="admin-table"><thead><tr><th>资料名称</th><th>来源</th><th>可读权限组</th></tr></thead><tbody>{data.documents.filter((d) => `${d.title} ${d.source}`.toLowerCase().includes(filter.toLowerCase())).map((d) => <tr key={d.id}><td><b>{d.title}</b><small>{d.id}</small></td><td>{({ upload: "手动导入", drive: "Drive", slack: "Slack", jira: "Jira", confluence: "Confluence" } as Record<string, string>)[d.source] || d.source}</td><td><div className="group-chips">{d.acl.map((g) => <span className="chip" key={g}>{g}</span>)}</div></td></tr>)}</tbody></table>{!data.documents.length && <p className="empty">还没有资料。先导入一份文档。</p>}</div></section>
    </>}
  </main>;
}

const roles: Record<string, string> = { admin: "管理员", security: "安全团队", auditor: "审计员", employee: "员工", engineer: "工程师", contractor: "外包人员", pm: "项目经理" };

export function MembersPanel({ currentId }: { currentId: string }) {
  const { data, error, load } = useResource<Member[]>(api.members);
  const { data: status } = useResource<WorkspaceStatus>(api.status);
  return <main className="admin-page"><div className="admin-heading"><div><span className="overline">管理 / 身份</span><h1>成员与权限</h1><p>角色决定后台功能，权限组决定可读资料。</p></div></div>{status?.auth_mode === "local" && <CreateAccount onCreated={load} />}{!data ? <ResourceState error={error} retry={load} /> : <section className="admin-section"><div className="section-title"><h2>{data.length} 位成员</h2><span className="quiet-tag">{data.filter((m) => m.active).length} 个启用账号</span></div><div className="member-list">{data.map((member) => <MemberEditor key={member.id} member={member} self={member.id === currentId} />)}</div><p className="field-help">{status?.auth_mode === "local" ? "创建后分配角色与权限组。新账号默认没有资料权限。" : "新成员首次通过 SSO 登录后加入，默认没有资料权限。"}</p></section>}</main>;
}

function MemberEditor({ member, self }: { member: Member; self: boolean }) {
  const [role, setRole] = useState(member.role), [groups, setGroups] = useState(member.groups.join(", ")), [active, setActive] = useState(member.active);
  const [busy, setBusy] = useState(false), [notice, setNotice] = useState(""), [error, setError] = useState("");
  return <form className="member-editor" onSubmit={async (e) => { e.preventDefault(); setBusy(true); setNotice(""); setError(""); try { await api.saveMember(member.id, { role, active, groups: groups.split(/[,，]/).map((g) => g.trim()).filter(Boolean) }); setNotice("已保存"); changed(); } catch (e) { setError(message(e)); } finally { setBusy(false); } }}><div className="member-name"><span className="account-avatar">{member.name[0]}</span><div><b>{member.name}</b><small>{self ? "当前账号" : member.username || (member.id.length > 20 ? `${member.id.slice(0, 12)}…` : member.id)}</small></div></div><fieldset disabled={busy} className="member-controls"><label className="field">角色<select name={`role-${member.id}`} value={role} onChange={(e) => setRole(e.target.value)}>{Object.entries(roles).map(([key, label]) => <option value={key} key={key}>{label}</option>)}</select></label><label className="field">权限组<input name={`groups-${member.id}`} value={groups} onChange={(e) => setGroups(e.target.value)} placeholder="用逗号分隔" /></label><label className="member-toggle"><input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />启用</label><button className="btn sm" disabled={busy}>{busy ? "保存中…" : "保存"}</button></fieldset><span className="member-feedback" role="status">{notice}</span>{error && <p className="error" role="alert">{error}</p>}{member.username && !self && <PasswordReset id={member.id} />}</form>;
}

function CreateAccount({ onCreated }: { onCreated: () => Promise<void> }) {
  const [busy, setBusy] = useState(false), [notice, setNotice] = useState(""), [error, setError] = useState("");
  return <section className="admin-section"><div className="section-title"><h2>创建账号</h2></div><form onSubmit={async (e) => {
    e.preventDefault(); const form = e.currentTarget, values = new FormData(form); setBusy(true); setError(""); setNotice("");
    try { await api.createMember({ username: String(values.get("username")), name: String(values.get("name")), password: String(values.get("password")) }); form.reset(); setNotice("账号已创建，请在下方分配权限。"); await onCreated(); changed(); } catch (e) { setError(message(e)); } finally { setBusy(false); }
  }}><fieldset className="settings-fields create-account-fields" disabled={busy}>
    <label className="field">姓名<input name="name" maxLength={100} required /></label>
    <label className="field">账号<input name="username" autoComplete="off" autoCapitalize="none" spellCheck={false} pattern="[a-zA-Z0-9][a-zA-Z0-9_.@\\-]{2,79}" minLength={3} maxLength={80} required /></label>
    <label className="field">初始密码<input name="password" type="password" autoComplete="new-password" minLength={15} maxLength={128} required placeholder="至少 15 个字符" /></label>
    <button className="btn primary" disabled={busy}>{busy ? "正在创建…" : "创建账号"}</button>
  </fieldset><div className="admin-savebar"><span role="status">{notice}</span>{error && <span className="error" role="alert">{error}</span>}</div></form></section>;
}

function PasswordReset({ id }: { id: string }) {
  const [password, setPassword] = useState(""), [busy, setBusy] = useState(false), [notice, setNotice] = useState("");
  return <details className="member-password-reset"><summary>重置密码</summary><div className="password-reset-fields"><label className="field">新密码<input type="password" autoComplete="new-password" value={password} minLength={15} maxLength={128} onChange={(e) => setPassword(e.target.value)} /></label><button type="button" className="btn sm" disabled={busy || password.length < 15} onClick={async () => { setBusy(true); setNotice(""); try { await api.resetPassword(id, password); setPassword(""); setNotice("密码已重置，原有登录已失效。"); } catch (e) { setNotice(message(e)); } finally { setBusy(false); } }}>{busy ? "重置中…" : "确认重置"}</button></div><p className="field-help" role="status">{notice || "设置新密码后，该账号需要重新登录。"}</p></details>;
}
