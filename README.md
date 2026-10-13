# Butler

连“结论”也管的企业 AI 助手。Tencent Cloud AI CAN DO IT Hackathon · Aspire 赛道。

设计目标：来源权限约束、结论级防护与可独立验证的审计。当前版本的数据管线（切块、混合检索、同步、注入检测、前提发现、语义判官、签名审计）已实现并有测试与评测；**尚未完成：托管平台接入、真实大模型与真实多语言嵌入的验收、前端对应界面。**所有“泄露”数字来自离线模拟生成器，见[独立评测](docs/independent-eval.md)。

## 当前实现状态

| 能力 | 当前状态 |
| --- | --- |
| 登录、成员、配置、资料导入、会话 | 已有持久化应用流程；账号密码及可选 OIDC |
| 文档权限 | 本地组与 ACL 过滤；没有平台权限展开或实时平台复核 |
| 切块、embedding、混合检索 | 已实现：结构化切块（带原文位置）、哈希嵌入 + 远程嵌入接口、权限先行的 BM25 + 向量 RRF 融合；**没有真实语义嵌入的评测**，见[检索评测](docs/retrieval-eval.md) |
| 平台同步 | 已实现 Git 仓库连接器（真实数据源）+ 数据库队列（幂等、乱序、重试、死信、对账、权限新鲜期）+ worker；**没有接入 Slack/Confluence/Jira/Drive**，Celery 仅有未测试的适配层，见[同步说明](docs/sync.md)。雷达未做 |
| 提示注入 | 规则 + 训练的线性分类器（按句子打分），入库隔离、使用前再扫、输出链接核对，见[说明](docs/prompt-injection.md) |
| 前提自动发现 | 训练的小模型自动找出能拼出机密的资料（v2 加入中文语义特征和 quorum 规则），见[说明](docs/premise-discovery.md) |
| 语义判官 | 训练的线性模型，用中文词向量的软对齐特征判断回答是否“说出”受限结论，补关键词判官的改述盲区；依赖约 570 MB 的可选词向量，见[独立评测](docs/independent-eval.md) |
| 独立评测 | 手写评测集 `seed/eval/`（开发/测试切分，测试集只能跑一次）与结果见[独立评测](docs/independent-eval.md) |
| 生成与结论检查 | 企业接口已写，真实模型待联调。已有：引用核验（编号与数字）、降级文本复核、事实绑定正文版本、依赖闭包检查、级联候选筛选（超预算拒答） |
| 审计 | 库内哈希链 + Ed25519 签名检查点导出 + 独立验证命令行（`python -m butler.audit.verify_cli`）；失败请求、审计查看均留痕 |
| 红队与评测 | 30+30 离线用例；合成基准（真实手册背景 + 种子生成拼图链，独立评分器，见[基准说明](docs/benchmark.md)）；手写独立评测集（见上）。生成器均是离线模拟，不是实模结果 |
| 存储 | 业务对象拆成带索引的表（文档、事实、成员、会话、审计、块、向量、同步任务），旧数据启动时幂等迁移 |
| 部署 | 企业 Compose 文件已有（含 worker）；Docker/PostgreSQL 实际部署未验收 |

逐项证据、已复现缺陷及建设顺序见[实现核查与优化顺序](docs/implementation-audit.md)。原始长篇方案移至[设计提案](docs/design-proposal.md)，其中的目录与功能描述表示目标，不代表已完成。

团队开发按[两人分工与接口交接](docs/WORKSPLIT.md)推进：A 负责数据、检索与同步，B 负责回答、安全、审计与应用对接。

## 目录
- `services/api` FastAPI 后端（核心逻辑都在 `butler/`）
- `apps/web` Next.js 前端：演示首页、账号密码登录（可选 OIDC）、工作区概览、问答与会话、知识资料、成员权限、配置中心、审计
- `seed/tidepool` 虚构公司 Tidepool Pay 的演示数据 + 马赛克攻击评测用例
- `seed/eval` 手写独立评测集（开发/测试切分）
- `docs/adr` 设计取舍记录；`docs/*.md` 评测与设计说明

## 快速开始
```bash
cd services/api
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
pytest -q                       # 权限 / 审计链 / 检索 / 同步 / 注入 / 评测程序
uvicorn butler.main:app --reload --port 8000

cd apps/web                     # 另开终端，从项目根目录执行
npm install && npm run dev      # http://localhost:3000（可用 BUTLER_API 指定后端）
```

可选的中文语义能力（语义判官、前提发现 v2、跨语言检索，约 570 MB 词向量）：`pip install -r requirements-semantic.txt`；缺失时自动退回关键词/词法路径。训练脚本需要 `requirements-train.txt`。

评测：`python scripts/fetch_eval_handbook.py` 下载固定版本手册，然后 `python -m butler.redteam.eval_set --split dev`（测试集只能跑一次，见[独立评测](docs/independent-eval.md)）。同步 worker：`python -m butler.workers.run`。

前端入口：`/` 公开演示；`/login` 登录；`/workspace/overview` 工作区概览；`/workspace` 问答与持久化会话；`/workspace/knowledge` 资料导入；`/workspace/members` 成员权限；`/workspace/settings` 配置中心；`/workspace/audit` 审计。管理页仅 admin / security 可访问，审计另向 auditor 开放。

首页用同一张 3D 桌面串起“查资料 → 生成回答 → 检查权限 → 发出答案”，每步可重播，支持身份切换、单轮、多轮和正常问题；小屏幕与 WebGL 不可用时使用可读步骤动画。

默认 `BUTLER_MODE=demo`：后台配置、资料、会话与审计保存在 `.runtime/workspace-demo.sqlite`，公开演示仍使用独立内存数据。登录页支持账号密码，也可展开「体验演示账号」；使用 Sara 在「成员与权限」创建本地账号。可用 `BUTLER_DEMO_DATABASE_URL` 指定演示数据库。企业模式使用 PostgreSQL 和内部服务凭据，默认账号密码登录：首次设置 `BUTLER_ADMIN_USERNAME` 与 `BUTLER_ADMIN_PASSWORD`，OIDC 可按需开启。企业模式不加载演示账号或资料；部署文件另启隔离的演示服务供首页使用。

**企业部署和剩余生产验收项见 [企业工作区部署](docs/enterprise-deployment.md)。** 部署文件为 `infra/compose.enterprise.yml`。密钥由服务端环境管理，后台只保存非敏感运行配置。资料接入支持带 ACL 的 JSON 导入和 Git 仓库同步（`/workspace/sync/*` 与 `python -m butler.workers.run`），托管平台适配器尚未实现。

演示接口：`POST /ask` · `POST /compare` · `GET /sources` · `GET /audit` · `GET /audit/verify` · `GET /eval` · `GET /eval/cases`。企业 API 关闭这些旧入口，使用服务端绑定身份的 `/workspace/*` 接口；浏览器通过 Next.js `/api/workspace/*` 访问。`/audit/tamper`、`/demo/reset` 仅供隔离的演示数据使用。

现有规则评测输出：30 组攻击 + 30 个正常问题，无权限 RAG 泄露100%，文档级 RAG 90%，Butler 0%，误拦0%。这些数字仅适用于合成规则用例；本次还发现跨轮评分漏算，不能作为实模安全结论，详见[核查报告](docs/implementation-audit.md)。

真实接入优先选择已有测试空间和账号的平台，完整验收内容同步、权限和撤权后，再扩展到其余平台。
