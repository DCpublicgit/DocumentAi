"""Test isolation: the suite never touches the database the app serves from.

Several tests run against a real Postgres (test_server starts the real app,
whose startup creates schemas and whose answers write audit rows; test_loader
and test_registry insert and delete rows; test_fts_query needs the real
corpus). Pointed at DATABASE_URL from .env, which is the live database, that
meant every test run added fake questions ("Асуулт", "kjshdf ...") to the audit
table employees' usage is read from, briefly flipped is_current flags in the
table retrieval serves from, and applied schema changes to production before
any deploy.

So settings.database_url is swapped, at import time and before anything can
open a pool, for a sibling database named "<live name>_test" on the same
server. A session fixture creates it if missing and seeds policy_chunks from
the live database (READ-ONLY on the live side). It fails safe: if the test
database cannot be prepared, tests that need it error out on a missing
database. They never fall back to the live one.
"""

import asyncio
import warnings
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest
from pgvector.asyncpg import register_vector

from app import db
from app.config import settings

# TestClient(app) (tests/test_server.py) runs the real FastAPI lifespan,
# including startup model warm-up. Off in tests: it costs ~150s cold on the
# CPU-only pilot VM and every other test file mocks or skips the real
# BGE-M3/reranker models entirely (see tests/test_reranker.py) — the test
# suite has never depended on the actual weights being loaded.
settings.warm_up_models_enabled = False

LIVE_DATABASE_URL = settings.database_url


def _url_for(database: str) -> str:
    return urlunsplit(urlsplit(LIVE_DATABASE_URL)._replace(path=f"/{database}"))


_live_name = urlsplit(LIVE_DATABASE_URL).path.lstrip("/")
TEST_DATABASE = f"{_live_name}_test"
settings.database_url = _url_for(TEST_DATABASE)

_CHUNK_COLUMNS = (
    "file_name, section, policy_version, effective_date, is_current, chunk_index, content, embedding"
)


async def _prepare_test_database() -> None:
    # Maintenance connection on the same server, only to create the database.
    admin = await asyncpg.connect(_url_for("postgres"))
    try:
        exists = await admin.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", TEST_DATABASE)
        if not exists:
            await admin.execute(f'CREATE DATABASE "{TEST_DATABASE}"')
    finally:
        await admin.close()

    test = await asyncpg.connect(settings.database_url)
    live = await asyncpg.connect(LIVE_DATABASE_URL)
    try:
        for sql in (
            db.CREATE_SCHEMA_SQL,
            db.CREATE_REGISTRY_SCHEMA_SQL,
            db.CREATE_AUDIT_SCHEMA_SQL,
            db.CREATE_FEEDBACK_SCHEMA_SQL,
        ):
            await test.execute(sql)

        await register_vector(test)
        await register_vector(live)
        # Reads only: the live connection never executes anything but SELECTs.
        live_count = await live.fetchval("SELECT count(*) FROM policy_chunks")
        test_count = await test.fetchval("SELECT count(*) FROM policy_chunks WHERE file_name NOT LIKE 'TEST\\_%'")
        if live_count != test_count:
            rows = await live.fetch(f"SELECT {_CHUNK_COLUMNS} FROM policy_chunks")
            async with test.transaction():
                await test.execute("TRUNCATE policy_chunks")
                await test.executemany(
                    f"INSERT INTO policy_chunks ({_CHUNK_COLUMNS}) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
                    [tuple(r) for r in rows],
                )
    finally:
        await test.close()
        await live.close()


@pytest.fixture(scope="session", autouse=True)
def _isolated_test_database():
    assert settings.database_url != LIVE_DATABASE_URL and TEST_DATABASE.endswith("_test"), (
        "tests must never run against the live database"
    )
    try:
        asyncio.run(_prepare_test_database())
    except Exception as exc:  # noqa: BLE001 — see module docstring: fail safe, not fall back
        warnings.warn(
            f"could not prepare test database {TEST_DATABASE!r} ({type(exc).__name__}: {exc}); "
            "tests that need Postgres will fail, and none will touch the live database",
            stacklevel=1,
        )
    yield
