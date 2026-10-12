"""可选：用 Celery 调度同一个 tick（需要 `pip install celery redis` 和 Redis）。

默认部署用 `python -m butler.workers.run`（数据库队列，不需要 Redis）；这个文件只是把同样的函数挂到 Celery 上，
方便已经有 Celery 基础设施的环境接入。**本仓库的测试没有覆盖它**（沙箱里没有 Redis）。

    BUTLER_CELERY_BROKER=redis://redis:6379/0 celery -A butler.workers.celery_app worker -B
"""
import os

from celery import Celery   # 未安装 celery 时导入本模块会失败，这是预期的

app = Celery("butler", broker=os.environ["BUTLER_CELERY_BROKER"])
app.conf.beat_schedule = {"sync-tick": {"task": "butler.workers.celery_app.sync_tick", "schedule": 30.0}}
_counter = {"n": 0}


@app.task(name="butler.workers.celery_app.sync_tick")
def sync_tick():
    from .. import workspace as w
    from .run import tick
    _counter["n"] += 1
    return tick(w.database, w.embedder_for, _counter["n"])
