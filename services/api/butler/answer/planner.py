"""查询规划：把一个自然语言问题变成“聚焦的子查询 + 要查哪些平台 + 时间意图”。

为什么需要：企业里的问法是“数据库迁移项目现在什么状态，上周 Slack 里有没有人提阻塞？”，
词法检索会被“上周、Slack、阻塞”这类泛词拉低覆盖率，且“迁移”和文档里的 migrate / Aurora / Atlas 对不上。
规划器（小模型，没有模型时退回规则）给出同义词、项目名、英文术语，并决定去 Jira / Slack / Confluence / Drive 的哪些平台查。
规划只看问题文本，不看任何资料，所以不会把受限内容带进检索。
"""
from __future__ import annotations
import hashlib
import json
import re
from dataclasses import dataclass, field

from .remote import ModelFailure, RemoteModel, parse_json_object

PLATFORMS = ("confluence", "jira", "slack", "drive")
_CJK = re.compile(r"[一-鿿]")


@dataclass
class Plan:
    queries: list[str] = field(default_factory=list)
    platforms: list[str] = field(default_factory=lambda: list(PLATFORMS))
    recency: bool = False
    days: int | None = None
    source: str = "rules"          # rules | llm


_HINTS = {
    "jira": r"\b(ticket|tickets|issue|issues|jira|bug|bugs|sprint|epic|backlog|story|follow-?ups?)\b|工单|问题单|缺陷|迭代",
    "slack": r"\b(slack|thread|threads|channel|channels|discussion|discussed|chat|message|messages|dm|conversation)\b|讨论|线程|频道|聊天|消息",
    "confluence": r"\b(wiki|confluence|runbook|runbooks|doc|docs|decision|adr|page|pages|postmortem|playbook|handbook|design doc)\b|文档|决策|手册|复盘|页面",
    "drive": r"\b(file|files|sheet|spreadsheet|deck|slides|drive|pdf|screenshot|image|diagram|picture|photo|whiteboard|recording|audio|contract|scan|scanned|presentation)\b|文件|表格|幻灯片|截图|图片|合同|录音|白板|架构图",
}
_RECENT = re.compile(r"\b(latest|newest|current|most recent|up to date|now)\b|最新|最近|当前", re.I)
_DAYS = [(r"yesterday|昨天", 2), (r"last week|past week|上周|最近一周", 7), (r"last sprint|上个迭代|上一个迭代", 14), (r"last month|past month|上个月|最近一个月", 31), (r"last quarter|上季度|上一季度", 100), (r"this week|本周", 7), (r"last 30 days|past 30 days", 31)]
_STOP = set("the a an is are was were be to of and or in on for with at by from as it this that what which who how do does me my about tell show summarize summarise explain give list find please there any has have any were been being their there between from into over under last next new and then than also just not but if when where why can could would should will shall may might i we our your you they them his her its".split()) | set("discussion discussions threads thread status latest current".split())


def rule_plan(question: str) -> Plan:
    q = question.lower()
    hits = [p for p, rx in _HINTS.items() if re.search(rx, q)]
    words = [w for w in re.findall(r"[a-z0-9][a-z0-9\-_.]+|[一-鿿]{2,}", q) if w not in _STOP]
    keywords = " ".join(dict.fromkeys(words))[:160]
    days = next((d for rx, d in _DAYS if re.search(rx, q)), None)
    queries = [question] + ([keywords] if keywords and keywords != q else [])
    return Plan(queries, hits if 0 < len(hits) < 4 else list(PLATFORMS), bool(_RECENT.search(question)), days, "rules")


PROMPT = (
    "You are the query planner of an enterprise knowledge assistant. The company keeps knowledge in Confluence (wiki pages, runbooks, decision docs, postmortems), "
    "Jira (tickets), Slack (threads) and Google Drive (docs, sheets, slides, PDFs, images, recordings). Given the user's question, return ONLY a JSON object:\n"
    '{"queries": [2 to 5 short search queries (3-8 words each) that would find the relevant material; include synonyms, project or system names you can infer, and English technical terms even if the question is Chinese], '
    '"platforms": [subset of "confluence","jira","slack","drive" that are relevant; all four if unsure], '
    '"recency": true if the user wants the latest/current version, "days": number of days of the time window if the question has one (last week=7, last sprint=14, last month=31, last quarter=100) else null}\n'
    "Today is {today}. Do not answer the question."
)


class Planner:
    def __init__(self, model: RemoteModel | None, today: str = ""):
        self.model, self.today = model, today
        self.cache: dict[str, Plan] = {}

    def __call__(self, question: str) -> Plan:
        key = hashlib.sha256(question.strip().lower().encode()).hexdigest()
        if key in self.cache:
            return self.cache[key]
        base = rule_plan(question)
        plan = base
        if self.model is not None:
            try:
                data = parse_json_object(self.model.complete(PROMPT.replace("{today}", self.today or "unknown"), question))
                qs = [str(x).strip() for x in data.get("queries", []) if str(x).strip()][:5]
                plats = [p for p in data.get("platforms", []) if p in PLATFORMS] or list(PLATFORMS)
                days = data.get("days")
                plan = Plan([question] + qs, plats, bool(data.get("recency")) or base.recency, int(days) if isinstance(days, (int, float)) and days > 0 else base.days, "llm")
            except (ModelFailure, ValueError, AttributeError, TypeError):
                plan = base          # 规划失败不影响回答：退回规则
        if len(self.cache) > 500:
            self.cache.clear()
        self.cache[key] = plan
        return plan
