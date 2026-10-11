# 分工建议（3 人）

先由基座负责人冻结三个接口，之后三条线基本互不阻塞：
1. `connectors/base.py` 适配器契约  2. `models.py` 数据模型  3. `/ask` 等 HTTP 接口

| 线 | 范围 | 目录 | 先做什么 |
|---|---|---|---|
| A 数据线 | Slack、Atlassian、Drive 适配器；账号与种子数据；同步（webhook + 对账 + Celery） | `connectors/` `ingest/` `workers/` `seed/` | Slack 端到端，再 Atlassian，最后 Drive |
| B 安全线（核心） | 结论级防护、受限事实抽取、混元判官、审计链与检查点、评测集（30+30）、红队 | `answer/` `audit/` `redteam/` `tests/` | 扩评测用例，再把关键词判官换成混元 |
| C 产品线 | Next.js 界面：身份切换器、来源标注、左右分屏对比、审计查看器；部署（Docker、Caddy、腾讯云）；Demo 脚本、答辩材料、竞品页 | `apps/web` `infra/` `docs/` | 身份切换 + 提问页，对接 `/ask` |

规则：
- 一个模块一个负责人；跨线改动先在群里说。
- 安全相关代码（`acl/` `answer/mosaic.py` `audit/`）改动必须有测试，且另一人 review。
- 每个人保留与 CodeBuddy/WorkBuddy 的开发对话截图（≥3 张，赛题硬性要求）。
- 两人时：A+C 合并给一人，B 给另一人。
