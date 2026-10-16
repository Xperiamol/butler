"""Drive 批量共享盘、文件夹和文件：文档 / 表格 / 幻灯片的文字内容；共享设置包含用户、组、全公司、任何人、受限访问。"""
from __future__ import annotations
from .base import Attachment
from .drive import DriveFile, DriveServer, Folder, Perm, SharedDrive
from .people import Directory
from .vocab import FEATURES, SERVICES, TECH, Pick, when

DRIVES: list[tuple[str, str, set[str], str]] = [   # id, 名称, 成员组, 成员角色
    ("SD-ENG", "Engineering", {"engineering"}, "writer"), ("SD-FIN", "Finance", {"finance-and-leadership"}, "writer"), ("SD-LEG", "Legal", {"legal"}, "writer"),
    ("SD-HR", "People", {"people-ops"}, "writer"), ("SD-EXEC", "Leadership", {"leadership"}, "writer"), ("SD-PRD", "Product & Design", {"product", "design"}, "writer"),
    ("SD-SEC", "Security", {"security"}, "writer"), ("SD-SALES", "Sales", {"sales"}, "writer"), ("SD-ALL", "Company-wide", {"all-employees"}, "reader"),
    ("SD-COMP", "Compliance", {"compliance"}, "writer"), ("SD-SUP", "Support", {"support"}, "writer"), ("SD-DATA", "Data", {"data-eng"}, "writer"),
]
FOLDERS = ["Planning", "Reports", "Meeting notes", "Reference", "Archive", "Templates", "Decks", "Research"]
SHEET_TOPICS = ["Q4 capacity plan", "Cloud cost by service", "Hiring pipeline", "Vendor spend tracker", "Incident metrics", "Merchant churn cohort", "OKR tracker", "Latency budget by endpoint"]
DECK_TOPICS = ["Quarterly business review", "Platform roadmap", "Security awareness", "Merchant onboarding results", "Architecture overview", "Customer advisory board"]
DOC_TOPICS = ["Meeting notes", "Project brief", "Research summary", "Process write-up", "Retro summary", "Launch checklist", "Partner proposal"]


def seed_drives(server: DriveServer, d: Directory) -> None:
    groups = d.groups()
    for did, name, gs, role in DRIVES:
        members = {pid: role for g in gs for pid in groups.get(g, set())}
        server.add_drive(SharedDrive(did, name, members))


def _table(p: Pick, rows: int, cols: list[str]) -> str:
    head = "| " + " | ".join(cols) + " |"
    lines = [head, "|" + "---|" * len(cols)]
    for i in range(rows):
        lines.append("| " + " | ".join([f"{p.one(SERVICES)}" if c == "Service" else f"{p.int(1, 99)}%" if "%" in c else f"{p.int(10, 900)}" for c in cols]) + " |")
    return "\n".join(lines)


def fill_files(server: DriveServer, d: Directory, epoch: float, seed: int, scale: float = 1.0) -> int:
    p = Pick(seed)
    made = 0
    people = [x.id for x in d.employees()]
    fid = 0
    for did, name, gs, role in DRIVES:
        folders = []
        for k, fname in enumerate(p.some(FOLDERS, 4)):
            f = Folder(f"fo-{did}-{k}", fname, None, did, "")
            server.add_folder(f)
            folders.append(f)
        for _ in range(int(p.int(45, 80) * scale)):
            folder = p.one(folders)
            kind = p.one(["doc", "doc", "sheet", "slides", "doc", "sheet"])
            ts = when(epoch, p.between(1, 300))
            if kind == "sheet":
                topic = p.one(SHEET_TOPICS)
                title, mime = f"{topic} ({p.one(['FY26', 'Q3', 'Q4', 'H1'])})", "application/vnd.google-apps.spreadsheet"
                text = f"Sheet: {topic}\n\n" + _table(p, 8, ["Service", "Owner team", "Utilisation %", "Cost (USD k)"])
            elif kind == "slides":
                topic = p.one(DECK_TOPICS)
                title, mime = f"{topic} — deck", "application/vnd.google-apps.presentation"
                text = f"Slide 1: {topic}\nSlide 2: Goals and context — we want to improve {p.one(FEATURES)} while keeping reliability high.\nSlide 3: Where we are — progress on {p.one(SERVICES)} and {p.one(TECH)}.\nSlide 4: Risks and asks.\nSpeaker notes: keep the discussion on decisions, not status."
            else:
                topic = p.one(DOC_TOPICS)
                title, mime = f"{topic}: {p.one(FEATURES)}", "application/vnd.google-apps.document"
                text = f"{topic}\n\nSummary: we reviewed {p.one(FEATURES)} and agreed on next steps. Owner: {p.one(people)}. Related service: {p.one(SERVICES)}.\n\nDecisions\n- Prioritise reliability work before new features.\n- Review again in two weeks."
            owner = p.one(people)
            perms: list[Perm] = []
            limited = False
            r = p.r.random()
            if r < 0.04:
                perms.append(Perm("anyone", "", "reader"))                              # 任何知道链接的人
            elif r < 0.12:
                perms.append(Perm("domain", "", "reader"))                              # 全公司可看
            elif r < 0.22:
                perms.append(Perm("user", p.one(people), "commenter"))
            elif r < 0.26:
                limited = True                                                            # 受限访问：只有显式共享的人
                perms.append(Perm("user", owner, "writer"))
                perms.append(Perm("user", p.one(people), "reader"))
            server.add_file(DriveFile(f"f{fid:05d}", title, mime, folder.id, did, owner, ts - 86400 * p.int(0, 60), ts, text, perms, limited, version=p.int(1, 8)))
            fid += 1
            made += 1
    # 个人 My Drive：个人文件，只共享给指定的人
    for owner in p.some(people, 22):
        for _ in range(p.int(6, 14)):
            ts = when(epoch, p.between(1, 200))
            topic = p.one(DOC_TOPICS)
            perms = [Perm("user", owner, "writer")]
            if p.chance(0.5):
                perms.append(Perm("user", p.one(people), "reader"))
            if p.chance(0.15):
                perms.append(Perm("group", p.one(["engineering", "product", "support"]), "reader"))
            server.add_file(DriveFile(f"f{fid:05d}", f"{topic}: {p.one(FEATURES)} (draft)", "application/vnd.google-apps.document", None, None, owner, ts - 86400 * 10, ts,
                                      f"Draft notes on {p.one(FEATURES)}. Not for wide distribution.", perms, True, version=p.int(1, 4)))
            fid += 1
            made += 1
    return made
