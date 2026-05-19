"""HTTP Basic 認証。

v1 と同じ `users.password_hash = sha256(password)` を使い、JWT 層は廃止。
タイミング攻撃を避けるため `secrets.compare_digest` で比較する。
"""
import hashlib
import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.db import connect

_security = HTTPBasic(realm="rotation-planner-v2")


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def authenticate(credentials: HTTPBasicCredentials) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT id, username, display_name, role, org_id, password_hash, is_active "
            "FROM users WHERE username = ?",
            (credentials.username,),
        ).fetchone()
    if row is None or not row["is_active"]:
        return None
    expected = row["password_hash"]
    actual = _sha256(credentials.password)
    if not secrets.compare_digest(expected, actual):
        return None
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "role": row["role"],
        "org_id": row["org_id"],
    }


def current_user(
    credentials: Annotated[HTTPBasicCredentials, Depends(_security)],
) -> dict:
    user = authenticate(credentials)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="認証失敗",
            headers={"WWW-Authenticate": 'Basic realm="rotation-planner-v2"'},
        )
    return user


CurrentUser = Annotated[dict, Depends(current_user)]
