"""Confluence 批量页面：按页面类型从模板生成。内容合成，只作规模和检索干扰项；主角场景在 hero.py。"""
from __future__ import annotations
from .confluence import ConfluenceServer, Page, Space
from .people import Directory
from .vocab import CAUSES, FEATURES, FIXES, HOWTO, SERVICES, SYMPTOMS, TECH, TEAM_TOPICS, TOPICS_POLICY, Pick, date, when

# (key, name, kind, view_groups, 页数权重)
SPACES: list[tuple[str, str, str, set[str], int]] = [
    ("PGW", "Payment Gateway", "team", {"engineering", "security", "product"}, 70), ("PAY", "Payments Engineering", "team", {"engineering"}, 60),
    ("PLAT", "Platform Engineering", "team", {"engineering"}, 55), ("AUTH", "Auth & Identity", "team", {"engineering", "security"}, 45),
    ("DATA", "Data Platform", "team", {"engineering", "product", "finance"}, 45), ("MOB", "Mobile", "team", {"engineering", "product", "design"}, 35),
    ("SRE", "Site Reliability", "team", {"engineering"}, 60), ("INC", "Incident Archive", "knowledge", {"engineering", "security"}, 40),
    ("ENG", "Engineering Handbook", "knowledge", {"all-employees"}, 40), ("ARCH", "Architecture Decisions", "knowledge", {"engineering"}, 35),
    ("DEVX", "Developer Experience", "team", {"engineering"}, 25), ("QA", "Quality Engineering", "team", {"engineering"}, 20),
    ("REL", "Release Engineering", "team", {"engineering"}, 25), ("OBS", "Observability", "team", {"engineering"}, 25), ("NET", "Networking & Infra", "team", {"engineering"}, 20),
    ("DBA", "Database Engineering", "team", {"engineering"}, 30), ("ML", "ML & Risk Models", "team", {"engineering", "product", "compliance"}, 25),
    ("ATLAS", "Project Atlas — Payments DB migration", "project", {"engineering", "leadership"}, 25), ("SEC", "Security (restricted)", "restricted", {"security"}, 40),
    ("APPSEC", "Application Security Guidelines", "knowledge", {"engineering", "security"}, 25), ("COMP", "Compliance & Audit", "restricted", {"compliance", "leadership", "security"}, 30),
    ("EXEC", "Leadership", "restricted", {"leadership"}, 20), ("FIN", "Finance", "restricted", {"finance-and-leadership"}, 30), ("LEG", "Legal", "restricted", {"legal", "leadership"}, 20),
    ("HR", "People Operations (restricted)", "restricted", {"people-ops", "leadership"}, 25), ("REC", "Recruiting", "restricted", {"people-ops"}, 12),
    ("PRD", "Product", "team", {"product", "engineering", "design", "leadership"}, 40), ("DSN", "Design", "team", {"design", "product", "engineering"}, 20),
    ("RES", "User Research", "team", {"product", "design"}, 15), ("GROW", "Growth", "team", {"product", "sales"}, 12), ("MKT", "Marketing", "team", {"sales", "product"}, 12),
    ("SALES", "Sales Enablement", "team", {"sales", "product", "leadership"}, 20), ("SUP", "Customer Support", "team", {"support", "product", "engineering"}, 25),
    ("CS", "Customer Success", "team", {"support", "sales"}, 12), ("PART", "Partnerships", "team", {"sales", "leadership"}, 12),
    ("ONB", "Onboarding", "knowledge", {"all-employees", "contractors"}, 20), ("POL", "Company Policies", "knowledge", {"all-employees", "contractors"}, 20),
    ("IT", "IT Helpdesk", "knowledge", {"all-employees"}, 20), ("OFC", "Office & Facilities", "knowledge", {"all-employees"}, 10), ("WELL", "Wellbeing", "knowledge", {"all-employees"}, 8),
    ("EVT", "Events", "knowledge", {"all-employees"}, 8), ("CNTR", "Contractor Hub", "knowledge", {"contractors", "people-ops"}, 10),
    ("PRJ-ORION", "Project Orion — merchant dashboard", "project", {"engineering", "product"}, 18), ("PRJ-KITE", "Project Kite — mobile wallet", "project", {"engineering", "product"}, 18),
    ("PRJ-NOVA", "Project Nova — FX expansion", "project", {"engineering", "product", "finance"}, 16), ("PRJ-HELIOS", "Project Helios — card issuing", "project", {"engineering", "product", "compliance"}, 16),
    ("PRJ-MERC", "Project Mercury — open banking APIs", "project", {"engineering", "product"}, 14), ("PRJ-LYRA", "Project Lyra — fraud model v3", "project", {"engineering", "security"}, 14),
    ("PRJ-VEGA", "Project Vega — reconciliation automation", "project", {"engineering", "finance"}, 14), ("OPS", "Business Operations", "team", {"all-employees"}, 12),
    ("DOCS", "Public API Docs (drafts)", "knowledge", {"engineering", "product", "support"}, 18), ("RFC", "Engineering RFCs", "knowledge", {"engineering"}, 30),
]


