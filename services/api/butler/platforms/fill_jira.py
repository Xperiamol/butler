"""Jira 批量项目与问题。项目角色、Browse 权限、问题级安全级别都是真实语义；内容合成。"""
from __future__ import annotations
from .jira import Actors, Comment, Issue, JiraServer, Project, SecurityLevel
from .people import Directory
from .vocab import CAUSES, FEATURES, FIXES, PRIORITIES, SERVICES, STATUSES, SYMPTOMS, TECH, Pick, when

# (key, name, 开发组, 观察组, 权重, 受限项目?)
PROJECTS: list[tuple[str, str, set[str], set[str], int]] = [
    ("PAY", "Payments", {"payments-eng"}, {"engineering", "product", "support"}, 120), ("PGW", "Payment Gateway", {"payments-eng", "platform-eng"}, {"engineering", "product", "support"}, 110),
    ("PLAT", "Platform", {"platform-eng"}, {"engineering", "product"}, 100), ("AUTH", "Auth & Identity", {"auth-eng"}, {"engineering", "security", "product"}, 80),
    ("DATA", "Data Platform", {"data-eng"}, {"engineering", "product", "finance"}, 70), ("MOB", "Mobile", {"mobile-eng"}, {"engineering", "product", "design"}, 70),
    ("SRE", "Site Reliability", {"sre"}, {"engineering"}, 80), ("SEC", "Security", {"security"}, {"leadership"}, 90), ("ATLAS", "Atlas DB migration", {"platform-eng", "sre", "payments-eng"}, {"engineering", "leadership"}, 40),
    ("INC", "Incidents", {"sre", "payments-eng", "platform-eng"}, {"engineering", "security", "leadership"}, 60), ("OPS", "Business Operations", {"support", "sales"}, {"all-employees"}, 40),
    ("DEVX", "Developer Experience", {"platform-eng"}, {"engineering"}, 40), ("QA", "Quality", {"engineering"}, {"engineering", "product"}, 40), ("REL", "Release Engineering", {"platform-eng", "sre"}, {"engineering"}, 40),
    ("OBS", "Observability", {"sre", "platform-eng"}, {"engineering"}, 35), ("DBA", "Database Engineering", {"platform-eng", "data-eng"}, {"engineering"}, 40), ("ML", "ML & Risk", {"data-eng"}, {"engineering", "product", "compliance"}, 35),
    ("PRD", "Product", {"product"}, {"engineering", "design", "leadership", "sales", "support"}, 60), ("DSN", "Design", {"design"}, {"product", "engineering"}, 30),
    ("FIN", "Finance", {"finance"}, {"leadership"}, 25), ("LEGAL", "Legal", {"legal"}, {"leadership"}, 20), ("HR", "People Operations", {"people-ops"}, {"leadership"}, 25),
    ("SUP", "Support Escalations", {"support"}, {"engineering", "product"}, 55), ("SALES", "Sales Requests", {"sales"}, {"product", "leadership"}, 30), ("COMP", "Compliance", {"compliance"}, {"leadership", "security"}, 30),
    ("VEND", "Vendor Management", {"finance", "legal"}, {"leadership", "engineering"}, 25), ("ORION", "Project Orion", {"engineering"}, {"product", "design"}, 35),
    ("KITE", "Project Kite", {"mobile-eng", "payments-eng"}, {"product", "design"}, 35), ("NOVA", "Project Nova", {"payments-eng", "data-eng"}, {"product", "finance"}, 30),
    ("HELIOS", "Project Helios", {"payments-eng", "security"}, {"product", "compliance"}, 30), ("MERC", "Project Mercury", {"platform-eng", "payments-eng"}, {"product"}, 30),
    ("LYRA", "Project Lyra", {"data-eng", "security"}, {"product"}, 30), ("VEGA", "Project Vega", {"payments-eng", "finance"}, {"product"}, 30),
]
RESTRICTED = {"SEC", "FIN", "LEGAL", "HR", "COMP"}
HERO_ONLY = {"ATLAS"}   # 这个项目里只有手写的主角问题，不混入批量问题


def seed_projects(server: JiraServer, d: Directory) -> None:
    for key, name, dev, view, _ in PROJECTS:
        leads = [x.id for x in d.employees() if x.team in dev][:1]
        server.add_project(Project(
            key, name, leads[0] if leads else "sara",
            roles={"Administrators": Actors(set(leads[:1]), set()), "Developers": Actors(set(), set(dev)), "Viewers": Actors(set(), set(view) | ({"leadership"} if key not in RESTRICTED else set()))},
            browse_roles={"Administrators", "Developers", "Viewers"},
            levels={"Security Team": SecurityLevel("Security Team", groups={"security"}, roles={"Administrators"}),
                    "Leadership": SecurityLevel("Leadership", groups={"leadership"}, reporter_can_see=False),
                    "HR-Confidential": SecurityLevel("HR-Confidential", groups={"people-ops"}, reporter_can_see=False)}))


