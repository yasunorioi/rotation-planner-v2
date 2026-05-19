"""ダッシュボード — ほ場数・計画数・履歴数の数値表示のみ。"""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from app.auth import CurrentUser
from app.db import connect

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


@router.get("/")
def dashboard(request: Request, user: CurrentUser):
    with connect() as conn:
        field_count = conn.execute(
            "SELECT COUNT(*) AS c FROM fields WHERE user_id = ?", (user["id"],)
        ).fetchone()["c"]
        plan_count = conn.execute(
            "SELECT COUNT(*) AS c FROM rotation_plans WHERE user_id = ?", (user["id"],)
        ).fetchone()["c"]
        history_count = conn.execute(
            "SELECT COUNT(*) AS c FROM crop_history h "
            "JOIN fields f ON h.field_id = f.id WHERE f.user_id = ?",
            (user["id"],),
        ).fetchone()["c"]
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": user,
            "field_count": field_count,
            "plan_count": plan_count,
            "history_count": history_count,
        },
    )
