"""テスト共通: 各テストで独立した一時 SQLite を用意する。"""
import hashlib
import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

SCHEMA = Path(__file__).resolve().parent.parent / "db_schema.sql"


@pytest.fixture
def app_client(monkeypatch):
    """FastAPI TestClient + 一時 DB + テストユーザー (test/testpw)."""
    tmp = tempfile.NamedTemporaryFile(suffix="_v2_test.db", delete=False)
    tmp.close()
    monkeypatch.setenv("ROTATION_DB", tmp.name)

    conn = sqlite3.connect(tmp.name)
    with open(SCHEMA, "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    pw_hash = hashlib.sha256("testpw".encode()).hexdigest()
    conn.execute(
        "INSERT INTO users (username, password_hash, display_name, role) "
        "VALUES (?, ?, ?, ?)",
        ("test", pw_hash, "テストユーザー", "farmer"),
    )
    conn.commit()
    conn.close()

    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        c.auth = ("test", "testpw")
        yield c

    try:
        os.unlink(tmp.name)
    except FileNotFoundError:
        pass
