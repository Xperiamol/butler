import Link from "next/link";
import Brand from "@/components/Brand";
import Demo from "@/components/Demo";
import HeroField from "@/components/HeroField";
import Preloader from "@/components/Preloader";
import { CountUp, Reveal } from "@/components/motion";
import { enterprise } from "@/lib/deployment";
import { publicDemoEnabled } from "@/lib/public-demo";
export const dynamic = "force-dynamic";

const SOURCES = ["Confluence", "Jira", "Slack", "Google Drive", "GitHub", "手动导入"];
const LAYERS = [
  { n: "01", title: "身份与权限", text: "检索前先按来源里的权限过滤。生成模型从头到尾看不到你无权读的资料。" },
  { n: "02", title: "会话账本", text: "记住这个会话已经放行过什么，分几轮套问也要把前面的算进来。" },
  { n: "03", title: "前提闭包", text: "登记一条结论依赖哪几份资料。累计拿到的资料凑齐了，就停在那一步，不靠措辞，不调用模型。" },
  { n: "04", title: "结论判官", text: "模型再读一遍答案，看它有没有说出受限结论。说出了就收窄，或转成“需要授权”。" },
  { n: "05", title: "审计与审批", text: "每次判定进哈希链，改一条就验不过。批准是限时的，批准人也留痕，不能批自己。" },
];

export default function Home() {
  return <div className="public-site">
    <Preloader />
    <header className="public-header"><Brand /><nav aria-label="首页导航"><a href="#how">原理</a>{publicDemoEnabled && <><a href="#demo">现场演示</a><a href="#results">评测结果</a></>}</nav><Link href="/login" className="header-login">登录工作台 <span aria-hidden="true">↗</span></Link></header>
    <main>
      <section className="intro hero">
        <HeroField />
        <div className="intro-heading"><div className="overline">BUTLER / 企业知识助手</div><h1><span className="hero-line"><span>资料能看。</span></span><span className="hero-line accent"><span>结论呢？</span></span></h1></div>
        <div className="intro-description"><p>合同暂停，预算归零。<br />AI 拼出的裁撤计划，你有权知道吗？</p><p>Butler 在答案发出前，再查一次权限。</p>{publicDemoEnabled && <a href="#demo" className="text-link">看它怎么做 <span aria-hidden="true">↓</span></a>}</div>
      </section>
      <Reveal className="hero-stats">
        <div><strong><CountUp value={27} suffix="%" /><i aria-hidden="true">→</i><CountUp value={0} suffix="%" /></strong><span>只查文档权限 → 用 Butler，受限结论泄露率</span></div>
        <div><strong><CountUp value={94} suffix="%" /></strong><span>代价：对话被拦下过至少一次（其中约三成是误伤）</span></div>
        <div><strong><CountUp value={5} /></strong><span>层检查：权限、账本、前提、判官、审计</span></div>
        <p>真实模型 gpt-5.4-mini · 33 条留出测试链。评分器与判官是同一个模型，样本由模型标注，结论仅供参考，详见评测文档。</p>
      </Reveal>
      <div className="marquee" aria-hidden="true"><div className="marquee-track">{[...SOURCES, ...SOURCES, ...SOURCES, ...SOURCES].map((s, i) => <span key={i}>{s}<i /></span>)}</div></div>
      <section className="how" id="how">
        <Reveal className="how-head"><span className="demo-label">00 / 原理</span><h2>回答发出前，要过五道关。</h2><p>权限回答的是“能不能读这一份”。Butler 多问一句：你累计拿到的这些，拼起来是不是你不该知道的。</p></Reveal>
        <div className="how-grid">{LAYERS.map((l, i) => <Reveal key={l.n} delay={i * 90} className="how-card"><div data-tilt><span>{l.n}</span><h3>{l.title}</h3><p>{l.text}</p><i aria-hidden="true" /></div></Reveal>)}</div>
      </section>
      {publicDemoEnabled && <Demo />}
      <Reveal as="section" className="workspace-invite"><div><span className="overline">工作台</span><h2>{enterprise ? "带着身份，进入工作区。" : "换个身份，继续问。"}</h2><p>{enterprise ? "用公司的统一账号登录。" : "选一个账号，看看你能知道什么。审批、审计、攻防演示台都在里面。"}</p></div><Link href="/login" className="btn primary">进入工作台 <span aria-hidden="true">↗</span></Link></Reveal>
    </main>
    <footer className="public-footer"><Brand /><span>Tencent Cloud AI CAN DO IT · Aspire</span><span>Butler · 2026</span></footer>
  </div>;
}
