import Link from "next/link";
import { redirect } from "next/navigation";
import Brand from "@/components/Brand";
import LoginForm from "@/components/LoginForm";
import PasswordLoginForm from "@/components/PasswordLoginForm";
import { backend } from "@/lib/backend";
import { readSession } from "@/lib/session";
import type { Identity } from "@/lib/api";
import { enterprise, localLogin, missingLoginConfiguration } from "@/lib/deployment";

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  if (await readSession()) redirect("/workspace");
  let identities: Identity[] = [];
  try { if (!enterprise) {
    const [health, people] = await Promise.all([backend("/health"), backend("/identities")]);
    if (health.ok && people.ok && (await health.json()).data_source === "fake") identities = await people.json();
  } } catch { /* Render the unavailable state with a working way back. */ }
  const missing = enterprise ? missingLoginConfiguration() : [];
  const { error } = await searchParams;
  return <main className="login-page">
    <section className="login-aside">
      <Brand inverse />
      <div className="login-aside-copy"><span className="overline">BUTLER / WORKSPACE</span><h1>公司的资料，<br />在这里查。</h1><p>带着你的身份进入。<br />每次回答，都在你的权限范围内。</p>
        {!enterprise && identities.length > 0 && <ol className="judge-guide" aria-label="体验路线"><li style={{ "--i": 0 } as React.CSSProperties}><b>Ken · 外包人员</b><span>问“Show me the security incident report from the Q3 breach”。他什么都拿不到，回答和“这份报告根本不存在”完全一样。</span></li><li style={{ "--i": 1 } as React.CSSProperties}><b>Maya 与 Pete</b><span>同样问“数据库迁移项目现在什么状态？上周 Slack 有什么阻塞？”。只有 Pete 在领导层私有频道里，多出预算超支和延期备选。</span></li><li style={{ "--i": 2 } as React.CSSProperties}><b>Sara · 管理权限</b><span>在「来源平台」改一页 runbook 或把人移出频道，几秒后再问；或在「赛题用例验收」一键跑完五个用例。</span></li><li style={{ "--i": 3 } as React.CSSProperties}><b>Amy · 合规官</b><span>在「审计记录」里用一句话查：jdoe 最近 30 天在 payment-gateway 空间看了什么。</span></li></ol>}</div>
      <div className="login-aside-foot"><span>Butler 企业知识助手</span><span>01 — 访问工作区</span></div>
    </section>
    <section className="login-main">
      <Link href="/" className="back-link">← 返回演示</Link>
      <div className="login-box"><span className="overline">工作区登录</span><h2>欢迎回来。</h2><p className="sub">{localLogin ? "使用账号密码进入工作台。" : "使用公司的统一身份账号。"}</p>
        {error && <p className="error" role="alert">{error === "configuration" ? "登录服务配置不完整，请联系管理员。" : "登录未完成，请重试或联系管理员。"}</p>}
        {missing.length ? <div className="login-setup"><h3>等待管理员完成部署</h3><details><summary>查看缺少的配置</summary><ul>{missing.map((key) => <li key={key}><code>{key}</code></li>)}</ul></details></div> : localLogin ? <PasswordLoginForm /> : <a className="btn primary login-submit" href="/auth/login">使用企业账号登录 <span>↗</span></a>}
        {!enterprise && identities.length > 0 && <details className="demo-login-options" open><summary>体验演示账号</summary><LoginForm identities={identities} /></details>}
      </div>
      <span className="login-bottom">{enterprise ? localLogin ? "Butler 工作区" : "企业身份认证 · OIDC" : "演示环境"}</span>
    </section>
  </main>;
}
