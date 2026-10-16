"""面向提问者的固定文案：按提问语言（有汉字就是中文，否则英文）选。措辞刻意中性：
“没有找到”与“找到了但你无权看”说法完全一样，不透露受限内容是否存在。"""
from __future__ import annotations
import re

_CJK = re.compile(r"[一-鿿]")

ZH = {
    "no_evidence": "没有找到你有权查看的相关资料，所以不作回答。",
    "needs_approval": "这个问题的回答，加上之前已经给你的资料，会得出一项需要授权才能知道的结论，所以暂不放行。如果工作确有需要，可以申请授权；批准后在有效期内可以继续提问。",
    "unverified": "生成的回答无法对应到你有权查看的资料，所以不作回答。",
    "refused": "这个问题的完整回答可能涉及你无权知道的结论，所以不作回答。",
    "greeting": "你好，我是 Butler。可以直接问工作上的问题，比如“支付 API 限流是多少？”。我会按你的权限查资料，并告诉你答案出自哪份资料。",
    "degraded_prefix": "以下只列出你有权查看的事实，不做进一步推断：\n",
}
EN = {
    "no_evidence": "I couldn't find relevant information in the sources available to you.",
    "needs_approval": "Answering this would combine what you already have access to into a conclusion that requires authorization, so I can't release it yet. If you need it for your work, you can request access; once approved you can ask again within the approved window.",
    "unverified": "I couldn't tie the generated answer to sources available to you, so I'm not releasing it.",
    "refused": "A complete answer to this may involve information you don't have access to, so I can't answer it.",
    "greeting": "Hi, I'm Butler. Ask me a work question, for example “What's the status of the database migration?”. I answer from the sources you have access to and cite where each answer comes from.",
    "degraded_prefix": "Only the facts you have access to are listed below, without further inference:\n",
}


def lang_of(question: str) -> str:
    return "zh" if _CJK.search(question or "") else "en"


def msg(key: str, question: str) -> str:
    return (ZH if lang_of(question) == "zh" else EN)[key]