def _issue_text(p: Pick, kind: str, svc: str) -> tuple[str, str]:
    sym, cause, fix, tech, feat = p.one(SYMPTOMS), p.one(CAUSES), p.one(FIXES), p.one(TECH), p.one(FEATURES)
    if kind == "Bug":
        return (f"{svc}: {sym}", f"We observed {sym} on {svc}. Steps to reproduce: send a burst of requests while the dependency is slow. Expected: requests degrade gracefully. Actual: errors cascade. Suspected cause: {cause}.")
    if kind == "Story":
        return (f"Implement {feat}", f"As a merchant I want {feat} so that I can reduce manual work. Acceptance criteria: the flow works end to end in staging, is covered by tests, and has a runbook. Depends on {svc}.")
    if kind == "Epic":
        return (f"{feat.capitalize()} — epic", f"Umbrella ticket for {feat}. Child stories track design, implementation, rollout and documentation.")
    if kind == "Spike":
        return (f"Spike: evaluate {tech} for {svc}", f"Time-boxed investigation of {tech}. Output: a short write-up with a recommendation and risks.")
    return (f"{p.one(['Add', 'Upgrade', 'Tune', 'Clean up', 'Document'])} {tech} for {svc}", f"Routine task for {svc}. Context: after the last review we agreed to improve resilience. Fix applied in similar cases: {fix}.")


COMMENTS = ["Picked this up. Will have a PR by tomorrow.", "Reproduced locally. The issue is intermittent, so I added logging.", "Blocked on a review from the platform team.", "Deployed to staging, looks good.",
            "Linking the relevant dashboard and the Slack thread for context.", "Confirmed fixed in the latest release. Closing.", "We need product input on the acceptance criteria.", "Rolled back the change after seeing elevated errors.",
            "Updated the estimate after the design discussion.", "Added a test that covers the regression."]


def fill_issues(server: JiraServer, d: Directory, epoch: float, seed: int, scale: float = 1.0) -> int:
    p = Pick(seed)
    made = 0
    employees = [x for x in d.employees()]
    for key, name, dev, view, weight in PROJECTS:
        if key in HERO_ONLY:
            continue
        n = max(4, int(weight * scale))
        team = [x for x in employees if x.team in dev] or employees
        for i in range(1, n + 1):
            kind = p.one(["Bug", "Bug", "Story", "Story", "Task", "Task", "Task", "Spike", "Epic"])
            svc = p.one(SERVICES)
            summary, desc = _issue_text(p, kind, svc)
            created = when(epoch, p.between(2, 240))
            updated = created + 86400 * p.between(0, 30)
            updated = min(updated, epoch - 3600)
            issue = Issue(f"{key}-{i}", key, kind, summary, desc, p.one(STATUSES), p.one(PRIORITIES), p.one(team).id, p.one(team).id if p.chance(0.9) else None, created, updated,
                          labels=p.some(["backend", "frontend", "infra", "tech-debt", "customer", "p1", "security", "performance"], p.int(0, 2)), version=p.int(1, 6))
            for _ in range(p.int(0, 4)):
                issue.comments.append(Comment(p.one(team).id, p.one(COMMENTS), created + 86400 * p.between(0, 20)))
            if i > 3 and p.chance(0.3):
                issue.links.append((p.one(["relates to", "blocks", "is blocked by", "duplicates"]), f"{key}-{p.int(1, i - 1)}"))
            if key in {"SEC"} and p.chance(0.85):
                issue.security = "Security Team"
            elif key in {"HR"} and p.chance(0.7):
                issue.security = "HR-Confidential"
            elif key not in RESTRICTED and kind == "Bug" and "security" in issue.labels and p.chance(0.8):
                issue.summary = f"Vulnerability: {p.one(['SQL injection in', 'SSRF in', 'Insecure deserialization in', 'Missing authz check in', 'XSS in'])} {svc}"
                issue.description = f"Reported by the security team. {svc} is affected; details are restricted to the security team until a fix ships."
                issue.security = "Security Team"
                issue.reporter = p.one([x for x in employees if x.team == "security"]).id
            elif p.chance(0.01):
                issue.security = "Leadership"
            server.add_issue(issue)
            made += 1
    return made
