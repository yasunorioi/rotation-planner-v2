"""SQLite 接続ヘルパー。

ドメインライブラリ `rotation_planner.common.db` の DB_PATH を環境変数
ROTATION_DB から差し替えて使う。アプリ起動時に `configure_db()` を呼ぶ。
"""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from rotation_planner.common import db as _domain_db
from rotation_planner.common import db_access as _domain_db_access

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "rotation_planner.db"


def configure_db() -> Path:
    db_path = Path(os.environ.get("ROTATION_DB", DEFAULT_DB_PATH)).resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _domain_db.DB_PATH = db_path
    _domain_db_access.DB_PATH = db_path
    return db_path


@contextmanager
def connect():
    db_path = configure_db()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
