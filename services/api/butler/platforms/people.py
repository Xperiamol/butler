"""模拟公司的人员目录：员工、外包、各平台账号。确定性生成（固定随机种子），同一份目录驱动四个平台模拟器。

不变量：平台里的权限只引用“人员 id / 组名”；平台账号与本地成员的对应关系集中在这里（Person），连接器和权限解析器都从这里查。
"""
from __future__ import annotations
import random
from dataclasses import dataclass, field

COMPANY = "Tidepool Pay"
DOMAIN = "tidepool.example"

# (team, headcount, title pool)
TEAMS: list[tuple[str, int, list[str]]] = [
    ("payments-eng", 14, ["Backend Engineer", "Senior Backend Engineer", "Staff Engineer", "Engineering Manager"]),
    ("platform-eng", 12, ["Platform Engineer", "Senior Platform Engineer", "Staff Engineer"]),
    ("auth-eng", 8, ["Backend Engineer", "Security-minded Engineer", "Senior Engineer"]),
    ("data-eng", 9, ["Data Engineer", "Analytics Engineer", "Senior Data Engineer"]),
    ("mobile-eng", 8, ["iOS Engineer", "Android Engineer", "Mobile Lead"]),
    ("sre", 8, ["Site Reliability Engineer", "Senior SRE", "SRE Manager"]),
    ("security", 7, ["Security Engineer", "Security Analyst", "Head of Security"]),
    ("product", 10, ["Product Manager", "Senior Product Manager", "Product Analyst"]),
    ("design", 6, ["Product Designer", "UX Researcher", "Design Lead"]),
    ("finance", 8, ["Financial Analyst", "Accountant", "FP&A Manager"]),
    ("legal", 4, ["Legal Counsel", "Contracts Manager"]),
    ("people-ops", 5, ["HR Business Partner", "Recruiter", "People Ops Manager"]),
    ("support", 10, ["Support Specialist", "Support Lead"]),
    ("sales", 10, ["Account Executive", "Solutions Engineer", "Sales Manager"]),
    ("compliance", 3, ["Compliance Officer", "Risk Analyst"]),
    ("leadership", 6, ["CEO", "CTO", "CFO", "VP Product", "VP Engineering", "COO"]),
]
ENG_TEAMS = {"payments-eng", "platform-eng", "auth-eng", "data-eng", "mobile-eng", "sre"}

_FIRST = ("Wei Li Mei Hui Ahmad Siti Nur Arun Priya Vikram Ananya David Emma Olivia Lucas Noah Sofia Daniel Grace Hannah Ivan Jasmine Kai Lena Marcus "
          "Nina Owen Pia Quinn Ravi Sophie Tariq Uma Victor Wendy Xin Yusuf Zara Aisha Bryan Chloe Dev Elena Farid Gina Hugo Iris Jun Kiran Leon "
          "Mira Nathan Orla Paul Rui Sana Theo Una Vera Will Yan Zhi").split()
_LAST = ("Tan Lim Ng Wong Chen Lee Liu Goh Teo Koh Ong Chua Sim Yeo Ho Patel Kumar Singh Rahman Hassan Ismail Abdullah Nair Menon Gupta Smith "
         "Brown Wilson Taylor Martin Fernandez Dubois Kim Park Nguyen Tran").split()


@dataclass
class Person:
    id: str
    name: str
    team: str
    title: str
    kind: str = "employee"          # employee | contractor
    featured: bool = False
    role: str = "employee"          # Butler 工作区角色
    legacy_groups: tuple[str, ...] = ()   # 早期示例资料用的组名（eng / pm / leadership …）

    @property
    def email(self) -> str:
        return f"{self.id}@{DOMAIN}" if self.kind == "employee" else f"{self.id}@contractor.example"

    @property
    def slack_id(self) -> str:
        return "U" + self.id.upper()[:8].ljust(6, "0")

    @property
    def confluence_id(self) -> str:
        return f"cf-{self.id}"

    @property
    def jira_id(self) -> str:
        return f"jira-{self.id}"


