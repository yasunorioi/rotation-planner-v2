"""輪作計画 CRUD — name / start_year / end_year のメタデータのみ。

constraints_json / metadata_json は optimizer 接続時に拡張する。
"""
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from app.auth import CurrentUser
from app.db import connect

router = APIRouter(prefix="/plans")
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _fetch_plans(user_id: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, name, start_year, end_year, created_at, updated_at "
            "FROM rotation_plans WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def _fetch_plan(user_id: int, plan_id: int) -> dict:
    with connect() as conn:
        row = conn.execute(
            "SELECT id, name, start_year, end_year, created_at, updated_at "
            "FROM rotation_plans WHERE id = ? AND user_id = ?",
            (plan_id, user_id),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "計画が見つかりません")
    return dict(row)


@router.get("/")
def list_plans(request: Request, user: CurrentUser):
    plans = _fetch_plans(user["id"])
    return templates.TemplateResponse(
        request, "plans/list.html", {"user": user, "plans": plans}
    )


@router.get("/new", response_class=HTMLResponse)
def new_plan_form(request: Request, user: CurrentUser):
    return templates.TemplateResponse(request, "plans/_form.html", {"plan": None})


@router.post("/", response_class=HTMLResponse)
def create_plan(
    request: Request,
    user: CurrentUser,
    name: str = Form(...),
    start_year: str = Form(...),
    end_year: str = Form(...),
):
    with connect() as conn:
        cursor = conn.execute(
            "INSERT INTO rotation_plans (user_id, name, start_year, end_year) "
            "VALUES (?, ?, ?, ?)",
            (user["id"], name, start_year, end_year),
        )
        plan_id = cursor.lastrowid
    plan = _fetch_plan(user["id"], plan_id)
    return templates.TemplateResponse(request, "plans/_row.html", {"plan": plan})


@router.get("/{plan_id}/edit", response_class=HTMLResponse)
def edit_plan_form(request: Request, user: CurrentUser, plan_id: int):
    plan = _fetch_plan(user["id"], plan_id)
    return templates.TemplateResponse(request, "plans/_form.html", {"plan": plan})


@router.get("/{plan_id}")
def plan_detail(request: Request, user: CurrentUser, plan_id: int):
    plan = _fetch_plan(user["id"], plan_id)
    return templates.TemplateResponse(
        request, "plans/detail.html", {"user": user, "plan": plan}
    )


@router.post("/{plan_id}/optimize", response_class=HTMLResponse)
def optimize_plan(request: Request, user: CurrentUser, plan_id: int):
    plan = _fetch_plan(user["id"], plan_id)
    from app.optimizer_service import run_optimization_for_plan

    result = run_optimization_for_plan(user["id"], plan)
    return templates.TemplateResponse(
        request, "plans/_result.html", {"plan": plan, "result": result}
    )


@router.put("/{plan_id}", response_class=HTMLResponse)
def update_plan(
    request: Request,
    user: CurrentUser,
    plan_id: int,
    name: str = Form(...),
    start_year: str = Form(...),
    end_year: str = Form(...),
):
    with connect() as conn:
        result = conn.execute(
            "UPDATE rotation_plans SET name=?, start_year=?, end_year=?, "
            "updated_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?",
            (name, start_year, end_year, plan_id, user["id"]),
        )
        if result.rowcount == 0:
            raise HTTPException(404, "計画が見つかりません")
    plan = _fetch_plan(user["id"], plan_id)
    return templates.TemplateResponse(request, "plans/_row.html", {"plan": plan})


@router.delete("/{plan_id}")
def delete_plan(user: CurrentUser, plan_id: int):
    with connect() as conn:
        result = conn.execute(
            "DELETE FROM rotation_plans WHERE id = ? AND user_id = ?",
            (plan_id, user["id"]),
        )
        if result.rowcount == 0:
            raise HTTPException(404, "計画が見つかりません")
    return Response(status_code=200)