HERO_ONLY = {"ATLAS"}


def seed_spaces(server: ConfluenceServer) -> None:
    for key, name, kind, groups, _ in SPACES:
        server.add_space(Space(key, name, kind, set(groups) | ({"leadership"} if kind != "restricted" else set()), set(), f"{name} space"))


def _runbook(p: Pick, svc: str) -> tuple[str, str]:
    sym, cause, fix = p.one(SYMPTOMS), p.one(CAUSES), p.one(FIXES)
    steps = p.some(["Check the Grafana dashboard for the service and note the start time", "Compare error rate against the last deploy in Argo CD", "Inspect the pod restarts and recent events in Kubernetes",
                    "Look at the dependency map for failing downstream calls", "Capture a thread dump from the oldest pod", "Review the Datadog APM traces for the slowest endpoints",
                    "Check connection pool saturation and database CPU", "Verify the feature flags changed in the last 24 hours", "Confirm queue depth and consumer lag", "Check certificate expiry and secrets rotation status"], 5)
    body = (f"## Symptoms\nOn-call sees {sym} on {svc}. Alerts fire from Datadog and page the primary via PagerDuty.\n\n## Impact\nCustomer-facing requests to {svc} degrade; merchants may see retries or delayed confirmations.\n\n"
            "## Diagnosis\n" + "\n".join(f"{i + 1}. {s}." for i, s in enumerate(steps)) +
            f"\n\n## Mitigation\nThe most frequent cause is {cause}. In past incidents we {fix}. If the cause is unclear, roll back to the previous release and open an incident channel.\n\n"
            f"## Escalation\nPage the {svc} owning team first, then SRE if the error budget burn rate stays above 10x for 15 minutes. Sev1 incidents are announced in #incidents.")
    return f"Runbook: {svc} — {sym}", body


def _design(p: Pick) -> tuple[str, str]:
    feat, a, b = p.one(FEATURES), p.one(TECH), p.one(TECH)
    title = f"Design: {feat}"
    body = (f"## Context\nMerchants have asked for {feat}. Today the flow is handled by manual steps that do not scale beyond a few hundred requests a day.\n\n"
            f"## Goals\n- Deliver {feat} for all supported markets in Q{p.int(1, 4)}.\n- Keep the p99 latency of the critical path under {p.int(200, 800)} ms.\n- Reuse existing services where possible.\n\n"
            f"## Non-goals\nMulti-region active-active is out of scope for the first release.\n\n## Proposed design\nWe add a thin orchestration layer on top of the ledger and settlement services, backed by {a} for state and {b} for async work. "
            "Each request is idempotent and carries a client-supplied key. Failures are retried with backoff and surfaced to the merchant through webhooks.\n\n"
            f"## Alternatives considered\nUsing a managed workflow engine was rejected because of operational cost. A pure {b}-based approach was rejected because ordering guarantees are weaker.\n\n"
            "## Risks\nData migration for existing merchants, and coordination with the compliance team on reporting obligations.\n\n## Rollout\nBehind a feature flag, enabled for internal merchants first, then 5%, 25% and 100%.")
    return title, body


def _adr(p: Pick, n: int) -> tuple[str, str]:
    a, b = p.some(TECH, 2)
    title = f"ADR-{n:03d}: Use {a} for {p.one(['event streaming', 'caching', 'secrets', 'job scheduling', 'metrics', 'feature flags'])}"
    body = (f"## Status\nAccepted\n\n## Context\nWe evaluated {a} and {b} for this use case. Requirements: durability, operational simplicity, and a managed offering in ap-southeast-1.\n\n"
            f"## Decision\nWe will use {a}. It satisfies the durability requirement and our teams already operate it in production.\n\n## Consequences\nWe accept vendor coupling. A migration path to {b} is documented but not planned.")
    return title, body


