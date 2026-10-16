"""主角场景：赛题五个用例用到的资料。每个场景有公开部分和受限部分，受限部分按各平台原生机制设限。

场景 1  Atlas 数据库迁移：Jira 项目 + 公开 Slack 频道里的阻塞问题 + 只有领导层能看的私有频道（预算超支、可能延期）
场景 2  payment-service 事故 runbook：Confluence 页面会被“来源平台上的更新”追加一步；Drive 里还有一份过期副本（干扰项）
场景 3  Q3 安全事件报告：Confluence 安全空间 + Jira 安全级别 + 私有频道 + Drive 受限文件（图片 / 扫描 PDF）
场景 4  结算战情室：私有频道 + 页面级限制；把人移出频道 / 收紧页面后，回答立刻变化
场景 5  审计：由 seed_audit_history 生成 30 天访问记录（在 audit_seed.py）
另有：支付故障复盘（含监控截图、事故电话录音转写）、认证服务设计讨论（含白板照片）、供应商合同扫描件、容量表。
"""
from __future__ import annotations
import json

from . import media
from .base import Attachment
from .confluence import Page
from .drive import DriveFile, Perm
from .hub import Hub
from .jira import Comment, Issue
from .slack import Channel, Message
from .vocab import date


class Ctx:
    def __init__(self, hub: Hub, epoch: float):
        self.hub, self.epoch = hub, epoch
        self.d = hub.directory
        self.base = epoch - (epoch % 86400)

    def at(self, days_ago: float, hour: float = 9.0) -> float:
        return self.base - days_ago * 86400 + hour * 3600

    def T(self, team: str, i: int = 0) -> str:
        return self.d.team(team)[i].id

    def chan(self, cid: str, name: str, members: set[str], kind: str = "private", ws: str = "T001", topic: str = "") -> Channel:
        c = Channel(cid, name, ws, kind, set(members), topic, 365)
        self.hub.slack.add_channel(c)
        return c

    def cid(self, name_or_id: str) -> str:
        if name_or_id in self.hub.slack.channels:
            return name_or_id
        return next(ch.id for ch in self.hub.slack.channels.values() if ch.name == name_or_id and ch.ws == "T001")

    def thread(self, channel: str, days_ago: float, hour: float, root: tuple[str, str], replies: list[tuple[str, str]], files: list[Attachment] | None = None):
        channel = self.cid(channel)
        ts = self.at(days_ago, hour)
        self.hub.slack.add_message(channel, Message(ts, root[0], root[1], files=files or []))
        for k, (u, t) in enumerate(replies):
            self.hub.slack.add_message(channel, Message(ts + 240 * (k + 1) + 17 * k, u, t, thread_ts=ts))

    def page(self, pid: str, space: str, title: str, body: str, author: str, days_ago: float, parent: str | None = None, restrict: set[str] | None = None, atts: list[Attachment] | None = None, version: int = 1, links: list[str] | None = None):
        p = Page(pid, space, title, body, author, self.at(days_ago + 20, 9), self.at(days_ago, 10), parent, version, labels=[space.lower()], restrict_users=restrict, attachments=atts or [], links=links or [])
        self.hub.confluence.add_page(p)
        return p

    def issue(self, key: str, summary: str, desc: str, status: str, prio: str, reporter: str, assignee: str | None, days_ago: float, comments: list[tuple[str, float, str]] = (), security: str | None = None, links: list[tuple[str, str]] = (), typ: str = "Task", atts: list[Attachment] | None = None):
        i = Issue(key, key.split("-")[0], typ, summary, desc, status, prio, reporter, assignee, self.at(days_ago + 14, 9), self.at(days_ago, 11), labels=[], links=list(links),
                  comments=[Comment(u, b, self.at(d, 10)) for u, d, b in comments], security=security, attachments=atts or [], version=3)
        self.hub.jira.add_issue(i)
        return i

    def drive(self, fid: str, name: str, mime: str, drive: str | None, owner: str, days_ago: float, text: str = "", perms: list[Perm] = (), limited: bool = False, att: Attachment | None = None, folder: str | None = None):
        f = DriveFile(fid, name, mime, folder, drive, owner, self.at(days_ago + 10, 9), self.at(days_ago, 14), text, list(perms), limited, att, version=2)
        self.hub.drive.add_file(f)
        return f


