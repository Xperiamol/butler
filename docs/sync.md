# 数据同步

## 组成

| 部分 | 位置 | 说明 |
| --- | --- | --- |
| 连接器契约 | `connectors/sync.py` | `events(cursor)`、`list_ids()`、`fetch()`、`fetch_principals()` |
| Git 仓库连接器 | `connectors/gitrepo.py` | 不需要平台账号的真实数据源：`git diff` 检测增/改/删，提交序号做版本，按路径前缀规则展开权限 |
| 队列 | `workers/queue.py` | 数据库队列（`sync_jobs` 表）：幂等入队、租约、指数退避、死信 |
| 处理 | `workers/sync.py` | `pull`（拉变更）→ `reconcile`（对账）→ `run_once`/`drain`（处理）→ 建索引 |
| 运行 | `workers/run.py` | `python -m butler.workers.run`；也可以 `POST /workspace/sync/run` 手动触发 |
| 可选 Celery | `workers/celery_app.py` | 把同一个 tick 挂到 Celery；**测试未覆盖**（沙箱没有 Redis） |

接口（管理员）：`PUT /workspace/sync/config`（连接器、规则、主体映射、权限复核有效期）、`GET /workspace/sync/status`（队列状态、积压秒数、死信、权限最早到期时间）、`POST /workspace/sync/run`。

## 保证（均有测试，`tests/test_sync.py`）

- **幂等**：同一事件重复投递只有一条任务；内容和权限都没变的 upsert 是空操作，不提升修订号、不重建索引。
- **乱序**：每个对象记录已处理的来源版本，旧版本事件丢弃；删除留墓碑，之后迟到的旧 upsert 不会让文档复活。
- **删除**：文档、块、以它为来源的受限事实一起删；修订号提升，持有旧权限的会话失效。
- **对账**：发现"来源有本地没有 / 权限不一致 / 权限复核快到期 / 本地有来源没有"，已有未完成任务的对象不重复入队。
- **权限接口失败 ⇒ 拒绝**：`fetch_principals` 抛错，任务重试（5s×2ⁿ），超过 5 次进死信，错误只记异常类型。已同步文档带 `acl_fresh_until`，过期后检索与来源列表都视为不可读。
- **平台主体映射不出本地组 ⇒ 无人可读**，不是默认放行。
- **撤权可度量**：权限变化时审计写入 `sync.acl_changed`，含 `source_changed_at / detected_at / effective_at`。
- **租约**：worker 领取后崩溃，租约到期会被重新领取，不会丢任务。
- **向量服务故障**不让同步失败：文档先走词法兜底，向量稍后补。

## 真实数据上的一次运行

用 GitLab 手册（681 篇 .md）的真实内容建了一个本地 git 仓库，按目录规则展开权限（security/legal/finance 目录各自一组，其余全员）：

- 初始同步 681 篇：约 1 分钟（瓶颈是入库时的提示注入扫描，约占一半）
- 第二次提交改 5 个、删 3 个：增量 8 个事件，0.4 秒处理完；紧接着对账 `queued = 0`
- 可见文档数：普通员工 67、security 组 491、高管 678

仓库历史是模拟的（两次提交），内容是真实的。**没有接入任何托管平台（Slack/Confluence/Jira/Drive）**，也没有测过 webhook 验签和平台端 API 限流/429。

## 局限

- 目前只有 Git 连接器。接别的平台只需要实现 `SyncConnector` 四个方法，但平台账号映射（平台用户 → 本地成员）还没有，`principal_map` 只映射到本地组。
- 权限展开是"路径前缀 → 主体"的静态规则，不是平台的实时对象级权限。
- 每次修订号提升都会让所有旧会话失效（粒度过粗，审计里的 P1 仍未解决）。
