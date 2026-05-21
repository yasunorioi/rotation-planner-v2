"""ダッシュボード — 指標 + 最近の活動 + アクション提案。"""
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from app.auth import CurrentUser
from app.db import connect

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


@router.get("/")
def dashboard(request: Request, user: CurrentUser):
    uid = user["id"]
    current_year = datetime.now().year
    with connect() as conn:
        field_count = conn.execute(
            "SELECT COUNT(*) AS c FROM fields WHERE user_id = ?", (uid,)
        ).fetchone()["c"]
        plan_count = conn.execute(
            "SELECT COUNT(*) AS c FROM rotation_plans WHERE user_id = ?", (uid,)
        ).fetchone()["c"]
        history_count = conn.execute(
            "SELECT COUNT(*) AS c FROM crop_history h "
            "JOIN fields f ON h.field_id = f.id WHERE f.user_id = ?",
            (uid,),
        ).fetchone()["c"]
        # 今年の防除記録件数
        records_year = conn.execute(
            "SELECT COUNT(*) AS c FROM pesticide_records "
            "WHERE user_id = ? AND strftime('%Y', spray_date) = ?",
            (uid, str(current_year)),
        ).fetchone()["c"]
        # 最近編集したほ場 (5件)
        recent_fields = [dict(r) for r in conn.execute(
            "SELECT id, field_code, name, updated_at FROM fields "
            "WHERE user_id = ? ORDER BY updated_at DESC LIMIT 5",
            (uid,),
        ).fetchall()]
        # 最近の計画 (3件)
        recent_plans = [dict(r) for r in conn.execute(
            "SELECT id, name, start_year, end_year, updated_at FROM rotation_plans "
            "WHERE user_id = ? ORDER BY updated_at DESC LIMIT 3",
            (uid,),
        ).fetchall()]
        # 最近の防除記録 (5件)
        recent_records = [dict(r) for r in conn.execute(
            "SELECT r.id, r.spray_date, r.pesticide_name, f.field_code FROM pesticide_records r "
            "JOIN fields f ON r.field_id = f.id "
            "WHERE r.user_id = ? ORDER BY r.spray_date DESC, r.id DESC LIMIT 5",
            (uid,),
        ).fetchall()]
        # アクション提案: ポリゴン未登録のほ場数
        no_polygon = conn.execute(
            "SELECT COUNT(*) AS c FROM fields "
            "WHERE user_id = ? AND coordinates_json IS NULL",
            (uid,),
        ).fetchone()["c"]
        # アクション提案: 履歴が空 (= 一度も crop が登録されていない) のほ場
        no_history = conn.execute(
            "SELECT COUNT(*) AS c FROM fields f "
            "WHERE f.user_id = ? AND NOT EXISTS ("
            "  SELECT 1 FROM crop_history h WHERE h.field_id = f.id"
            ")",
            (uid,),
        ).fetchone()["c"]
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": user,
            "field_count": field_count,
            "plan_count": plan_count,
            "history_count": history_count,
            "records_year": records_year,
            "current_year": current_year,
            "recent_fields": recent_fields,
            "recent_plans": recent_plans,
            "recent_records": recent_records,
            "no_polygon": no_polygon,
            "no_history": no_history,
        },
    )
