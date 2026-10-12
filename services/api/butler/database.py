"""Persistent workspace store. PostgreSQL in deployment; SQLite for local preview/tests.

业务对象分表（带索引列，可按属主/来源分页查询）；其余低频配置仍放通用表。接口保持 get/put/all/delete 不变，
启动时把旧通用表里的同类记录幂等迁移到新表。
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from sqlalchemy import (Boolean, Column, Float, ForeignKey, Index, Integer, JSON, LargeBinary, MetaData, String, Table,
                        Text, create_engine, func, select)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.pool import StaticPool

metadata = MetaData()
records = Table("workspace_records", metadata,
                Column("kind", String(32), primary_key=True),
                Column("id", String(256), primary_key=True),
                Column("data", JSON, nullable=False))

documents = Table("documents", metadata,
                  Column("id", String(256), primary_key=True), Column("source", String(32), index=True),
                  Column("content_hash", String(64)), Column("title", String(500)), Column("acl", JSON),
                  Column("fresh_until", Float),   # 平台同步来的文档：权限复核有效期，过期即视为不可读
                  Column("data", JSON, nullable=False))
facts = Table("facts", metadata,
              Column("id", String(256), primary_key=True), Column("source_doc", String(256), index=True),
              Column("data", JSON, nullable=False))
members = Table("members", metadata,
                Column("id", String(256), primary_key=True), Column("active", Boolean, index=True),
                Column("data", JSON, nullable=False))
conversations = Table("conversations", metadata,
                      Column("id", String(512), primary_key=True), Column("owner", String(256), index=True),
                      Column("updated", Float, index=True), Column("data", JSON, nullable=False))
audit_entries = Table("audit_entries", metadata,
                      Column("id", String(32), primary_key=True), Column("data", JSON, nullable=False))

# 切块与向量：一个 chunk 属于一个文档的一个内容版本；embedding 按 (模型, 输入哈希) 复用
chunks = Table("chunks", metadata,
               Column("id", String(300), primary_key=True), Column("doc_id", String(256), nullable=False),
               Column("content_hash", String(64), nullable=False), Column("seq", Integer, nullable=False),
               Column("start", Integer, nullable=False), Column("end", Integer, nullable=False),
               Column("tokens", Integer, nullable=False), Column("heading", Text, nullable=False, default=""),
               Column("text", Text, nullable=False), Column("text_hash", String(64), nullable=False),
               Column("risk", Float, nullable=False, default=0.0), Column("flags", String(200), nullable=False, default=""),
               Index("ix_chunks_doc", "doc_id", "content_hash"))
embeddings = Table("embeddings", metadata,
                   Column("model", String(128), primary_key=True), Column("text_hash", String(64), primary_key=True),
                   Column("dim", Integer, nullable=False), Column("vector", LargeBinary, nullable=False))
sync_jobs = Table("sync_jobs", metadata,
                  Column("id", String(128), primary_key=True), Column("source", String(32), index=True),
                  Column("external_id", String(256), index=True), Column("version", Float, nullable=False),
                  Column("kind", String(16), nullable=False), Column("status", String(16), index=True, nullable=False),
                  Column("attempts", Integer, nullable=False, default=0), Column("run_after", Float, nullable=False, default=0.0),
                  Column("error", Text, nullable=False, default=""), Column("payload", JSON, nullable=False),
                  Column("created", Float, nullable=False))

# kind -> (表, 从记录中取出索引列的函数)
TYPED = {
    "document": (documents, lambda d: {"source": d.get("source"), "content_hash": d.get("content_hash"),
                                             "title": d.get("title"), "acl": d.get("acl"),
                                             "fresh_until": (d.get("sync") or {}).get("acl_fresh_until")}),
    "fact": (facts, lambda d: {"source_doc": d.get("source_doc")}),
    "member": (members, lambda d: {"active": bool(d.get("active"))}),
    "conversation": (conversations, lambda d: {"owner": d.get("owner"), "updated": d.get("updated", 0.0)}),
    "audit_entry": (audit_entries, lambda d: {}),
}


def _insert(connection):
    return pg_insert if connection.dialect.name == "postgresql" else sqlite_insert


class Transaction:
    def __init__(self, connection):
        self.connection = connection

    def get(self, kind: str, key: str, default=None):
        table = TYPED[kind][0] if kind in TYPED else records
        where = [table.c.id == key] + ([] if kind in TYPED else [records.c.kind == kind])
        value = self.connection.execute(select(table.c.data).where(*where)).scalar_one_or_none()
        return default if value is None else value

    def all(self, kind: str):
        return list(self.iter(kind))

    def iter(self, kind: str, batch: int = 500):
        """分批读取，避免一次把整张表装进内存。"""
        table = TYPED[kind][0] if kind in TYPED else records
        cond = [] if kind in TYPED else [records.c.kind == kind]
        last = None
        while True:
            q = select(table.c.id, table.c.data).where(*cond).order_by(table.c.id).limit(batch)
            if last is not None:
                q = q.where(table.c.id > last)
            rows = self.connection.execute(q).all()
            if not rows:
                return
            for _, data in rows:
                yield data
            last = rows[-1][0]

    def query(self, kind: str, order_by: str | None = None, descending: bool = False, limit: int | None = None, **equal):
        """按索引列过滤：conversations 按 owner，members 按 active，facts 按 source_doc 等。"""
        table = TYPED[kind][0]
        q = select(table.c.data).where(*[table.c[k] == v for k, v in equal.items()])
        if order_by:
            col = table.c[order_by]
            q = q.order_by(col.desc() if descending else col)
        if limit:
            q = q.limit(limit)
        return list(self.connection.execute(q).scalars())

    def tail(self, kind: str, n: int) -> list[tuple[str, dict]]:
        """最后 n 条（按主键升序返回），审计列表不必加载整条链。"""
        table = TYPED[kind][0]
        rows = self.connection.execute(select(table.c.id, table.c.data).order_by(table.c.id.desc()).limit(n)).all()
        return [(r[0], r[1]) for r in reversed(rows)]

    def count(self, kind: str) -> int:
        table = TYPED[kind][0] if kind in TYPED else records
        q = select(func.count()).select_from(table)
        if kind not in TYPED:
            q = q.where(records.c.kind == kind)
        return self.connection.execute(q).scalar_one()

    def put(self, kind: str, key: str, data: dict):
        insert = _insert(self.connection)
        if kind in TYPED:
            table, extract = TYPED[kind]
            values = {"id": key, "data": data, **extract(data)}
            self.connection.execute(insert(table).values(**values).on_conflict_do_update(
                index_elements=[table.c.id], set_={k: v for k, v in values.items() if k != "id"}))
            return
        stmt = insert(records).values(kind=kind, id=key, data=data)
        self.connection.execute(stmt.on_conflict_do_update(
            index_elements=[records.c.kind, records.c.id], set_={"data": data}))

    def delete(self, kind: str, key: str):
        if kind in TYPED:
            table = TYPED[kind][0]
            self.connection.execute(table.delete().where(table.c.id == key))
            return
        self.connection.execute(records.delete().where(records.c.kind == kind, records.c.id == key))


def ensure_columns(engine) -> None:
    """为早期版本创建的分表补列（create_all 不会改已有表），并回填新列。"""
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    with engine.begin() as connection:
        for table in metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in have:
                    connection.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(engine.dialect)}'))
        for kind, (table, extract) in TYPED.items():
            if kind == "document":
                for key, data in connection.execute(select(table.c.id, table.c.data).where(table.c.acl.is_(None))).all():
                    connection.execute(table.update().where(table.c.id == key).values(**extract(data)))


def migrate_legacy(connection) -> int:
    """把旧通用表中的业务记录搬到分表；重复执行无副作用。"""
    moved = 0
    insert = _insert(connection)
    for kind, (table, extract) in TYPED.items():
        rows = connection.execute(select(records.c.id, records.c.data).where(records.c.kind == kind)).all()
        for key, data in rows:
            connection.execute(insert(table).values(id=key, data=data, **extract(data)).on_conflict_do_nothing(
                index_elements=[table.c.id]))
            moved += 1
        if rows:
            connection.execute(records.delete().where(records.c.kind == kind))
    return moved


class Database:
    def __init__(self, url: str):
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        options = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            options["connect_args"] = {"check_same_thread": False, "timeout": 30}
            if url.endswith(":memory:"):
                options["poolclass"] = StaticPool
        self.engine = create_engine(url, **options)
        self.lock = threading.RLock()
        metadata.create_all(self.engine)
        ensure_columns(self.engine)
        with self.engine.begin() as connection:
            insert = _insert(connection)
            connection.execute(insert(records).values(kind="meta", id="lock", data={}).on_conflict_do_nothing())
            migrate_legacy(connection)

    @contextmanager
    def transaction(self):
        # 事务内串行化审计链/会话写入。模型调用已在锁外（见 workspace._ask）。
        with self.lock, self.engine.begin() as connection:
            connection.execute(select(records.c.id).where(
                records.c.kind == "meta", records.c.id == "lock").with_for_update()).first()
            yield Transaction(connection)
