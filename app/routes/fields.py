"""ほ場 CRUD — HTMX で行単位 add/edit/delete。ポリゴン編集は別ページ。"""
import json
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.auth import CurrentUser
from app.db import connect

SAPPORO = [43.0642, 141.3469]  # ポリゴン未登録時のデフォルト中心

router = APIRouter(prefix="/fields")
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _fetch_fields(user_id: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, field_code, district, name, area_ha, beet_forbidden, notes "
            "FROM fields WHERE user_id = ? ORDER BY field_code",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def _fetch_field(user_id: int, field_id: int) -> dict:
    with connect() as conn:
        row = conn.execute(
            "SELECT id, field_code, district, name, area_ha, beet_forbidden, notes "
            "FROM fields WHERE id = ? AND user_id = ?",
            (field_id, user_id),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "ほ場が見つかりません")
    return dict(row)


@router.get("/")
def list_fields(request: Request, user: CurrentUser):
    fields = _fetch_fields(user["id"])
    return templates.TemplateResponse(
        request, "fields/list.html", {"user": user, "fields": fields}
    )


@router.get("/new", response_class=HTMLResponse)
def new_field_form(request: Request, user: CurrentUser):
    return templates.TemplateResponse(
        request, "fields/_form.html", {"field": None}
    )


@router.post("/", response_class=HTMLResponse)
def create_field(
    request: Request,
    user: CurrentUser,
    field_code: str = Form(...),
    name: str = Form(""),
    district: str = Form(""),
    area_ha: float = Form(...),
    beet_forbidden: bool = Form(False),
    notes: str = Form(""),
):
    with connect() as conn:
        cursor = conn.execute(
            "INSERT INTO fields (user_id, field_code, district, name, area_ha, beet_forbidden, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user["id"], field_code, district or None, name or None, area_ha, int(beet_forbidden), notes or None),
        )
        field_id = cursor.lastrowid
    field = _fetch_field(user["id"], field_id)
    return templates.TemplateResponse(request, "fields/_row.html", {"field": field})


@router.get("/{field_id}/edit", response_class=HTMLResponse)
def edit_field_form(request: Request, user: CurrentUser, field_id: int):
    field = _fetch_field(user["id"], field_id)
    return templates.TemplateResponse(request, "fields/_form.html", {"field": field})


@router.get("/{field_id}", response_class=HTMLResponse)
def get_field_row(request: Request, user: CurrentUser, field_id: int):
    field = _fetch_field(user["id"], field_id)
    return templates.TemplateResponse(request, "fields/_row.html", {"field": field})


@router.put("/{field_id}", response_class=HTMLResponse)
def update_field(
    request: Request,
    user: CurrentUser,
    field_id: int,
    field_code: str = Form(...),
    name: str = Form(""),
    district: str = Form(""),
    area_ha: float = Form(...),
    beet_forbidden: bool = Form(False),
    notes: str = Form(""),
):
    with connect() as conn:
        result = conn.execute(
            "UPDATE fields SET field_code=?, district=?, name=?, area_ha=?, beet_forbidden=?, notes=?, "
            "updated_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?",
            (field_code, district or None, name or None, area_ha, int(beet_forbidden), notes or None,
             field_id, user["id"]),
        )
        if result.rowcount == 0:
            raise HTTPException(404, "ほ場が見つかりません")
    field = _fetch_field(user["id"], field_id)
    return templates.TemplateResponse(request, "fields/_row.html", {"field": field})


@router.delete("/{field_id}")
def delete_field(user: CurrentUser, field_id: int):
    with connect() as conn:
        result = conn.execute(
            "DELETE FROM fields WHERE id = ? AND user_id = ?", (field_id, user["id"])
        )
        if result.rowcount == 0:
            raise HTTPException(404, "ほ場が見つかりません")
    return Response(status_code=200)


@router.get("/{field_id}/polygon")
def polygon_editor(request: Request, user: CurrentUser, field_id: int):
    with connect() as conn:
        row = conn.execute(
            "SELECT id, field_code, name, coordinates_json FROM fields "
            "WHERE id = ? AND user_id = ?",
            (field_id, user["id"]),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "ほ場が見つかりません")

    existing = None
    if row["coordinates_json"]:
        try:
            existing = json.loads(row["coordinates_json"])
        except json.JSONDecodeError:
            existing = None
    return templates.TemplateResponse(
        request,
        "fields/polygon.html",
        {
            "user": user,
            "field": dict(row),
            "map_data": {
                "center": SAPPORO,
                "zoom": 10,
                "geojson": existing,
            },
        },
    )


@router.post("/{field_id}/polygon")
def save_polygon(user: CurrentUser, field_id: int, geojson: str = Form("")):
    geojson = geojson.strip()
    if geojson:
        try:
            parsed = json.loads(geojson)
        except json.JSONDecodeError:
            raise HTTPException(400, "GeoJSON のパースに失敗")
        geom_type = parsed.get("geometry", {}).get("type") if parsed.get("type") == "Feature" else parsed.get("type")
        if geom_type != "Polygon":
            raise HTTPException(400, f"Polygon 以外は受け付けません (type={geom_type})")
        value = json.dumps(parsed, ensure_ascii=False)
    else:
        value = None
    with connect() as conn:
        result = conn.execute(
            "UPDATE fields SET coordinates_json=?, updated_at=CURRENT_TIMESTAMP "
            "WHERE id=? AND user_id=?",
            (value, field_id, user["id"]),
        )
        if result.rowcount == 0:
            raise HTTPException(404, "ほ場が見つかりません")
    return RedirectResponse("/fields/", status_code=303)