def _img(key: str, built: tuple[bytes, str], name: str, how: str = "vision") -> Attachment:
    media.save(key, built[0])
    return Attachment(key.replace(".png", "").replace(".pdf", ""), name, "application/pdf" if key.endswith(".pdf") else "image/png", key, built[1], how)


def add_engineering(c: Ctx) -> None:
    ep, T = c.epoch, c.T
    alice, mliu, raj, jdoe = "alice", "mliu", "raj", "jdoe"
    marcus, daniel, grace, pete, olivia = "marcus", "daniel", "grace", "pete", "olivia"
    plat2, sre2 = T("platform-eng", 2), T("sre", 1)

    # ================= 场景 1：Atlas 数据库迁移 =================
    cutover = date(ep + 35 * 86400)
    timeline = _img("atlas-cutover-timeline.png", media.timeline("Project Atlas — cutover timeline", [("Provision Aurora + parameter groups", 0, 2, "done"), ("Schema conversion (SCT)", 1, 3, "done"), ("DMS full load + CDC", 2, 5, "done"),
                                                                                                         ("Validation: checksums", 4, 7, "active"), ("Rehearsal #2 (CDC lag blocker)", 5, 7, "blocked"), ("Rehearsal #3", 7, 8, "todo"), ("Cutover window", 9, 10, "todo"), ("14-day soak, then decommission PG12", 10, 12, "todo")],
                                                                                                         12, 6, "Target cutover: Saturday " + cutover), "Atlas cutover timeline (Gantt)")
    c.page("9010", "ATLAS", "Atlas Cutover Plan — database migration", f"## Goal\nDatabase migration (Project Atlas): migrate the payments-db (self-managed PostgreSQL 12, ~4.8 TB) to Aurora PostgreSQL 15 with less than 10 minutes of write downtime.\n\n## Target date\nCutover window: Saturday {cutover}, 01:00–03:00 SGT. A go/no-go review happens the Thursday before.\n\n"
           "## Phases\n1. Provision Aurora cluster, parameter groups and IAM auth (done)\n2. Schema conversion and fixes with AWS SCT (done)\n3. DMS full load and change data capture (done)\n4. Validation: row counts and checksums on ledger tables (in progress, 11 of 14 tables complete)\n5. Rehearsals #2 and #3 (rehearsal #2 revealed CDC lag; see ATLAS-106)\n6. Cutover, 14-day soak, decommission of the old cluster\n\n"
           "## Owners\nMigration lead: Maya Liu. Payments owner: Alice Tan. SRE: Raj Patel. Executive sponsor: Marcus Yeo.\n\n## Rollback\nPoint of no return is the moment writes are enabled on Aurora. Before that, rollback is a DNS/config flip back to PostgreSQL 12 and takes about 5 minutes.\n\n## Links\nJira epic ATLAS-101. Channel #proj-atlas.",
           mliu, 2, atts=[timeline], version=9, links=["ATLAS-101", "ATLAS-106", "ATLAS-107"])
    c.page("9011", "ATLAS", "Atlas Rehearsal #2 — database migration report", "## Result\nFull load completed in 3h12m. CDC lag on `ledger_entries` peaked at 41 minutes during the replay of the nightly batch, far above the 60-second target.\n\n## Findings\n- Replication slot WAL retention grew to 380 GB.\n- DMS task failed on `merchant_documents` rows with LOB columns above 32 MB.\n\n## Decisions\nExclude the LOB table from DMS and copy it with pg_dump (owner: Alice Tan). Open an AWS support case about slot bloat (owner: Raj Patel).",
           mliu, 5, parent="9010", version=3, links=["ATLAS-106", "ATLAS-107"])
    c.page("9012", "ATLAS", "Atlas Risk Register (leads only)", "## Open risks\n- R3: CDC lag exceeds target during peak (mitigation: rehearsal #3, throttle batch)\n- R7: **Budget overrun**: the Aurora reserved commitment is 18% above the original estimate. Needs CFO approval.\n- R9: **Contingency date**: if rehearsal #3 slips, cutover moves to Saturday " + date(ep + 56 * 86400) + ". Not yet communicated to the team.\n\n## Distribution\nRestricted to the steering group.",
           marcus, 3, parent="9010", restrict={marcus, daniel, pete, grace, olivia}, version=4)
    c.issue("ATLAS-101", "Database migration: move payments-db from self-managed PostgreSQL 12 to Aurora PostgreSQL 15", "Epic for the database migration (Project Atlas). Target cutover: Saturday " + cutover + ". Children: ATLAS-102 … ATLAS-113.", "In Progress", "Highest", marcus, mliu, 1,
            [(mliu, 1, "Status: 3 of 8 phases done. Validation at 11/14 tables. Two blockers open: ATLAS-106 (CDC lag) and ATLAS-107 (LOB columns). Cutover date unchanged unless rehearsal #3 fails.")], typ="Epic", links=[("is parent of", "ATLAS-106"), ("is parent of", "ATLAS-107")])
    c.issue("ATLAS-102", "Provision Aurora cluster and parameter groups (ap-southeast-1)", "Create the Aurora PostgreSQL 15 cluster with Multi-AZ writer and two readers.", "Done", "High", mliu, mliu, 30)
    c.issue("ATLAS-103", "Convert schema with AWS SCT and fix incompatible functions", "Converted 212 objects; 9 functions needed manual rewrites.", "Done", "High", mliu, plat2, 24)
    c.issue("ATLAS-104", "Set up DMS replication instance and initial full load", "Replication instance r6i.4xlarge. Full load of 4.8 TB completed.", "Done", "High", mliu, raj, 18)
    c.issue("ATLAS-105", "Validate row counts and checksums for ledger tables", "Compare row counts and per-row checksums for the 14 ledger tables. 11 of 14 complete; the largest three remain.", "In Progress", "High", mliu, mliu, 2,
            [(mliu, 2, "ledger_entries and settlement_lines checksums are still running; expect results Thursday.")])
    c.issue("ATLAS-106", "Logical replication lag on ledger_entries exceeds 40 min in rehearsal #2", "During rehearsal #2 the CDC lag for `ledger_entries` peaked at 41 minutes (target: under 60 seconds). Replication slot WAL grew to 380 GB. **Blocker for cutover.**", "Blocked", "Highest", mliu, raj, 3,
            [(raj, 3, "AWS support case #4471829 opened. They suggest tuning max_slot_wal_keep_size and splitting the task per table."), (mliu, 1, "Will test table splitting in rehearsal #3.")], links=[("blocks", "ATLAS-101")])
    c.issue("ATLAS-107", "DMS task fails on LOB columns above 32 MB in merchant_documents", "DMS aborts the task on rows with LOBs above 32 MB. Options: full LOB mode (slow) or exclude the table and copy with pg_dump. **Blocker.**", "Blocked", "High", alice, alice, 4,
            [(marcus, 4, "Go with exclude + pg_dump. Alice owns it."), (alice, 2, "pg_dump copy of merchant_documents tested in staging: 52 minutes. Needs a longer window or a pre-copy.")], links=[("blocks", "ATLAS-101")])
    c.issue("ATLAS-108", "Cutover runbook review with SRE", "Walk through the cutover steps with SRE and agree the go/no-go checklist.", "To Do", "Medium", mliu, raj, 2)
    c.issue("ATLAS-109", "Rollback plan and point-of-no-return checklist", "Document rollback before and after writes are enabled on Aurora.", "To Do", "High", mliu, sre2, 2)
    c.issue("ATLAS-110", "Application connection cutover via config-service flag", "Switch services to the Aurora endpoint with a flag, per service, in the cutover window.", "In Progress", "Medium", alice, alice, 3)
    c.issue("ATLAS-111", "Performance regression test: p99 write latency vs baseline", "Load test on Aurora with production-shaped traffic. Baseline p99 write latency on PG12: 38 ms.", "In Progress", "Medium", mliu, plat2, 3,
            [(plat2, 3, "Aurora p99 write latency 41 ms at 1.2x peak. Within the 15% budget.")])
    c.issue("ATLAS-112", "Decommission PostgreSQL 12 after a 14-day soak", "Only after sign-off from SRE and the payments owner.", "To Do", "Low", mliu, mliu, 2)
    c.issue("ATLAS-113", "Security review of Aurora IAM auth and KMS keys", "Review completed by the security team; no findings.", "Done", "Medium", mliu, "sara", 12)
    c.issue("ATLAS-114", "Approve Aurora reserved commitment overrun", "Approval request for the Aurora reserved commitment: 18% above the original estimate.", "Pending approval", "High", marcus, grace, 2,
            [(grace, 2, "Approving up to USD 140k pending a revised business case.")], security="Leadership")
    ch_atlas = c.chan("CH-ATLAS", "proj-atlas", {mliu, alice, raj, marcus, plat2, sre2, c.T("payments-eng", 2), c.T("data-eng", 0)}, "public", topic="Project Atlas — payments-db to Aurora")
    c.thread("CH-ATLAS", 6, 10, (mliu, "Database migration rehearsal #2 finished. Full load OK (3h12m), but CDC lag on ledger_entries peaked at 41 min during the nightly batch replay. Target is 60 s. Writing up the report on the wiki."), [(raj, "Slot WAL retention hit 380 GB. That's what worries me, not just the lag."), (alice, "Is the lag only the nightly batch? If so we can throttle the batch during cutover.")])
    c.thread("CH-ATLAS", 4, 15, (alice, "Database migration blocker: DMS fails on merchant_documents rows with LOBs above 32 MB. Options: (a) full LOB mode, slow, (b) exclude the table and copy it with pg_dump. We need a decision today."), [(mliu, "Full LOB mode would add ~14h to the full load. I prefer (b)."), (marcus, "Go with (b). Alice owns it. Please confirm the copy time in staging."), (alice, "Tested in staging: pg_dump copy takes 52 minutes. I'll pre-copy during the week and apply a delta on cutover night.")])
    c.thread("CH-ATLAS", 3, 11, (raj, "AWS support case #4471829 opened for the replication slot bloat. They suggest max_slot_wal_keep_size and splitting the DMS task per table."), [(mliu, "Splitting per table is easy. I'll try it in rehearsal #3."), (raj, "Also adding an alert on slot lag > 5 GB.")])
    c.thread("CH-ATLAS", 1, 16, (mliu, "Database migration status for Thursday's sync: ATLAS-105 checksums 11/14 tables done. Open blockers: ATLAS-106 (CDC lag) and ATLAS-107 (LOB columns, workaround agreed). Cutover is still planned for Saturday " + cutover + " unless rehearsal #3 fails."), [(plat2, "Perf test looks fine: p99 write latency 41 ms vs 38 ms baseline."), (marcus, "Thanks Maya. Keep the Thursday sync short.")])
    c.chan("CH-ATLASP", "atlas-leads-private", {marcus, daniel, pete, grace, olivia}, "private", topic="Atlas steering — leaders only")
    c.thread("CH-ATLASP", 2, 18, (marcus, "Aurora commit is 18% over the original estimate. If rehearsal #3 slips I propose we move the cutover to " + date(ep + 56 * 86400) + " and do not announce until Thursday's steering. Please keep this within this group for now."), [(grace, "I can approve the overrun up to USD 140k, but I need a revised business case before the board pack."), (daniel, "Agree on the contingency date. Engineering should not hear about it until we know rehearsal #3 results."), (pete, "Product is fine with a one-month slip if we communicate it to merchants properly.")])
    c.drive("fH-ATLAS", "Atlas steering committee — October update", "application/vnd.google-apps.presentation", "SD-EXEC", marcus, 2,
            f"Slide 1: Atlas steering — October update\nSlide 2: Status — validation at 11/14 tables; rehearsal #2 exposed CDC lag (41 min) and a LOB limitation.\nSlide 3: Risks — budget overrun of 18% on the Aurora commitment (USD 140k approved subject to a business case); contingency cutover date {date(ep + 56 * 86400)}.\nSlide 4: Decisions needed — approve the contingency date; approve communication plan.\nSpeaker notes: do not circulate beyond the steering group.")

    # ================= 场景 2：runbook 新鲜度 =================
    c.page("9100", "PGW", "payment-service Incident Runbook", "## Purpose\nUse this runbook when payment-service shows elevated 5xx or latency. Owner: payments-eng. Last reviewed with SRE after INC-2291.\n\n## Symptoms\n- 5xx above 2% on `/v1/payments`\n- p99 latency above 1.5 s\n- PagerDuty alert `payment-service-high-error-rate`\n\n## Diagnosis\n1. Open the Grafana dashboard `payment-service / overview` and note the start time.\n2. Check the last deploy in Argo CD; if a release landed in the last 30 minutes, suspect it first.\n3. Check the config-service audit log for config changes in the last hour.\n4. Check the database connection pool saturation panel (target: under 80%).\n5. Check downstream health: ledger-service, fraud-engine.\n\n## Mitigation\n- Roll back the last release with `argocd app rollback payment-service`.\n- Revert the last config change if it touched pool sizes or timeouts.\n- Scale payment-service to 12 replicas.\n\n## Escalation\nPage payments-eng primary, then the SRE manager if the error budget burn rate stays above 10x for 15 minutes. Announce Sev1 in #incidents.\n\n## Related\nPostmortem INC-2291. Jira SRE-901.",
           alice, 9, version=7, links=["INC-2291", "SRE-901"])
    c.drive("fH-RUNBOOK-OLD", "payment-service runbook (old copy)", "application/vnd.google-apps.document", "SD-ENG", T("sre", 2), 120,
            "payment-service runbook — copied from the wiki in May. Symptoms: 5xx above 2%. Diagnosis: check Grafana, check Argo CD, check pool saturation. Mitigation: roll back, scale to 8 replicas. Escalation: page payments-eng primary.", perms=[Perm("domain", "", "reader")])
    c.issue("SRE-901", "Add ledger writer failover step to payment-service runbook", "After INC-2291 we want an explicit failover step for the ledger writer in the runbook.", "In Progress", "High", raj, alice, 8, [(raj, 8, "Draft step ready; Alice to review and publish to the wiki.")])
    c.thread("incidents", 8, 9, ("raj", "Runbook gap from INC-2291: there is no explicit failover step for the ledger writer. SRE-901 tracks adding it. Alice, can you publish once reviewed?"), [(alice, "Will do. I'll add it as a numbered step so on-call doesn't have to hunt.")])

    # ================= 支付故障复盘（含监控截图 + 事故录音）=================
    inc_date = date(ep - 95 * 86400)
    grafana = _img("inc-2291-latency-p99.png", media.line_chart("payment-service — p99 latency and 5xx rate", [f"01:{m:02d}" for m in range(40, 60, 2)] + [f"02:{m:02d}" for m in range(0, 50, 2)],
                                                                [("p99 latency (s)", [0.31, 0.3, 0.33, 0.32, 0.3, 0.34, 0.33, 0.31, 0.32, 0.36, 0.5, 4.8, 4.6, 4.1, 3.4, 2.2, 1.1, 0.5, 0.35, 0.32, 0.31, 0.3, 0.3, 0.31, 0.3], "#58a6ff"),
                                                                 ("5xx rate (%)", [0.1, 0.1, 0.2, 0.1, 0.1, 0.1, 0.2, 0.1, 0.1, 0.4, 3.0, 34.0, 31.0, 22.0, 12.0, 6.0, 2.0, 0.8, 0.4, 0.2, 0.1, 0.1, 0.1, 0.1, 0.1], "#f0883e")],
                                                                "seconds / percent", annotation=(11, "02:10 5xx spike begins"), threshold=(1.5, "SLO p99 1.5 s")), "INC-2291 p99 latency and 5xx screenshot")
    transcript = media.transcript("inc-2291-bridge-call.mp3") or {"segments": []}
    call_text = "Incident bridge recording, transcript (speech-to-text):\n" + "\n".join(f"[{s['start']:.0f}s] {s['speaker']}: {s['text']}" for s in transcript["segments"])
    call = Attachment("bridge-call", "INC-2291 incident bridge call.mp3", "audio/mpeg", "inc-2291-bridge-call.mp3", call_text, "asr")
    c.page("9400", "INC", "Postmortem INC-2291: Payment gateway outage", f"## Summary\nOn {inc_date} between 02:10 and 02:31 SGT, payment-service returned HTTP 5xx for up to 34% of requests. About 1,900 merchant transactions failed; all were retried successfully by merchants or our webhook replay. No data was lost.\n\n"
           "## Root cause\nA config-service rollout at 01:55 SGT applied a new config template that lowered the payment-service database connection pool from 200 to 50. Under the early-morning settlement-prep traffic the pool was exhausted, requests queued, and timeouts cascaded.\n\n"
           "## Timeline (SGT)\n- 01:55 config-service rollout lowers max pool size 200 → 50\n- 02:10 5xx rate crosses 3%, PagerDuty pages Raj Patel (on-call)\n- 02:14 incident bridge opened; root cause identified as the pool limit\n- 02:28 config reverted by Alice Tan\n- 02:31 error rate back under 1%\n\n## What went well\nAlerting fired within two minutes and the bridge was assembled quickly.\n\n## What went badly\nThe config template change had no review from payments-eng; there was no saturation alert on the pool; the runbook did not mention checking recent config changes.\n\n"
           "## Follow-up tickets\n- PAY-9001 Add connection pool saturation alert (Done)\n- PAY-9002 Raise default pool size and load test (In Progress)\n- PAY-9003 Require payments-eng review for config template changes (In Progress)\n- PAY-9004 Update the runbook with pool and config diagnostics (Done)\n- PAY-9005 Game day: pool exhaustion drill (To Do)\n- SRE-901 Add ledger writer failover step to the runbook (In Progress)\n\n## Attachments\nGrafana screenshot of p99 latency and 5xx rate; recording of the incident bridge call.",
           raj, 95, atts=[grafana, call], version=5, links=["PAY-9001", "PAY-9002", "PAY-9003", "PAY-9004", "PAY-9005", "SRE-901"])
    for k, (summ, st, d) in enumerate([("Add connection pool saturation alert for payment-service", "Done", 80), ("Raise default pool size and load test under peak traffic", "In Progress", 20), ("Require payments-eng review for config template changes", "In Progress", 25),
                                      ("Update payment-service runbook with pool and config diagnostics", "Done", 70), ("Game day: connection pool exhaustion drill", "To Do", 12)], 1):
        c.issue(f"PAY-900{k}", summ, f"Follow-up from postmortem INC-2291 (payment gateway outage on {inc_date}).", st, "High", raj, alice if k != 3 else plat2, d, [(alice, d, "Linked to INC-2291.")], links=[("relates to", "INC-2291")])
    c.thread("incidents", 95, 2.3, (raj, "SEV1: payment-service 5xx at 34%. Bridge is open. Looks like pool exhaustion after the 01:55 config rollout."), [(alice, "Confirmed: max pool size is 50 instead of 200. Reverting the config now."), (raj, "Recovered at 02:31. Thanks all. Postmortem to follow."), (marcus, "Please make sure the config template change gets a payments-eng review next time.")],
             files=[Attachment("inc-graf", "p99-latency.png", "image/png", "inc-2291-latency-p99.png", grafana.derived, "vision")])
    c.drive("fH-BRIDGE", "INC-2291 incident bridge recording", "audio/mpeg", "SD-ENG", raj, 95, call_text, perms=[Perm("group", "engineering", "reader")], att=call)

    # ================= 认证服务设计讨论（含白板照片）=================
    auth_wb = _img("auth-flow-whiteboard.png", media.whiteboard("New auth service — token flow", [("Client\n(app)", 40, 120), ("auth-gateway", 330, 120), ("token-service\n(opaque tokens)", 620, 120)], ["opaque reference tokens, 15 min TTL", "introspection cached 30 s at the gateway", "signing keys rotate every 90 days (KMS)"], [(0, 1), (1, 2)]), "Auth token flow — whiteboard photo")
    c.chan("CH-AUTH", "proj-auth-v2", {c.T("auth-eng", 0), c.T("auth-eng", 1), alice, mliu, "sara", c.T("auth-eng", 2)}, "public", topic="New auth service design")
    c.thread("CH-AUTH", 11, 10, (c.T("auth-eng", 0), "Design thread for the new auth service. Option A: signed JWTs (stateless, but hard to revoke). Option B: opaque reference tokens with introspection (revocable, one extra hop). Thoughts?"), [("sara", "Security prefers B: instant revocation matters for compromised merchant keys."), (alice, "Latency of introspection worries payments. Can the gateway cache introspection results?"), (c.T("auth-eng", 1), "Cache for 30s at the gateway; revocation lag is then at most 30s. That's acceptable.")])
    c.thread("CH-AUTH", 8, 14, (c.T("auth-eng", 0), "Whiteboard from today's session: opaque tokens with 15 min TTL, introspection cached 30s, key rotation every 90 days via KMS."), [("sara", "Add a break-glass path to revoke all tokens for a merchant."), (mliu, "Do we need the token-service to be multi-region from day one? I'd say no for v1.")], files=[Attachment("auth-wb", "auth-token-flow.png", "image/png", "auth-flow-whiteboard.png", auth_wb.derived, "vision")])
    c.thread("CH-AUTH", 6, 11, (c.T("auth-eng", 0), "Decision: we go with option B (opaque tokens + cached introspection). I'll write the ADR."), [("sara", "Thanks. Please record the revocation SLA in the ADR."), (c.T("auth-eng", 1), "ADR-014 drafted, linking in the channel topic.")])
    c.page("9500", "AUTH", "ADR-014: Adopt opaque reference tokens with introspection for the new auth service", "## Status\nAccepted\n\n## Context\nThe new auth service issues credentials for merchants and internal services. We compared signed JWTs with opaque reference tokens.\n\n## Decision\nWe will use opaque reference tokens (15 minute TTL) validated through an introspection endpoint. The gateway caches introspection results for 30 seconds. Signing keys for internal assertions rotate every 90 days through KMS.\n\n"
           "## Consequences\n- Revocation takes effect within 30 seconds.\n- One extra network hop on the critical path; mitigated by the gateway cache.\n- Break-glass endpoint to revoke all tokens for a merchant.\n\n## Discussion\nSee the Slack design thread in #proj-auth-v2 and the whiteboard photo attached to it.", c.T("auth-eng", 0), 5, version=2, links=[])
    c.page("9501", "PGW", "Payment Gateway Architecture Overview", "## Overview\nRequests enter through api-gateway (Envoy) and are routed to payment-service, which calls ledger-service and fraud-engine. The ledger writer is an Aurora PostgreSQL 15 cluster. See the architecture diagram attached to this page.\n\n## Key numbers\n- p99 latency target 1.5 s\n- peak throughput 1,200 requests/second\n- ledger writer RPO 0, RTO 5 minutes", alice, 40, atts=[_img("payment-gateway-architecture.png", media.architecture("Payment Gateway — request path (prod)", [("Merchant\nSDK", 30, 120), ("api-gateway\n(Envoy)", 290, 120), ("payment-service", 550, 120), ("ledger-service", 810, 120), ("fraud-engine", 550, 300), ("Aurora PG 15\nledger writer", 810, 300)], [(0, 1, "HTTPS"), (1, 2, "gRPC"), (2, 3, "gRPC"), (2, 4, "sync score"), (3, 5, "SQL")], "Source: architecture review 2026-Q3"), "Payment gateway architecture diagram")], version=4)

    # ================= 场景 4：结算战情室（权限变更演示）=================
    shot = _img("settlement-error-screenshot.png", media.screenshot_error("settlement-batch — job 2026-10-12", ["2026-10-12 03:00:04 INFO  settlement-batch started job=2026-10-12", "2026-10-12 03:02:11 ERROR bank file rejected: MAS-FAST v2 schema validation failed (field 14: beneficiary_ref)", "2026-10-12 03:02:11 FATAL aborting batch, 18,402 payouts pending", "2026-10-12 03:02:12 INFO  retry scheduled in 45m"]), "Settlement batch error screenshot")
    c.chan("CH-SETTLE", "settlement-war-room", {alice, raj, marcus, c.T("payments-eng", 2), c.T("finance", 0)}, "private", topic="Settlement incident war room")
    c.thread("CH-SETTLE", 5, 3.5, (raj, "Settlement batch 2026-10-12 failed: the bank rejected the file (MAS-FAST v2 schema validation, beneficiary_ref). 18,402 payouts are pending."), [(alice, "The bank changed the field length from 35 to 140 characters. Our normaliser truncates it."), (c.T("finance", 0), "Finance needs payouts out by 18:00 to meet merchant SLAs."), (marcus, "Priority 1. Alice owns the fix, Raj on comms.")], files=[Attachment("settle-shot", "batch-error.png", "image/png", "settlement-error-screenshot.png", shot.derived, "vision")])
    c.thread("CH-SETTLE", 5, 9, (alice, "Workaround: re-run the normaliser with `--beneficiary-ref-max=140` and resubmit manually. First batch of 6,000 payouts accepted by the bank. ETA for the rest: 15:00."), [(raj, "Confirmed accepted. I'll update merchants in the status email."), (c.T("finance", 0), "Thanks. Delay cost estimate: USD 12k in late-payment credits.")])
    c.page("9300", "PAY", "Settlement delay playbook", "## Scope\nUse when a settlement batch is rejected or delayed by the bank.\n\n## Immediate actions\n1. Check the batch log for bank rejection codes.\n2. If the rejection is `MAS-FAST v2 schema validation`, re-run the normaliser with `--beneficiary-ref-max=140` and resubmit manually.\n3. Notify finance of the expected delay and late-payment credit exposure.\n\n## Lessons from the 12 Oct incident\nThe bank changed beneficiary_ref from 35 to 140 characters without notice; add a schema contract test with the bank sandbox.\n\n## Distribution\nRestricted to the war-room group.",
           alice, 4, restrict={alice, raj, marcus, c.T("payments-eng", 2), c.T("finance", 0)}, version=3)


def _pdf(key: str, built: tuple[bytes, str], name: str) -> Attachment:
    media.save(key, built[0])
    return Attachment(key.replace(".pdf", ""), name, "application/pdf", key, built[1], "ocr")
