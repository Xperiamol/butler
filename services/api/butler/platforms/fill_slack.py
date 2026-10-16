"""Slack 批量频道与线程：公开频道、私有频道、群聊/私信；合作伙伴工作区里放外包人员。线程内容从对话模板生成。"""
from __future__ import annotations
from .people import Directory, ENG_TEAMS
from .slack import Channel, Message, SlackServer, Workspace
from .vocab import CAUSES, CHANNEL_WORDS, FEATURES, FIXES, SERVICES, SYMPTOMS, TECH, TEAM_TOPICS, Pick, when

PUBLIC_TEAMS = ["payments", "platform", "auth", "data", "mobile", "sre", "security-public", "product", "design", "finance-public", "support", "sales", "people", "compliance-public"]
PRIVATE_NAMES = ["leadership", "exec-staff", "hr-ops", "finance-close", "legal-contracts", "compliance-audit", "payments-leads", "sre-oncall-private", "sec-detections",
                 "people-comp", "board-prep", "m-and-a-ideas", "layoffs-planning", "vendor-negotiations", "platform-leads", "data-privacy-office"]


def seed_workspaces(server: SlackServer, d: Directory) -> None:
    server.add_workspace(Workspace("T001", "tidepool", {x.id for x in d.employees()}))
    server.add_workspace(Workspace("T002", "tidepool-partners", {x.id for x in d.people if x.kind == "contractor"} | {"alice", "sara", "pete"}, set()))


def _team_members(d: Directory, team_key: str) -> set[str]:
    m = {"payments": "payments-eng", "platform": "platform-eng", "auth": "auth-eng", "data": "data-eng", "mobile": "mobile-eng", "sre": "sre", "security-public": "security",
         "product": "product", "design": "design", "finance-public": "finance", "support": "support", "sales": "sales", "people": "people-ops", "compliance-public": "compliance"}[team_key]
    return {x.id for x in d.team(m)}


def seed_channels(server: SlackServer, d: Directory, epoch: float, seed: int) -> None:
    p = Pick(seed)
    n = 0
    # 公开频道
    for team in PUBLIC_TEAMS:
        for word in p.some(CHANNEL_WORDS, 6):
            server.add_channel(Channel(f"C{n:04d}", f"{team}-{word}", "T001", "public", _team_members(d, team) | set(p.some([x.id for x in d.employees()], 3)), f"{team} {word}", 365))
            n += 1
    for name in ["incidents", "deploys", "general", "random", "announcements", "help-it", "help-data", "help-security", "new-joiners", "kudos", "lunch", "singapore-office", "reading-club", "oncall-handoff", "release-train", "ask-engineering", "ask-product"]:
        server.add_channel(Channel(f"C{n:04d}", name, "T001", "public", set(), name.replace("-", " "), 365))
        n += 1
    for proj in ["orion", "kite", "nova", "helios", "mercury", "lyra", "vega"]:
        server.add_channel(Channel(f"C{n:04d}", f"proj-{proj}", "T001", "public", set(p.some([x.id for x in d.employees() if x.team in ENG_TEAMS | {"product"}], 12)), f"Project {proj}", 365))
        n += 1
    for s in SERVICES[:20]:
        server.add_channel(Channel(f"C{n:04d}", f"svc-{s}", "T001", "public", set(p.some([x.id for x in d.employees() if x.team in ENG_TEAMS], 8)), f"{s} owners and consumers", 365))
        n += 1
    # 私有频道
    leaders = {x.id for x in d.team("leadership")}
    for name in PRIVATE_NAMES:
        members = leaders | set(p.some([x.id for x in d.employees()], 3))
        if "hr" in name or "people" in name:
            members = {x.id for x in d.team("people-ops")} | {"pete", "olivia"}
        if "finance" in name or "board" in name or "m-and-a" in name:
            members = {x.id for x in d.team("finance")[:3]} | {"grace", "olivia", "pete"}
        if "legal" in name or "vendor" in name:
            members = {x.id for x in d.team("legal")} | {"grace", "daniel"}
        if "compliance" in name or "privacy" in name:
            members = {x.id for x in d.team("compliance")} | {"sara", "daniel"}
        if "sre" in name or "detections" in name:
            members = {x.id for x in d.team("sre" if "sre" in name else "security")}
        server.add_channel(Channel(f"C{n:04d}", name, "T001", "private", members, "private", 365))
        n += 1
    for team in ["payments-eng", "platform-eng", "auth-eng", "data-eng", "mobile-eng", "sre", "security", "product", "support", "sales", "finance"]:
        for word in p.some(["leads", "oncall", "retro", "hiring", "planning"], 2):
            server.add_channel(Channel(f"C{n:04d}", f"{team}-{word}-private", "T001", "private", {x.id for x in d.team(team)[:6]}, "private", 365))
            n += 1
    while sum(1 for c in server.channels.values() if c.kind == "private") < 45:
        server.add_channel(Channel(f"C{n:04d}", f"proj-{p.one(['x', 'y', 'z'])}-{n}-private", "T001", "private", set(p.some([x.id for x in d.employees()], 6)), "private", 365))
        n += 1
    # 私信 / 群聊
    ids = [x.id for x in d.employees()]
    for i in range(32):
        a, b = p.some(ids, 2)
        kind = "im" if i % 4 else "mpim"
        mem = {a, b} if kind == "im" else {a, b, p.one(ids)}
        server.add_channel(Channel(f"D{n:04d}", f"dm-{a}-{b}", "T001", kind, mem, "", 90))
        n += 1
    # 合作伙伴工作区
    contractors = {x.id for x in d.people if x.kind == "contractor"}
    for name in ["partner-help", "contractor-announcements", "vendor-sync", "onboarding-contractors", "partner-bugs", "partner-releases"]:
        server.add_channel(Channel(f"C{n:04d}", name, "T002", "public", contractors | {"alice", "sara"}, name.replace("-", " "), 180))
        n += 1
    for name in ["acme-integration", "vendor-escalations"]:
        server.add_channel(Channel(f"C{n:04d}", name, "T002", "private", {"ken", "alice"}, "private", 180))
        n += 1


