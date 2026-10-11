# Butler

连“结论”也管的企业 AI 助手。Tencent Cloud AI CAN DO IT Hackathon · Aspire 赛道。

设计目标：来源权限约束、结论级防护与可独立验证的审计。当前版本仍是应用原型，尚未完成平台接入、切块、向量化和真实模型验收。

## 当前实现状态

| 能力 | 当前状态 |
| --- | --- |
| 登录、成员、配置、资料导入、会话 | 已有持久化应用流程；账号密码及可选 OIDC |
| 文档权限 | 本地组与 ACL 过滤；没有平台权限展开或实时平台复核 |
| 切块、embedding、向量检索 | 未实现；当前是整篇文档的字符二元组打分 |
| 平台同步、Celery、雷达 | 未实现；适配器只有协议与假数据加载器 |
| 生成与结论检查 | 企业接口已写，真实模型待联调；引用验证、降级复核、事实版本存在缺口 |
| 审计 | 库内哈希链；没有数字签名与库外检查点 |
| 红队 | 规则生成器与关键词判官的30+30离线用例；不是实模安全结果 |
| 部署 | 企业 Compose 文件已有；Docker/PostgreSQL 实际部署未验收 |

逐项证据、已复现缺陷及建设顺序见[实现核查与优化顺序](docs/implementation-audit.md)。原始长篇方案移至[设计提案](docs/design-proposal.md)，其中的目录与功能描述表示目标，不代表已完成。

团队开发按[两人分工与接口交接](docs/WORKSPLIT.md)推进：A 负责数据、检索与同步，B 负责回答、安全、审计与应用对接。

## 目录
- `services/api` FastAPI 后端（核心逻辑都在 `butler/`）
- `apps/web` Next.js 前端：演示首页、账号密码登录（可选 OIDC）、工作区概览、问答与会话、知识资料、成员权限、配置中心、审计
- `seed/tidepool` 虚构公司 Tidepool Pay 的演示数据 + 马赛克攻击评测用例
- `docs/adr` 设计取舍记录

## 快速开始
```bash
cd services/api
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
pytest -q                       # 权限 / 审计链 / 马赛克评测
uvicorn butler.main:app --reload --port 8000

cd apps/web                     # 另开终端，从项目根目录执行
npm install && npm run dev      # http://localhost:3000（可用 BUTLER_API 指定后端）
```

前端入口：`/` 公开演示；`/login` 登录；`/workspace/overview` 工作区概览；`/workspace` 问答与持久化会话；`/workspace/knowledge` 资料导入；`/workspace/members` 成员权限；`/workspace/settings` 配置中心；`/workspace/audit` 审计。管理页仅 admin / security 可访问，审计另向 auditor 开放。

首页用同一张 3D 桌面串起“查资料 → 生成回答 → 检查权限 → 发出答案”，每步可重播，支持身份切换、单轮、多轮和正常问题；小屏幕与 WebGL 不可用时使用可读步骤动画。

默认 `BUTLER_MODE=demo`：后台配置、资料、会话与审计保存在 `.runtime/workspace-demo.sqlite`，公开演示仍使用独立内存数据。登录页支持账号密码，也可展开「体验演示账号」；使用 Sara 在「成员与权限」创建本地账号。可用 `BUTLER_DEMO_DATABASE_URL` 指定演示数据库。企业模式使用 PostgreSQL 和内部服务凭据，默认账号密码登录：首次设置 `BUTLER_ADMIN_USERNAME` 与 `BUTLER_ADMIN_PASSWORD`，OIDC 可按需开启。企业模式不加载演示账号或资料；部署文件另启隔离的演示服务供首页使用。

**企业部署和剩余生产验收项见 [企业工作区部署](docs/enterprise-deployment.md)。** 部署文件为 `infra/compose.enterprise.yml`。密钥由服务端环境管理，后台只保存非敏感运行配置。当前资料接入支持带 ACL 的 JSON 导入，平台自动同步尚未实现。

演示接口：`POST /ask` · `POST /compare` · `GET /sources` · `GET /audit` · `GET /audit/verify` · `GET /eval` · `GET /eval/cases`。企业 API 关闭这些旧入口，使用服务端绑定身份的 `/workspace/*` 接口；浏览器通过 Next.js `/api/workspace/*` 访问。`/audit/tamper`、`/demo/reset` 仅供隔离的演示数据使用。

现有规则评测输出：30 组攻击 + 30 个正常问题，无权限 RAG 泄露100%，文档级 RAG 90%，Butler 0%，误拦0%。这些数字仅适用于合成规则用例；本次还发现跨轮评分漏算，不能作为实模安全结论，详见[核查报告](docs/implementation-audit.md)。

真实接入优先选择已有测试空间和账号的平台，完整验收内容同步、权限和撤权后，再扩展到其余平台。
