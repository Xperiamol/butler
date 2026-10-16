"""组装“Tidepool Pay”：人员目录 + 四个平台的批量资料 + 主角场景 + 多模态附件。同一个 (epoch, seed, scale) 得到同一个世界。"""
from __future__ import annotations
import time

from . import fill_confluence, fill_drive, fill_jira, fill_slack, hero, hero2, media
from .base import Attachment
from .confluence import ConfluenceServer
from .drive import DriveFile, DriveServer, Perm
from .hub import Hub
from .jira import JiraServer
from .people import directory
from .slack import SlackServer
from .vocab import Pick, when


def _chart_files(hub: Hub, epoch: float, seed: int, n: int) -> None:
    """批量的多模态文件：监控图 / 趋势图（真实绘制），识别文本来自同一份数据。"""
    p = Pick(seed)
    d = hub.directory
    owners = [x.id for x in d.employees()]
    drives = list(hub.drive.drives)
    for k in range(n):
        svc = p.one(["payment-service", "ledger-service", "fraud-engine", "api-gateway", "settlement-service", "auth-service"])
        metric = p.one([("p99 latency (ms)", 400.0), ("error rate (%)", 3.0), ("requests per second", 900.0), ("queue depth", 1200.0), ("CPU utilisation (%)", 80.0)])
        xs = [f"{h:02d}:00" for h in range(0, 24, 2)]
        base = metric[1]
        vals = [round(base * p.between(0.4, 1.0), 1) for _ in xs]
        title = f"{svc} — {metric[0]} (last 24h)"
        key = f"chart-{k:03d}.png"
        if not (media.media_dir() / key).exists():
            data, cap = media.line_chart(title, xs, [(metric[0], vals, "#58a6ff")], metric[0])
            media.save(key, data)
        else:
            cap = f"Dark-theme dashboard screenshot titled \"{title}\" with y-axis \"{metric[0]}\". The highest value shown is {max(vals)}."
        att = Attachment(f"chart-{k:03d}", f"{svc}-{k}.png", "image/png", key, cap, "vision")
        did = p.one(drives)
        hub.drive.add_file(DriveFile(f"fM{k:04d}", f"Dashboard snapshot: {svc} {metric[0].split(' (')[0]}", "image/png", None, did, p.one(owners), when(epoch, p.between(1, 120)) - 3600, when(epoch, p.between(1, 120)), "", [], False, att, version=1))
    # 一些只有转写、没有实体文件的会议录音/视频（来源是 ASR）
    for k in range(18):
        team = p.one(["payments-eng", "platform-eng", "product", "sre", "data-eng", "design"])
        topic = p.one(["sprint review", "design review", "architecture brown bag", "customer interview", "quarterly planning", "incident review"])
        txt = f"Recording transcript ({topic}, {team}):\n[00:01] Host: Thanks everyone for joining. Today we cover {p.one(['roadmap', 'reliability', 'launch readiness', 'capacity'])}.\n[03:20] Speaker: The main risk is {p.one(['ownership gaps', 'late dependencies', 'unclear requirements', 'alert fatigue'])}.\n[08:45] Host: Let's capture the action items in the ticket."
        att = Attachment(f"rec-{k:03d}", f"{topic} — {team}.mp4", "video/mp4", "", txt, "asr")
        hub.drive.add_file(DriveFile(f"fV{k:04d}", f"Recording: {topic} ({team})", "video/mp4", None, "SD-ALL" if p.chance(0.3) else "SD-PRD", p.one(owners), when(epoch, p.between(2, 150)) - 3600, when(epoch, p.between(2, 150)), "", [], False, att, version=1))


def build_world(epoch: float | None = None, seed: int = 7, scale: float = 1.0, throttle_every: int = 0, charts: int = 90) -> Hub:
    epoch = float(epoch if epoch is not None else time.time())
    d = directory(seed)
    hub = Hub(d, ConfluenceServer(d, throttle_every), JiraServer(d, throttle_every), SlackServer(d, throttle_every, now=epoch), DriveServer(d, throttle_every), epoch)
    fill_confluence.seed_spaces(hub.confluence)
    fill_confluence.fill_pages(hub.confluence, d, epoch, seed + 1, scale=scale)
    fill_jira.seed_projects(hub.jira, d)
    fill_jira.fill_issues(hub.jira, d, epoch, seed + 2, scale=scale)
    fill_slack.seed_workspaces(hub.slack, d)
    fill_slack.seed_channels(hub.slack, d, epoch, seed + 3)
    fill_slack.fill_threads(hub.slack, d, epoch, seed + 4, scale=scale)
    fill_drive.seed_drives(hub.drive, d)
    fill_drive.fill_files(hub.drive, d, epoch, seed + 5, scale=scale)
    ctx = hero.Ctx(hub, epoch)
    hero.add_engineering(ctx)
    hero2.add_security_and_business(ctx)
    _chart_files(hub, epoch, seed + 6, charts)
    return hub
