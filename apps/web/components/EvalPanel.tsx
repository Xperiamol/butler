"use client";
import { useEffect, useMemo, useState } from "react";
import { workspaceApi as api, FACT_LABEL, type Cases, type EvalReport } from "@/lib/api";

const MODES = [
  { key: "none", name: "无权限 RAG", color: "var(--series-none)" },
  { key: "doc", name: "文档级权限 RAG", color: "var(--series-doc)" },
  { key: "butler", name: "Butler", color: "var(--series-butler)" },
] as const;

const pct = (x: number) => `${Math.round(x * 100)}%`;

function Bars({ r, metric, count, total }: { r: EvalReport; metric: "leak_rate" | "false_block_rate"; count: "leaks" | "false_blocks"; total: "attacks" | "controls" }) {
  const [grown, setGrown] = useState(false);
  useEffect(() => { const t = setTimeout(() => setGrown(true), 50); return () => clearTimeout(t); }, []);
  return (
    <div>
      {MODES.map((m) => {
        const d = r[m.key];
        return (
          <div className="hbar" key={m.key}>
            <span className="name">{m.name}</span>
            <span className="track">
              <span className="fill" style={{ width: grown ? `${d[metric] * 100}%` : 0, background: m.color }} />
            </span>
            <span className="val">{pct(d[metric])}</span>
            <span className="tip">{m.name}：{d[count]}/{d[total]}</span>
          </div>
        );
      })}
    </div>
  );
}

export default function EvalPanel() {
  const [r, setR] = useState<EvalReport | null>(null);
  const [cases, setCases] = useState<Cases | null>(null);
  const [tab, setTab] = useState<"attack" | "control">("attack");
  const [err, setErr] = useState("");
  useEffect(() => {
    Promise.all([api.eval(), api.cases()]).then(([report, cases]) => { setR(report); setCases(cases); })
      .catch(() => setErr("暂时无法读取评测结果，请刷新重试。登录过期时，请重新登录。"));
  }, []);

  const rows = useMemo(() => {
    if (!r || !cases) return [];
    const q = new Map<string, string>();
    cases.attacks.forEach((c) => q.set(c.id, (c.turns ?? [c.question!]).join(" → ")));
    cases.controls.forEach((c) => q.set(c.id, c.question));
    return r.butler.cases
      .filter((c) => c.kind === tab)
      .map((c, i) => ({ ...c, q: q.get(c.id) ?? "", doc: r.doc.cases.find((x) => x.id === c.id)!, none: r.none.cases.find((x) => x.id === c.id)! , i }));
  }, [r, cases, tab]);

  const cell = (c: { kind: string; leaked?: boolean; degraded: boolean; answered?: boolean }) =>
    c.kind === "attack" ? (
      c.leaked ? <span className="res leak">✕ 泄露</span> : c.degraded ? <span className="res blocked">已拦下</span> : <span className="res safe">✓ 未拼出</span>
    ) : c.degraded ? (
      <span className="res blocked">误拦</span>
    ) : c.answered ? (
      <span className="res safe">✓ 正常作答</span>
    ) : (
      <span className="res leak">✕ 缺内容</span>
    );

  return (
    <main className="page">
      <div className="page-head">
        <div>
          <span className="eyebrow">安全 / 评测</span>
          <h1 className="title">
            泄露率 {r ? pct(r.doc.leak_rate) : "—"} → <span style={{ color: "var(--green)" }}>{r ? pct(r.butler.leak_rate) : "—"}</span>
          </h1>
          <p className="sub">30 组攻击问题，30 个正常问题。查看三种系统的泄露与误拦情况。</p>
        </div>
      </div>
      {err && <p className="error" role="alert">{err}</p>}
      {r && (
        <>
          <div className="note">
            当前为离线规则评测（{r.judge}）。生成器与检查器使用预设规则，这些结果不代表真实模型的防护效果。
          </div>
          <div className="legend">
            {MODES.map((m) => <span key={m.key}><i style={{ background: m.color }} />{m.name}</span>)}
          </div>
          <div className="viz-grid">
            <div className="panel viz">
              <h3>泄露率</h3>
              <div className="cap">{r.butler.attacks} 组攻击中，回答触及受限结论的比例（越低越好）</div>
              <Bars r={r} metric="leak_rate" count="leaks" total="attacks" />
            </div>
            <div className="panel viz">
              <h3>误拦率</h3>
              <div className="cap">{r.butler.controls} 个正常问题中，被降级的比例（越低越好）</div>
              <Bars r={r} metric="false_block_rate" count="false_blocks" total="controls" />
            </div>
          </div>

          <div className="panel viz">
            <div className="tabs">
              <button className={tab === "attack" ? "on" : ""} onClick={() => setTab("attack")}>攻击组 · {r.butler.attacks}</button>
              <button className={tab === "control" ? "on" : ""} onClick={() => setTab("control")}>对照组 · {r.butler.controls}</button>
            </div>
            <div className="table-wrap">
              <table className="cases">
                <thead>
                  <tr>
                    <th>ID</th><th>身份</th>{tab === "attack" && <th>目标结论</th>}<th>问题</th><th>无权限 RAG</th><th>文档级 RAG</th><th>Butler</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((c) => (
                    <tr key={c.id}>
                      <td className="mono">{c.id}</td>
                      <td>{c.identity}</td>
                      {tab === "attack" && <td>{FACT_LABEL[c.fact!] ?? c.fact}</td>}
                      <td style={{ color: "var(--text-2)" }}>{c.q}{(c.turns ?? 1) > 1 && <span className="chip" style={{ marginLeft: 6 }}>{c.turns} 轮</span>}</td>
                      <td>{cell(c.none)}</td>
                      <td>{cell(c.doc)}</td>
                      <td>{cell(c)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </main>
  );
}
