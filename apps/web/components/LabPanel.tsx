"use client";
import { useRef, useState } from "react";
import { useEffect } from "react";
import { api, FACT_LABEL, workspaceApi, type AuditRow, type Compare, type ScanResult, type TamperResult } from "@/lib/api";
import { PEOPLE, SCAN_PRESETS, SCENARIOS } from "@/lib/scenarios";
import AnswerText from "./AnswerText";

type Round = { question: string; result: Compare };
const leaked = (side: { text: string }) => side.text.split("\n").some((l) => l.startsWith("综合判断"));

export default function LabPanel() {
  return <main className="admin-page lab-page">
    <div className="admin-heading"><div><span className="overline">体验 / 攻防演示台</span><h1>自己动手，攻一次试试。</h1><p>下面两个台子都连着真实的守卫流程：一个演示拼图攻击，一个演示藏在资料里的提示注入。</p></div></div>
    <AttackBench />
    <ScanBench />
    <TamperBench />
  </main>;
}

function AttackBench() {
  const [scenario, setScenario] = useState(0), [person, setPerson] = useState(0);
  const [rounds, setRounds] = useState<Round[]>([]);
  const [running, setRunning] = useState(false), [error, setError] = useState(""), [finished, setFinished] = useState(false);
  const session = useRef("");
  const sc = SCENARIOS[scenario], who = PEOPLE[person];
  const run = async () => {
    if (running) return;
    setRunning(true); setRounds([]); setError(""); setFinished(false); session.current = crypto.randomUUID();
    try {
      for (const question of sc.turns) {
        const result = await api.compare(who.id, question, session.current);
        setRounds((r) => [...r, { question, result }]);
        await new Promise((resolve) => setTimeout(resolve, 650));
      }
      setFinished(true);
    } catch { setError("暂时连不上服务，请重试。"); }
    finally { setRunning(false); }
  };
  const plainLeaks = rounds.filter((r) => leaked(r.result.baseline)).length, stopped = rounds.filter((r) => r.result.butler.degraded).length;
  return <section className="lab-bench">
    <div className="lab-head"><span className="demo-label">01 / 拼图攻击</span><h2>同一组问题，两个助手。</h2></div>
    <div className="lab-controls">
      <div className="scenario-tabs" role="group" aria-label="攻击剧本">{SCENARIOS.map((s, i) => <button key={s.name} className={scenario === i ? "active" : ""} aria-pressed={scenario === i} disabled={running} onClick={() => { setScenario(i); setRounds([]); setFinished(false); }}><span>{s.name}</span></button>)}</div>
      <label className="demo-reader">提问人<select value={person} disabled={running} onChange={(e) => { setPerson(Number(e.target.value)); setRounds([]); setFinished(false); }}>{PEOPLE.map((p, i) => <option value={i} key={p.id}>{p.name} · {p.role}</option>)}</select></label>
      <button className="btn primary" disabled={running} onClick={run}>{running ? "攻击进行中…" : rounds.length ? "再来一次" : "发起攻击"}<span aria-hidden="true">→</span></button>
    </div>
    <p className="lab-blurb">{sc.blurb}</p>
    {error && <p className="error" role="alert">{error}</p>}
    <div className="lab-rounds">{rounds.map((r, i) => { const bad = leaked(r.result.baseline), cut = r.result.butler.degraded; return <article className="lab-round" key={i} style={{ "--i": 0 } as React.CSSProperties}>
      <header><span>第 {i + 1} 轮 · {who.name}</span><p>{r.question}</p></header>
      <div className="lab-sides">
        <div className={`lab-side ${bad ? "is-leak" : ""}`}><div className="lab-side-head"><b>普通助手</b><span className={`badge ${bad ? "stop" : "ok"}`}>{bad ? "拼出了结论" : "照常回答"}</span></div><AnswerText text={r.result.baseline.text} citations={r.result.baseline.citations} highlight typing /></div>
        <div className={`lab-side guarded ${cut ? "is-cut" : ""}`}><div className="lab-side-head"><b>Butler</b><span className={`badge ${cut ? "warn" : "ok"}`}>{cut ? `拦截 · ${r.result.butler.blocked_facts.map((f) => FACT_LABEL[f] ?? f).join("、") || "受限结论"}` : "放行"}</span></div><AnswerText text={r.result.butler.text} citations={r.result.butler.citations} typing /><small className="lab-ms">检查 {r.result.butler.guard_ms.toFixed(1)} ms</small></div>
      </div></article>; })}</div>
    {finished && <div className="lab-verdict" role="status"><div><strong>{plainLeaks}</strong><span>轮里普通助手拼出了结论</span></div><div><strong>{stopped}</strong><span>轮里 Butler 拦住了越权推断</span></div><div><strong>{rounds.length - stopped}</strong><span>轮正常放行</span></div></div>}
  </section>;
}

