import Link from "next/link";
import Brand from "@/components/Brand";
import Demo from "@/components/Demo";
import { enterprise } from "@/lib/deployment";
import { publicDemoEnabled } from "@/lib/public-demo";
export const dynamic = "force-dynamic";

export default function Home() {
  return <div className="public-site">
    <header className="public-header"><Brand /><nav aria-label="首页导航">{publicDemoEnabled && <><a href="#demo">现场演示</a><a href="#results">评测结果</a></>}</nav><Link href="/login" className="header-login">登录工作台 <span aria-hidden="true">↗</span></Link></header>
    <main>
      <section className="intro">
        <div className="intro-heading"><div className="overline">BUTLER / 企业知识助手</div><h1><span className="hero-line"><span>资料能看。</span></span><span className="hero-line accent"><span>结论呢？</span></span></h1></div>
        <div className="intro-description"><p>合同暂停，预算归零。<br />AI 拼出的裁撤计划，你有权知道吗？</p><p>Butler 在答案发出前，再查一次权限。</p>{publicDemoEnabled && <a href="#demo" className="text-link">看它怎么做 <span aria-hidden="true">↓</span></a>}</div>
      </section>
      {publicDemoEnabled && <Demo />}
      <section className="workspace-invite"><div><span className="overline">工作台</span><h2>{enterprise ? "带着身份，进入工作区。" : "换个身份，继续问。"}</h2><p>{enterprise ? "用公司的统一账号登录。" : "选一个账号，看看你能知道什么。"}</p></div><Link href="/login" className="btn primary">进入工作台 <span aria-hidden="true">↗</span></Link></section>
    </main>
    <footer className="public-footer"><Brand /><span>Tencent Cloud AI CAN DO IT · Aspire</span><span>Butler · 2026</span></footer>
  </div>;
}