# 固定的演示账号：登录页展示这几个，评委用例都围绕它们
FEATURED = [
    Person("alice", "Alice Tan", "payments-eng", "Senior Backend Engineer", role="engineer", featured=True, legacy_groups=("eng", "payments")),
    Person("ken", "Ken Lim", "contractors", "External Contractor", kind="contractor", role="contractor", featured=True, legacy_groups=("contractors",)),
    Person("sara", "Sara Ng", "security", "Security Engineer", role="security", featured=True, legacy_groups=("security", "eng")),
    Person("pete", "Pete Wong", "leadership", "VP Product", role="pm", featured=True, legacy_groups=("pm", "eng", "leadership")),
    Person("amy", "Amy Chen", "compliance", "Compliance Officer", role="compliance", featured=True, legacy_groups=("auditors",)),
    Person("jdoe", "John Doe", "payments-eng", "Junior Backend Engineer", role="engineer", featured=True, legacy_groups=("eng", "payments")),
    Person("mliu", "Maya Liu", "platform-eng", "Backend Engineer", role="engineer", featured=True, legacy_groups=("eng",)),
    Person("raj", "Raj Patel", "sre", "Site Reliability Engineer (on-call)", role="engineer", featured=True, legacy_groups=("eng",)),
]
NAMED_LEADERS = [("grace", "Grace Koh", "CFO"), ("daniel", "Daniel Ong", "CTO"), ("olivia", "Olivia Sim", "CEO"), ("marcus", "Marcus Yeo", "VP Engineering"), ("hannah", "Hannah Ho", "COO")]


def build_people(seed: int = 7) -> list[Person]:
    rng = random.Random(seed)
    people: dict[str, Person] = {p.id: p for p in FEATURED}
    taken_names = {p.name for p in FEATURED}
    for pid, name, title in NAMED_LEADERS:
        people[pid] = Person(pid, name, "leadership", title, role="pm", legacy_groups=("pm", "eng", "leadership"))
        taken_names.add(name)
    counts = {t: sum(1 for p in people.values() if p.team == t) for t, _, _ in TEAMS}
    for team, size, titles in TEAMS:
        while counts[team] < size:
            name = f"{rng.choice(_FIRST)} {rng.choice(_LAST)}"
            if name in taken_names:
                continue
            taken_names.add(name)
            pid = name.split()[0].lower()
            while pid in people:
                pid = (name.split()[0] + name.split()[1][0]).lower() if pid == name.split()[0].lower() else pid + str(rng.randint(2, 99))
            legacy = ("eng",) if team in ENG_TEAMS else ("pm",) if team == "product" else ("security", "eng") if team == "security" else ("auditors",) if team == "compliance" else ()
            people[pid] = Person(pid, name, team, rng.choice(titles), role="engineer" if team in ENG_TEAMS else "employee", legacy_groups=legacy)
            counts[team] += 1
    for i in range(1, 4):   # 另外三位外包
        pid = f"vendor{i}"
        people[pid] = Person(pid, f"Contractor {i}", "contractors", "External Contractor", kind="contractor", role="contractor", legacy_groups=("contractors",))
    return list(people.values())


@dataclass
class Directory:
    people: list[Person]
    by_id: dict[str, Person] = field(init=False)

    def __post_init__(self):
        self.by_id = {p.id: p for p in self.people}

    def team(self, name: str) -> list[Person]:
        return [p for p in self.people if p.team == name]

    def employees(self) -> list[Person]:
        return [p for p in self.people if p.kind == "employee"]

    def groups(self) -> dict[str, set[str]]:
        """组名 → 成员 id。组 = 团队 + 几个跨团队组。"""
        g: dict[str, set[str]] = {t: {p.id for p in self.team(t)} for t, _, _ in TEAMS}
        g["contractors"] = {p.id for p in self.people if p.kind == "contractor"}
        g["all-employees"] = {p.id for p in self.employees()}
        g["engineering"] = {p.id for p in self.people if p.team in ENG_TEAMS}
        g["incident-responders"] = g["sre"] | g["security"] | {"alice", "raj"}
        g["finance-and-leadership"] = g["finance"] | g["leadership"]
        return g


def directory(seed: int = 7) -> Directory:
    return Directory(build_people(seed))