_STARTERS = [
    ("Heads-up: deploying {svc} v{ver} to production in 30 minutes. Main change: {feat}.", ["Looks good, I'll keep an eye on the dashboards.", "Approved from my side.", "Rollout complete, no errors so far."]),
    ("Anyone seen {sym} on {svc} today? Trying to figure out if it's related to the last release.", ["Saw it earlier too. Might be {cause}.", "Can you share the trace link?", "We hit the same thing last month, the fix was: {fix}."]),
    ("Question: what's the right way to {howto}? The wiki page seems outdated.", ["I updated the runbook last week, let me link it.", "Short answer: use the helper script and open a ticket.", "Thanks, that worked!"]),
    ("PR ready for review: {feat} for {svc}. It touches the {tech} integration.", ["Left a few comments.", "Reviewed, one nit about naming.", "Merged."]),
    ("Retro notes: we agreed to prioritise stability this sprint. Biggest pain was {cause}.", ["+1, adding a ticket.", "Let's also review alerting thresholds."]),
    ("Incident update: {sym} on {svc}. Investigating. Next update in 15 minutes.", ["Mitigation in progress: {fix}.", "Resolved. Writing the postmortem.", "Thanks everyone for the quick response."]),
    ("Design question for {feat}: should we use {tech} or keep the current approach?", ["I'd keep it simple for v1.", "Let's write a short ADR so we capture the trade-offs.", "Agree, ADR it is."]),
    ("FYI the {svc} dashboards moved to a new folder in Grafana. Old links will redirect for a month.", ["Thanks!", "Updated my bookmarks."]),
]
_CHATTER = ["Lunch at the usual place?", "Congrats on the launch!", "Reminder: office closed on Friday for the public holiday.", "Anyone up for a book club this month?", "Standup in 5.", "Coffee run, who's in?", "Thanks for the help earlier!"]


def fill_threads(server: SlackServer, d: Directory, epoch: float, seed: int, scale: float = 1.0) -> int:
    p = Pick(seed)
    made = 0
    per_channel = {"public": 14, "private": 10, "mpim": 6, "im": 6}
    for c in list(server.channels.values()):
        members = sorted(c.members) or [x.id for x in d.employees()]
        n = max(2, int(per_channel[c.kind] * scale * p.between(0.5, 1.5)))
        for _ in range(n):
            ts = when(epoch, p.between(0.2, 150 if c.retention_days is None or c.retention_days >= 150 else c.retention_days))
            if c.name in {"general", "random", "kudos", "lunch", "singapore-office", "reading-club"} or p.chance(0.15):
                server.add_message(c.id, Message(ts, p.one(members), p.one(_CHATTER)))
                made += 1
                continue
            start, replies = p.one(_STARTERS)
            fmt = dict(svc=p.one(SERVICES), ver=f"{p.int(1, 4)}.{p.int(0, 30)}.{p.int(0, 9)}", feat=p.one(FEATURES), sym=p.one(SYMPTOMS), cause=p.one(CAUSES), fix=p.one(FIXES), tech=p.one(TECH), howto=p.one(["rotate a credential", "roll back a release", "replay a webhook", "run a load test", "restore a snapshot"]))
            root = Message(ts, p.one(members), start.format(**fmt))
            server.add_message(c.id, root)
            for k, r in enumerate(replies[: p.int(1, len(replies))]):
                server.add_message(c.id, Message(ts + 60 * (k + 1) * p.int(1, 20), p.one(members), r.format(**fmt), thread_ts=ts))
            made += 1
    return made
