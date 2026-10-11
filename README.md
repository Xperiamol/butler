# Butler

连“结论”也管的企业 AI 助手。Tencent Cloud AI CAN DO IT Hackathon · Aspire 赛道。

三层防护：文档级（平台原生权限）→ 结论级（防马赛克效应）→ 可证明（哈希链审计 + 公开评测集）。

## 目录
- `services/api` FastAPI 后端（核心逻辑都在 `butler/`）
- `apps/web` Next.js 前端（待建）
- `seed/tidepool` 虚构公司 Tidepool Pay 的演示数据 + 马赛克攻击评测用例
- `docs/adr` 设计取舍记录

## 快速开始
```bash
cd services/api
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
pytest -q                       # 权限 / 审计链 / 马赛克评测
uvicorn butler.main:app --reload
```

> 开发期用 `connectors/fake.py` 的离线数据，界面始终标注数据来源；真实平台适配器按 Slack → Confluence/Jira → Drive 顺序接入。
