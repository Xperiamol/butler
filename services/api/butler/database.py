"""Small persistent workspace store. PostgreSQL in deployment; SQLite for local preview/tests."""
from __future__ import annotations

import threading
from contextlib import contextmanager
from sqlalchemy import Column, JSON, MetaData, String, Table, create_engine, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.pool import StaticPool

metadata = MetaData()
records = Table("workspace_records", metadata,
                Column("kind", String(32), primary_key=True),
                Column("id", String(256), primary_key=True),
                Column("data", JSON, nullable=False))


class Transaction:
    def __init__(self, connection):
        self.connection = connection

    def get(self, kind: str, key: str, default=None):
        value = self.connection.execute(select(records.c.data).where(
            records.c.kind == kind, records.c.id == key)).scalar_one_or_none()
        return default if value is None else value

    def all(self, kind: str):
        return list(self.connection.execute(select(records.c.data).where(
            records.c.kind == kind).order_by(records.c.id)).scalars())

    def put(self, kind: str, key: str, data: dict):
        insert = pg_insert if self.connection.dialect.name == "postgresql" else sqlite_insert
        stmt = insert(records).values(kind=kind, id=key, data=data)
        self.connection.execute(stmt.on_conflict_do_update(
            index_elements=[records.c.kind, records.c.id], set_={"data": data}))

    def delete(self, kind: str, key: str):
        self.connection.execute(records.delete().where(records.c.kind == kind, records.c.id == key))


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
        with self.engine.begin() as connection:
            insert = pg_insert if connection.dialect.name == "postgresql" else sqlite_insert
            connection.execute(insert(records).values(kind="meta", id="lock", data={}).on_conflict_do_nothing())

    @contextmanager
    def transaction(self):
        # Serialize audit-chain/session mutations across workers. A slow model holds
        # this lock; the initial deployment intentionally has one API worker.
        with self.lock, self.engine.begin() as connection:
            connection.execute(select(records.c.id).where(
                records.c.kind == "meta", records.c.id == "lock").with_for_update()).first()
            yield Transaction(connection)
