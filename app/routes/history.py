"""作付履歴 CRUD — ほ場 × 年 のピボット表で HTMX セル単位編集。

`crop_history` テーブルは (field_id, year) UNIQUE。crop が空文字列なら行を消す。
"""
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.auth import CurrentUser
from app.db import connect
from rotation_planner.common.year_utils import generate_year_choices

router = APIRouter(prefix="/history")
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _year_range(from_y: str | None, to_y: str | None) -> list[str]:
    """`from`〜`to` を含む令和年のリストを返す。未指定時は現在年度±数年。"""
    if from_y and to_y and from_y.startswith("R") and to_y.startswith("R"):
        try:
            start, end = int(from_y[1:]), int(to_y[1:])
            if start <= end:
                return [f"R{n}" for n in range(start, end + 1)]
        except ValueError:
            pass
    return generate_year_choices(start_offset=-3, end_offset=2)


def _ensure_field_owned(conn, user_id: int, field_id: int) -> None:
    row = conn.execute(
        "SELECT 1 FROM fields WHERE id = ? AND user_id = ?", (field_id, user_id)
    ).fetchone()
    if row is None:
        raise HTTPException(404, "ほ場が見つかりません")


@router.get("/", response_class=HTMLResponse)
def history_list(
    request: Request,
    user: CurrentUser,
    from_y: str | None = Query(None, alias="from"),
    to_y: str | None = Query(None, alias="to"),
):
    years = _year_range(from_y, to_y)
    with connect() as conn:
        fields = conn.execute(
            "SELECT id, field_code, name FROM fields WHERE user_id = ? ORDER BY field_code",
            (user["id"],),
        ).fetchall()
        rows = conn.execute(
            "SELECT h.field_id, h.year, h.crop FROM crop_history h "
            "JOIN fields f ON h.field_id = f.id WHERE f.user_id = ?",
            (user["id"],),
        ).fetchall()
    grid: dict[tuple[int, str], str] = {(r["field_id"], r["year"]): r["crop"] for r in rows}
    return templates.TemplateResponse(
        request,
        "history/list.html",
        {
            "user": user,
            "years": years,
            "fields": [dict(f) for f in fields],
            "grid": grid,
            "from_y": years[0],
            "to_y": years[-1],
        },
    )


def _read_cell(conn, field_id: int, year: str) -> str:
    row = conn.execute(
        "SELECT crop FROM crop_history WHERE field_id = ? AND year = ?",
        (field_id, year),
    ).fetchone()
    return row["crop"] if row else ""


@router.get("/cell", response_class=HTMLResponse)
def cell_display(
    request: Request,
    user: CurrentUser,
    field_id: int,
    year: str,
):
    """表示モード (Esc キャンセル時にこれへ戻る)。"""
    with connect() as conn:
        _ensure_field_owned(conn, user["id"], field_id)
        crop = _read_cell(conn, field_id, year)
    return templates.TemplateResponse(
        request,
        "history/_cell.html",
        {"field_id": field_id, "year": year, "crop": crop},
    )


@router.get("/cell/edit", response_class=HTMLResponse)
def cell_edit(
    request: Request,
    user: CurrentUser,
    field_id: int,
    year: str,
):
    """編集モード (input フィールドにフォーカス)。"""
    with connect() as conn:
        _ensure_field_owned(conn, user["id"], field_id)
        crop = _read_cell(conn, field_id, year)
    return templates.TemplateResponse(
        request,
        "history/_cell_edit.html",
        {"field_id": field_id, "year": year, "crop": crop},
    )


@router.post("/cell", response_class=HTMLResponse)
def cell_save(
    request: Request,
    user: CurrentUser,
    field_id: int = Form(...),
    year: str = Form(...),
    crop: str = Form(""),
):
    crop = crop.strip()
    with connect() as conn:
        _ensure_field_owned(conn, user["id"], field_id)
        if crop:
            conn.execute(
                "INSERT INTO crop_history (field_id, year, crop) VALUES (?, ?, ?) "
                "ON CONFLICT(field_id, year) DO UPDATE SET crop = excluded.crop",
                (field_id, year, crop),
            )
        else:
            conn.execute(
                "DELETE FROM crop_history WHERE field_id = ? AND year = ?",
                (field_id, year),
            )
    return templates.TemplateResponse(
        request,
        "history/_cell.html",
        {"field_id": field_id, "year": year, "crop": crop},
    )
