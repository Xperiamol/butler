"""主角场景（二）：Q3 安全事件、法务/财务、合作伙伴与外包、应用安全指南、私信。"""
from __future__ import annotations
from . import media
from .base import Attachment
from .drive import Perm
from .hero import Ctx, _img, _pdf
from .vocab import date


def add_security_and_business(c: Ctx) -> None:
    ep, T = c.epoch, c.T
    sara, daniel, olivia, amy, ken, alice, jdoe, pete, grace = "sara", "daniel", "olivia", "amy", "ken", "alice", "jdoe", "pete", "grace"
    sec2, sec3 = T("security", 1), T("security", 2)
    breach_date = date(ep - 29 * 86400)

    # ================= 场景 3：Q3 安全事件（只有安全团队 / 少数领导能看）=================
    bt = _img("q3-breach-timeline.png", media.timeline("INC-SEC-0917 — breach timeline (CONFIDENTIAL)", [("Leaked API key pushed to public repo", 0, 1, "done"), ("Credential stuffing begins on merchant portal", 1, 2, "blocked"), ("Detection: anomalous login rate", 2, 3, "done"),
                                                                                                       ("Containment: key revoked, WAF rule", 3, 4, "done"), ("MAS notification (within 14h)", 3, 5, "done"), ("Customer notifications (3,412 merchants)", 4, 6, "done"), ("Forensics and post-incident review", 5, 8, "active")], 8, 6,
                                                                                                      "Distribution: security team only"), "Q3 breach forensic timeline")
    c.page("9200", "SEC", "Q3 Security Incident Report — INC-SEC-0917 (CONFIDENTIAL)", f"## Summary\nOn {breach_date} between 02:40 and 05:15 SGT an attacker ran a credential-stuffing campaign against the merchant portal login. **3,412 merchant accounts were accessed**. No card data or payout details were exposed; 214 accounts had their contact email viewed.\n\n"
           "## Root cause\nAn internal API key used by a monitoring script was committed to a public GitHub repository by a contractor on 2026-09-09. The key allowed the attacker to bypass the login rate limiter.\n\n## Timeline (SGT)\n- 02:40 attack begins\n- 03:05 anomaly alert for login success rate\n- 03:20 on-call security confirms credential stuffing\n- 03:45 API key revoked; WAF rule deployed\n- 05:15 attack traffic ends\n- 16:30 notification to MAS (within the 14-hour window)\n- Next day: notification emails to 3,412 merchants\n\n"
           "## Impact\n3,412 accounts accessed; 214 contact emails viewed; 0 fraudulent payouts. Estimated cost USD 86k (forensics, notification, credits).\n\n## Remediation\n- SEC-212 Rotate all internal API keys and enforce secret scanning pre-commit (Done)\n- SEC-213 Enforce MFA for merchant portal admin roles (In Progress)\n- SEC-214 Rate limiter must not be bypassable by service keys (In Progress)\n\n## Distribution\nSecurity team, CTO and CEO only. Do not share externally.", sara, 28, atts=[bt], version=6, links=["SEC-212", "SEC-213", "SEC-214"])
    for k, (summ, st) in enumerate([("Rotate all internal API keys and enforce secret scanning pre-commit", "Done"), ("Enforce MFA for merchant portal admin roles", "In Progress"), ("Rate limiter must not be bypassable by service keys", "In Progress")], 212):
        c.issue(f"SEC-{k}", summ, f"Follow-up from INC-SEC-0917 (Q3 breach, {breach_date}). Security-sensitive: details restricted.", st, "Highest", sara, sec2, 20, [(sara, 20, "Tracked in the Q3 incident report.")], security="Security Team")
    c.chan("CH-SECQ3", "sec-incident-q3", {sara, sec2, sec3, daniel, olivia}, "private", topic="Q3 incident — security team only")
    c.thread("CH-SECQ3", 29, 3.4, (sara, "Confirmed credential stuffing against the merchant portal. Success rate looks wrong. The login rate limiter is being bypassed with a service key. Revoking the key now."), [(sec2, "Key found in a public repo, committed by a contractor on 09-09. Revoked."), (daniel, "Draft the MAS notification. We have 14 hours."), (olivia, "Keep me posted. Customer comms need legal review.")])
    c.drive("fH-FORENSICS", "Q3 breach forensic report (scan)", "application/pdf", "SD-SEC", sara, 25, "", limited=True, att=_pdf("q3-forensics-report.pdf", media.scan_pages([["INC-SEC-0917 forensic summary", "Attack vector: leaked API key (monitoring script) in a public repository.", "Accounts accessed: 3,412. Contact emails viewed: 214. Payout data viewed: none.", "Attacker infrastructure: 41 residential proxy IPs, user agents rotated.", "Containment completed 03:45 SGT. WAF rule WAF-2291 deployed."], ["Recommendations", "1. Rotate all internal API keys.", "2. Pre-commit secret scanning for all repositories.", "3. Remove service-key bypass from the login rate limiter.", "Prepared by: S. Ng, Security. Classification: CONFIDENTIAL."]], "Q3 forensic report"), "Q3 forensic report (scanned PDF)"),
            perms=[Perm("user", sara, "writer"), Perm("user", daniel, "reader"), Perm("user", olivia, "reader")])
    c.drive("fH-Q3TIMELINE", "Q3 breach forensic timeline", "image/png", "SD-SEC", sec2, 25, "", att=bt)

    # ================= 应用安全：普通工程师（jdoe）能看到的 =================
    c.page("9210", "APPSEC", "Secure coding guidelines", "## Overview\nGeneral secure coding guidance for all engineers: validate input, parameterise queries, never log secrets, review dependencies.\n\n## Vulnerability management\nVulnerabilities found by scanners are triaged by the security team. Engineers receive a ticket for the fix; details of exploitable issues are shared on a need-to-know basis.\n\n## Dependency policy\nCritical CVEs in dependencies must be patched within 7 days, high within 30 days.", sec2, 60, version=3)
    c.page("9211", "APPSEC", "Dependency vulnerability policy", "Critical severity: patch within 7 days. High: 30 days. Medium: next release. Exceptions need a security-team waiver. Scanner results are available in the security dashboard for security-team members.", sec3, 90, version=2)
    c.issue("PAY-9101", "Upgrade log4j-compatible logging library across payments services", "Routine dependency upgrade requested by the security scanner. Not exploitable in our configuration.", "In Progress", "Medium", sec2, jdoe, 12)

    # ================= 法务 / 财务：合同扫描件、容量表、预算 =================
    msa = _pdf("acme-msa-scan.pdf", media.scan_pages([["MASTER SERVICES AGREEMENT — Acme Cloud Pte Ltd and Tidepool Pay", "1. Term. Initial term 36 months from the Effective Date, renewing annually.", "2. Fees. Committed annual spend USD 2,400,000, invoiced quarterly.",
                                                       "3. Service levels. Monthly uptime 99.95%. Credits: 5% of monthly fees below 99.95%, 10% below 99.9%, 25% below 99.5%."],
                                                      ["4. Termination for convenience. Either party may terminate with 90 days written notice. An early termination fee of 25% of the remaining annual commitment applies.", "5. Data protection. Provider processes personal data only on documented instructions; sub-processors require 30 days notice.",
                                                       "6. Liability. Aggregate liability capped at 12 months of fees. Signed: G. Koh (CFO) for Tidepool Pay."]], "Master Services Agreement"), "Acme Cloud MSA (scanned PDF)")
    c.drive("fH-MSA", "Acme Cloud MSA (scan)", "application/pdf", "SD-LEG", "legal0" if "legal0" in c.d.by_id else T("legal", 0), 100, "", limited=True, att=msa, perms=[Perm("user", T("legal", 0), "writer"), Perm("user", grace, "reader"), Perm("user", daniel, "reader")])
    c.drive("fH-CAPACITY", "Q4 capacity plan (FY26)", "application/vnd.google-apps.spreadsheet", "SD-DATA", T("data-eng", 0), 7,
            "Sheet: Q4 capacity plan\n\n| Team | Current cores | Q4 plan cores | Growth % |\n|---|---|---|---|\n| payments-eng | 1,200 | 1,980 | 65% |\n| platform-eng | 900 | 1,170 | 30% |\n| data-eng | 2,400 | 3,120 | 30% |\n| sre | 300 | 345 | 15% |\n| ml-risk | 500 | 1,100 | 120% |\n\nNote: ml-risk shows the largest growth (120%) driven by fraud model v3 training.",
            perms=[Perm("group", "engineering", "reader"), Perm("group", "finance", "reader")])
    c.page("9600", "FIN", "FY26 headcount and budget by department (draft)", "## Summary\nPayments engineering: FY26 budget USD 6.1M, headcount 14. Platform: USD 5.2M, headcount 12. **Payments team Q4 budget is proposed at zero pending the reorganisation decision.** Numbers are for finance and leadership only.", T("finance", 0), 6, version=3)

    # ================= 外包人员（Ken）与合作伙伴 =================
    c.page("9700", "CNTR", "Contractor onboarding checklist", "## Welcome\n1. Complete security awareness training within the first week.\n2. Use your company-issued laptop only; no personal devices for production access.\n3. Request access through your sponsor; access is time-boxed to the end of your contract.\n4. Never commit credentials to repositories.\n\n## Who to contact\nYour sponsor and the #contractor-announcements channel in the partners workspace.", T("people-ops", 0), 30, version=2)
    c.page("9701", "POL", "Acceptable use of company devices", "## Purpose\nDefines acceptable use of company devices and networks. All employees and contractors must follow it.\n\n## Requirements\n- Lock your device when unattended.\n- Do not install unapproved software.\n- Report lost devices within 24 hours.", T("people-ops", 1), 60, version=4)
    c.chan("CH-ACME", "acme-integration", {ken, alice}, "private", ws="T002", topic="Acme integration — sandbox")
    c.thread("CH-ACME", 3, 10, (ken, "Sandbox API credentials for the Acme integration expire on Friday. Can we rotate?"), [(alice, "I'll rotate them Thursday and share via the vault. Please don't paste them in chat.")])
    c.drive("fH-KEN", "Acme integration — sandbox notes", "application/vnd.google-apps.document", None, alice, 3, "Notes for the Acme integration sandbox. Endpoints, test merchants and the rotation schedule for sandbox credentials. No production data.", perms=[Perm("user", alice, "writer"), Perm("user", ken, "reader")], limited=True)

    # ================= 私信：领导层 =================
    c.chan("DM-PG", "dm-pete-grace", {pete, grace}, "im", topic="")
    c.thread("DM-PG", 4, 19, (pete, "Quick one: are we really zeroing the Payments budget for Q4? I need to know before the Friday all-hands."), [(grace, "It's in the draft but not final. Please don't mention it until Olivia signs off.")])