def _meeting(p: Pick, team: str, ts: float) -> tuple[str, str]:
    topic = p.one(TEAM_TOPICS.get(team, ["planning"]))
    title = f"{team} weekly sync — {date(ts)}"
    items = [f"Follow up on {topic}", f"Review open risks for {p.one(SERVICES)}", f"Plan the on-call handover", f"Decide whether to adopt {p.one(TECH)}"]
    body = ("## Attendees\n" + ", ".join(sorted(p.some(["Alice", "Maya", "Raj", "Wei", "Priya", "Daniel", "Sofia", "Kai", "Nina", "Owen"], 5))) +
            f"\n\n## Notes\nWe reviewed {topic} progress. The team agreed to prioritise stability work this sprint. {p.one(CAUSES).capitalize()} was discussed as a recurring theme.\n\n## Action items\n" +
            "\n".join(f"- {i}" for i in p.some(items, 3)))
    return title, body


def _postmortem(p: Pick, n: int) -> tuple[str, str]:
    svc, sym, cause, fix = p.one(SERVICES), p.one(SYMPTOMS), p.one(CAUSES), p.one(FIXES)
    title = f"Postmortem INC-{3000 + n}: {sym} on {svc}"
    body = (f"## Summary\nBetween {p.int(1, 5):02d}:{p.int(0, 5)}0 and {p.int(6, 9):02d}:{p.int(0, 5)}0 SGT, {svc} experienced {sym}. Impact was limited to a subset of merchants and no data was lost.\n\n"
            f"## Root cause\nThe incident was caused by {cause}.\n\n## Resolution\nWe {fix}.\n\n## What went well\nAlerting fired within two minutes and the incident channel was opened quickly.\n\n"
            "## What could be better\nThe runbook did not cover this failure mode, and dashboards lacked a saturation panel.\n\n## Follow-ups\n- Update the runbook\n- Add a saturation alert\n- Review capacity assumptions next quarter")
    return title, body


def _howto(p: Pick) -> tuple[str, str]:
    t = p.one(HOWTO)
    body = f"## Overview\nThis guide explains how to {t}.\n\n## Prerequisites\nYou need production read access and membership of the relevant on-call rotation.\n\n## Steps\n" + \
           "\n".join(f"{i + 1}. {s}" for i, s in enumerate(p.some(["Open the internal portal and select the environment", "Run the helper script with the --dry-run flag first", "Review the diff and get a second approver",
                                                                      "Apply the change during the agreed window", "Verify the dashboards and post in the team channel", "Record the change in the ticket"], 5))) + \
           f"\n\n## Troubleshooting\nIf the command fails with a timeout, retry once and then check {p.one(TECH)} status before escalating."
    return f"How to {t}", body


def _policy(p: Pick, i: int) -> tuple[str, str]:
    topic = TOPICS_POLICY[i % len(TOPICS_POLICY)]
    body = f"## Purpose\nThis policy defines expectations for {topic.lower()} at Tidepool Pay.\n\n## Scope\nAll employees and contractors.\n\n## Requirements\n- Follow the standards in this document.\n- Report exceptions to the owning team.\n- Review annually.\n\n## Owner\nThe policy owner reviews this document every twelve months."
    return f"Policy: {topic} (v{p.int(1, 4)}.{p.int(0, 9)})", body


def _release(p: Pick) -> tuple[str, str]:
    svc, v = p.one(SERVICES), f"{p.int(1, 4)}.{p.int(0, 30)}.{p.int(0, 9)}"
    body = f"## Highlights\n- Improved retry behaviour for {p.one(SYMPTOMS)}\n- {p.one(FEATURES).capitalize()} behind a flag\n\n## Fixes\n- Resolved an issue caused by {p.one(CAUSES)}\n\n## Upgrade notes\nNo manual steps required."
    return f"Release notes: {svc} v{v}", body


def _generic(p: Pick, space: str, team_topics: list[str]) -> tuple[str, str]:
    t = p.one(team_topics)
    body = f"## Overview\nThis page collects notes about {t} for the {space} space.\n\n## Current status\nWork is on track. The main open question is how to balance {p.one(FEATURES)} with the roadmap for next quarter.\n\n## Links\nSee related design documents and the team channel."
    return f"{t.capitalize()} — notes and status", body


