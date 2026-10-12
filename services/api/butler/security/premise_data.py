"""前提发现的训练数据：用"训练用事件类型"生成拼图链，真实手册当背景。

评测用的是 redteam.benchmark.KINDS 里的三类（收购/裁员/泄露），它们不出现在这里，所以测的是对新事件类型的泛化。
三种前提与结论的关联方式：
- both  ：碎片 A 提到代号，碎片 B 提到目标公司（结论两者都提）
- t2    ：两个碎片都提到目标公司
- c2    ：两个碎片都提到代号
"""
from __future__ import annotations
import random

KINDS = [
    {"secret": "Board minutes {c}: {t}'s chief executive will step down at the end of the quarter. Do not announce.",
     "statement": "The chief executive of {t} will step down",
     "a": {"c": "Project {c} leadership offsite was moved to a private venue.", "t": "{t} scheduled an unusual closed-door board session."},
     "b": {"c": "Project {c} recruiter search retained an executive search firm.", "t": "{t} deleted its executive biography page from the website."}},
    {"secret": "Pricing memo {c}: list prices for {t} will rise by 18 percent in January. Confidential.",
     "statement": "Prices for {t} will rise by 18 percent",
     "a": {"c": "Project {c} finance model was updated with new margin assumptions.", "t": "{t} sales were told to hold back quotes until next month."},
     "b": {"c": "Project {c} printing of new rate cards was approved.", "t": "{t} customer success asked for a list of annual renewals."}},
    {"secret": "Roadmap decision {c}: the {t} product line will be discontinued next year. Restricted.",
     "statement": "The {t} product line will be discontinued",
     "a": {"c": "Project {c} support runbooks were frozen for edits.", "t": "{t} marketing campaigns for next year were cancelled."},
     "b": {"c": "Project {c} migration guides are being drafted for customers.", "t": "{t} engineering backlog was archived this week."}},
    {"secret": "Audit {c}: auditors found a material weakness in the {t} revenue controls. Restricted until filing.",
     "statement": "Auditors found a material weakness in the {t} revenue controls",
     "a": {"c": "Audit {c} extra sampling requests were sent to the finance team.", "t": "{t} revenue reconciliations were escalated to the controller."},
     "b": {"c": "Audit {c} partner review was added to the calendar.", "t": "{t} month-end close was extended by three days."}},
    {"secret": "Legal note {c}: we will settle the {t} patent lawsuit for $12M. Privileged.",
     "statement": "The company will settle the {t} patent lawsuit",
     "a": {"c": "Case {c} outside counsel requested authority from the board.", "t": "{t} counsel proposed a mediation date."},
     "b": {"c": "Case {c} insurance carrier was notified of a possible payout.", "t": "{t} discovery deadlines were paused by mutual agreement."}},
    {"secret": "Compensation plan {c}: salaries for the {t} group are frozen for the next year. Restricted.",
     "statement": "Salaries for the {t} group are frozen",
     "a": {"c": "Plan {c} merit cycle communications were put on hold.", "t": "{t} managers were asked to pause promotion packets."},
     "b": {"c": "Plan {c} budget lines for raises were reallocated.", "t": "{t} offer approvals now require executive sign-off."}},
    {"secret": "Facilities decision {c}: the {t} office will close permanently in June. Do not share.",
     "statement": "The {t} office will close permanently",
     "a": {"c": "Site {c} lease counsel asked for the termination clauses.", "t": "{t} furniture vendors were asked for removal quotes."},
     "b": {"c": "Site {c} moving company walked through the floors.", "t": "{t} badge access was removed for visitors."}},
    {"secret": "Security advisory {c}: an unpatched remote code execution flaw affects the {t} gateway. Embargoed.",
     "statement": "An unpatched remote code execution flaw affects the {t} gateway",
     "a": {"c": "Advisory {c} emergency change window was requested.", "t": "{t} gateway traffic was moved behind an extra filter."},
     "b": {"c": "Advisory {c} patch review was assigned to a small group.", "t": "{t} gateway releases were paused without explanation."}},
]
PATTERNS = ("both", "t2", "c2")


def fragments(kind: dict, pattern: str, c: str, t: str) -> tuple[str, str]:
    a_key, b_key = {"both": ("c", "t"), "t2": ("t", "t"), "c2": ("c", "c")}[pattern]
    return kind["a"][a_key].format(c=c, t=t), kind["b"][b_key].format(c=c, t=t)


def make_chains(kinds: list[dict], n: int, seed: int, codenames: list[str], targets: list[str]) -> list[dict]:
    rng = random.Random(seed)
    cs, ts = rng.sample(codenames, n), rng.sample(targets, n)
    out = []
    for i in range(n):
        k, pat = kinds[i % len(kinds)], PATTERNS[(i // len(kinds)) % len(PATTERNS)]
        a, b = fragments(k, pat, cs[i], ts[i])
        out.append({"id": i, "secret": k["secret"].format(c=cs[i], t=ts[i]), "statement": k["statement"].format(c=cs[i], t=ts[i]),
                    "a": a, "b": b, "pattern": pat, "codename": cs[i], "target": ts[i]})
    return out
