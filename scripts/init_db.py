"""DB を空から作って初期ユーザーを1人登録する。

Usage:
    python -m scripts.init_db --username admin --password <パスワード>
"""
import argparse
import hashlib
import sqlite3
import sys
from pathlib import Path

from app.db import configure_db

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "db_schema.sql"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--display-name", default=None)
    parser.add_argument("--role", default="admin", choices=["admin", "ja_staff", "farmer"])
    args = parser.parse_args()

    db_path = configure_db()
    print(f"[init_db] DB: {db_path}")

    conn = sqlite3.connect(str(db_path))
    try:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            conn.executescript(f.read())

        pw_hash = hashlib.sha256(args.password.encode("utf-8")).hexdigest()
        cursor = conn.execute(
            "INSERT OR IGNORE INTO users (username, password_hash, display_name, role) "
            "VALUES (?, ?, ?, ?)",
            (args.username, pw_hash, args.display_name or args.username, args.role),
        )
        conn.commit()
        if cursor.rowcount == 0:
            print(f"[init_db] ユーザー '{args.username}' は既に存在します（パスワード未更新）")
        else:
            print(f"[init_db] ユーザー '{args.username}' を作成しました")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