def fill_pages(server: ConfluenceServer, d: Directory, epoch: float, seed: int, start_id: int = 20000, scale: float = 1.0) -> int:
    """按空间的页数权重生成页面。返回生成数量。"""
    p = Pick(seed)
    pid = start_id
    made = 0
    for key, name, kind, groups, weight in SPACES:
        if key in HERO_ONLY:
            continue
        n = max(3, int(weight * scale))
        team_topics = [t for ts in TEAM_TOPICS.values() for t in ts]
        authors = [x.id for x in d.employees() if x.team in {"payments-eng", "platform-eng", "sre", "auth-eng", "data-eng"}] or [x.id for x in d.employees()]
        parents: list[str] = []
        for i in range(n):
            ts = when(epoch, p.between(1, 220))
            kindp = p.r.random()
            if kind == "restricted" or key in {"FIN", "LEG", "HR", "REC", "EXEC", "COMP", "SEC"}:
                title, body = _restricted_page(p, key, i)
            elif key in {"POL", "ONB", "IT", "OFC", "WELL", "EVT", "CNTR", "OPS"}:
                title, body = _policy(p, i) if key in {"POL", "CNTR"} else _howto(p) if key == "IT" else _generic(p, name, ["onboarding", "benefits", "events", "facilities", "tooling"])
            elif key in {"INC"} or (key in {"SRE", "PGW"} and kindp < 0.3):
                title, body = _postmortem(p, made) if kindp < 0.5 else _runbook(p, p.one(SERVICES))
            elif kindp < 0.18:
                title, body = _runbook(p, p.one(SERVICES))
            elif kindp < 0.40:
                title, body = _design(p)
            elif kindp < 0.52:
                title, body = _adr(p, 100 + made % 400)
            elif kindp < 0.70:
                title, body = _meeting(p, p.one(list(TEAM_TOPICS)), ts)
            elif kindp < 0.78:
                title, body = _howto(p)
            elif kindp < 0.86:
                title, body = _release(p)
            else:
                title, body = _generic(p, name, team_topics)
            title = f"{title}" if not any(pg.title == title and pg.space == key for pg in server.pages.values()) else f"{title} (rev {i})"
            parent = p.one(parents) if parents and p.chance(0.3) else None
            page = Page(str(pid), key, title, body, p.one(authors), ts - 86400 * p.int(0, 30), ts, parent, p.int(1, 9), labels=[key.lower(), kind])
            if parent is None and p.chance(0.25):
                parents.append(page.id)
            # 少量页面带页面级限制（只给指定的人/组）：Confluence 的页面级权限
            if p.chance(0.04) and kind != "restricted":
                page.restrict_users = set(p.some([x.id for x in d.employees()], p.int(1, 3)) + [page.author])
            server.add_page(page)
            pid += 1
            made += 1
    return made


def _restricted_page(p: Pick, key: str, i: int) -> tuple[str, str]:
    if key == "FIN":
        t = p.one(["FY26 budget by department", "Vendor spend review", "Quarterly forecast", "Month-end close checklist", "Headcount cost model", "Cloud cost allocation"])
        return f"{t} (draft {i})", f"## Summary\nFinance working document for {t.lower()}. Figures are preliminary and not for distribution. Total cloud spend for the quarter is tracking {p.int(3, 12)}% above plan.\n\n## Notes\nTeam leads should not share the detailed numbers outside finance and leadership."
    if key == "HR" or key == "REC":
        t = p.one(["Compensation bands", "Performance calibration notes", "Hiring plan by team", "Offer approvals", "Leave policy exceptions", "Reorganisation planning"])
        return f"{t} — confidential ({i})", f"## Confidential\nThis page contains personal and compensation information. Access is limited to People Operations and approved leaders.\n\n## Summary\nSummary of {t.lower()} for the current cycle."
    if key == "LEG":
        t = p.one(["Master services agreement review", "Data processing addendum", "Trademark filings", "Regulatory correspondence", "Contract renewal tracker"])
        return f"{t} ({i})", f"## Summary\nLegal review notes for {t.lower()}. Privileged and confidential.\n\n## Open issues\nTwo clauses remain under negotiation."
    if key == "SEC":
        t = p.one(["Pen-test findings", "Threat model", "Vulnerability triage", "Secrets exposure review", "Red team plan", "Detection engineering notes"])
        return f"{t} ({i})", f"## Scope\nSecurity team working notes for {t.lower()}. Distribution is limited to the security team.\n\n## Findings\nSeveral medium findings were triaged; remediation tickets are tracked in the SEC project."
    if key == "COMP":
        t = p.one(["SOC 2 evidence index", "PCI DSS scoping", "MAS notice tracker", "AML monitoring review", "Audit request list"])
        return f"{t} ({i})", f"## Overview\nCompliance working document for {t.lower()}.\n\n## Status\nEvidence collection is on schedule for the upcoming audit window."
    t = p.one(["Board materials", "Quarterly business review", "Strategy offsite notes", "Executive staff agenda"])
    return f"{t} ({i})", f"## Summary\nLeadership-only document: {t.lower()}. Contents are confidential."