function ScanBench() {
  const [text, setText] = useState(SCAN_PRESETS[1].text), [result, setResult] = useState<ScanResult | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const scan = async () => { setBusy(true); setError(""); try { setResult(await workspaceApi.scan(text)); } catch (e) { setError(e instanceof Error ? e.message : "扫描未完成。"); } finally { setBusy(false); } };
  return <section className="lab-bench">
    <div className="lab-head"><span className="demo-label">02 / 提示注入扫描</span><h2>有人把指令藏进一份普通资料。</h2></div>
    <p className="lab-blurb">入库前先扫一遍：命中的资料被隔离，不会被任何人检索到。这里只扫描，不会写入资料。</p>
    <div className="scan-presets">{SCAN_PRESETS.map((p) => <button key={p.name} className={text === p.text ? "active" : ""} onClick={() => { setText(p.text); setResult(null); }}>{p.name}</button>)}</div>
    <div className="scan-grid">
      <div className="scan-input"><textarea value={text} onChange={(e) => { setText(e.target.value); setResult(null); }} rows={7} maxLength={20000} aria-label="要扫描的资料内容" /><button className="btn primary" disabled={busy || !text.trim()} onClick={scan}>{busy ? "扫描中…" : "扫描这份资料"}<span aria-hidden="true">→</span></button></div>
      <div className={`scan-result ${result ? result.flagged ? "is-flagged" : "is-clean" : ""}`} aria-live="polite">
        {!result ? <p className="scan-idle">选一个样例，或者粘贴你自己的文字。</p> : <>
          <div className="scan-stamp">{result.flagged ? "已隔离" : "正常入库"}</div>
          <div className="scan-meter"><span>风险分</span><div><i style={{ transform: `scaleX(${result.score})` }} /></div><b>{result.score.toFixed(2)}</b></div>
          {result.rules.length > 0 && <div className="scan-rules">{result.rules.map((r) => <span key={r}>{r}</span>)}</div>}
          <p className="scan-note">{result.flagged ? "这份资料不会进入检索，也不会出现在任何人的回答里。" : "没有发现注入特征。含“请忽略…”这类字样的正常通知不会被误伤。"}</p>
          {result.neutralized && !result.flagged && <small>已拆掉其中的角色标记和定界符后再送入生成。</small>}
        </>}
        {error && <p className="error" role="alert">{error}</p>}
      </div>
    </div>
  </section>;
}

const EVENT: Record<string, string> = { ask: "问答", "approval.requested": "申请授权", "approval.decided": "审批", "audit.viewed": "查看审计", "audit.exported": "导出审计", "settings.updated": "改配置" };
function TamperBench() {
  const [rows, setRows] = useState<AuditRow[] | null>(null), [denied, setDenied] = useState(false);
  const [picked, setPicked] = useState<number | null>(null), [result, setResult] = useState<TamperResult | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState("");
  useEffect(() => { workspaceApi.audit().then((a) => setRows(a.entries.slice(-8))).catch(() => setDenied(true)); }, []);
  const run = async (relink: boolean) => { if (picked === null) return; setBusy(true); setError(""); try { setResult(await workspaceApi.tamper(picked, relink)); } catch (e) { setError(e instanceof Error ? e.message : "演示未完成。"); } finally { setBusy(false); } };
  const state = (index: number) => !result ? "ok" : result.relinked ? index >= result.index ? "forged" : "ok" : result.first_bad_index !== null && index >= result.first_bad_index ? "broken" : "ok";
  return <section className="lab-bench">
    <div className="lab-head"><span className="demo-label">03 / 审计防篡改</span><h2>有数据库写权限的人，能悄悄改记录吗？</h2></div>
    <p className="lab-blurb">审计是一条哈希链：每条记录带着上一条的哈希。选一条改掉它——只在内存里改，不会动真实的审计记录。</p>
    {denied ? <p className="lab-blurb">这个台子读取真实审计记录，需要审计权限。换 Amy 或 Sara 登录试试。</p> : !rows ? <p className="admin-loading" role="status"><span className="spinner" />正在读取…</p> : rows.length < 2 ? <p className="lab-blurb">审计记录还太少。先去知识问答里问几个问题。</p> : <>
      <div className="chain-strip">{rows.map((r, i) => { const st = state(r.index); return <button key={r.index} className={`chain-block is-${st} ${picked === r.index ? "picked" : ""}`} style={{ "--i": i } as React.CSSProperties} onClick={() => { setPicked(r.index); setResult(null); }} aria-pressed={picked === r.index}>
        <span className="chain-no">#{r.index}</span><b>{EVENT[r.payload.event ?? "ask"] ?? r.payload.event}</b><small>{r.payload.user}</small><code>{r.hash.slice(0, 10)}</code><i className="chain-link" aria-hidden="true" />
      </button>; })}
        <div className={`chain-seal ${result ? result.relinked ? "is-bad" : "is-skip" : "is-ok"}`}><span>签名检查点</span><b>{result ? result.relinked ? "对不上" : "—" : "存放在库外"}</b></div></div>
      <div className="tamper-actions"><button className="btn sm" disabled={busy || picked === null} onClick={() => run(false)}>① 改这条记录</button><button className="btn sm primary" disabled={busy || picked === null} onClick={() => run(true)}>② 改完，再把后面的哈希整条重算 →</button>{result && <button className="btn sm" onClick={() => setResult(null)}>还原</button>}</div>
      {picked === null && <p className="lab-blurb">先点一个块。</p>}
      {error && <p className="error" role="alert">{error}</p>}
      {result && <div className={`tamper-verdict ${result.relinked ? "is-bad" : "is-bad"}`} role="status">{!result.relinked ? <><b>校验失败：链在第 {result.first_bad_index} 条断开</b><span>这条记录的哈希已经对不上，后面所有记录的“上一条哈希”也跟着失效。</span></> : <><b>链看起来是完好的，但检查点对不上</b><span>攻击者把后面的哈希全部重算了一遍，链自洽了。可是链头的签名检查点存放在库外、用私钥签名，他签不出新的，所以仍然被发现：{result.checkpoint_ok ? "" : "校验失败。"}</span></>}<small>{result.relinked ? `这条记录的哈希：${result.before}… → ${result.after}…（后面的也跟着重算了）` : `这条记录内容改了，但保存的哈希还是 ${result.before}…，重新计算时对不上。`}</small></div>}
    </>}
  </section>;
}
