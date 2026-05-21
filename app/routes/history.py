"""作付履歴 CRUD — ほ場 × 年 のピボット表で HTMX セル単位編集。

`crop_history` テーブルは (field_id, year) UNIQUE。crop が空文字列なら行を消す。
"""
import csv
import io
import re
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

_FIELD_CODE_ALIASES = {"ほ場ID", "field_code", "圃場コード", "field_id"}
_NAME_ALIASES = {"ほ場名", "圃場名", "name"}
_YEAR_PATTERN = re.compile(r"^R\d+$")

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


def _crop_suggestions(user_id: int) -> list[str]:
    """作物候補リスト。
    一次: crop_master (is_active=1, display_order 順)
    二次: ユーザの履歴に登場した作物 (マスタにないもの)
    三次: ユーザの計画 constraints に登場した作物 (マスタにないもの)
    """
    import json as _json

    seen: dict[str, None] = {}
    with connect() as conn:
        for r in conn.execute(
            "SELECT name FROM crop_master WHERE is_active = 1 "
            "ORDER BY display_order, name"
        ):
            seen.setdefault(r["name"], None)
        for r in conn.execute(
            "SELECT DISTINCT h.crop FROM crop_history h "
            "JOIN fields f ON h.field_id = f.id "
            "WHERE f.user_id = ? AND h.crop IS NOT NULL AND h.crop != ''",
            (user_id,),
        ):
            if r["crop"]:
                seen.setdefault(r["crop"], None)
        for r in conn.execute(
            "SELECT constraints_json FROM rotation_plans "
            "WHERE user_id = ? AND constraints_json IS NOT NULL",
            (user_id,),
        ):
            try:
                obj = _json.loads(r["constraints_json"])
                if isinstance(obj, dict):
                    for c in obj.keys():
                        seen.setdefault(c, None)
            except (TypeError, _json.JSONDecodeError):
                pass
    return list(seen.keys())


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


@router.get("/template.csv")
def history_template():
    years = generate_year_choices(start_offset=-3, end_offset=2)
    header = ["ほ場ID", "ほ場名"] + years
    sample = ["F001", "北1号"] + ["" for _ in years]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerow(sample)
    return StreamingResponse(
        io.BytesIO(buf.getvalue().encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="crop_history_template.csv"'},
    )


@router.post("/import")
async def import_history(
    request: Request,
    user: CurrentUser,
    file: UploadFile = File(...),
):
    """ピボット形式 (ほ場ID + R年列) の CSV を取り込んで履歴をupsert。
    既存ほ場のみ対象。未登録の field_code はエラーとして記録。"""
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = raw.decode("cp932")
        except UnicodeDecodeError:
            raise HTTPException(400, "CSV のデコードに失敗")

    reader = csv.reader(io.StringIO(text))
    try:
        headers = next(reader)
    except StopIteration:
        raise HTTPException(400, "CSV が空です")

    code_col = None
    year_cols: list[tuple[int, str]] = []
    for i, h in enumerate(headers):
        hs = (h or "").strip()
        if hs in _FIELD_CODE_ALIASES:
            code_col = i
        elif _YEAR_PATTERN.match(hs):
            year_cols.append((i, hs))
    if code_col is None:
        raise HTTPException(400, "ヘッダ「ほ場ID」が見つかりません")
    if not year_cols:
        raise HTTPException(400, "年列 (R5, R6 等) が見つかりません")

    upserted = 0
    deleted = 0
    errors: list[str] = []

    with connect() as conn:
        field_map = {
            r["field_code"]: r["id"]
            for r in conn.execute(
                "SELECT id, field_code FROM fields WHERE user_id = ?", (user["id"],)
            ).fetchall()
        }
        for row_idx, row in enumerate(reader, start=2):
            if not row or all((c or "").strip() == "" for c in row):
                continue
            if code_col >= len(row):
                continue
            code = row[code_col].strip()
            if not code:
                continue
            field_db_id = field_map.get(code)
            if field_db_id is None:
                errors.append(f"{row_idx}行目: 未登録のほ場「{code}」")
                continue
            for col_idx, year in year_cols:
                if col_idx >= len(row):
                    continue
                crop = row[col_idx].strip()
                if crop:
                    conn.execute(
                        "INSERT INTO crop_history (field_id, year, crop) VALUES (?, ?, ?) "
                        "ON CONFLICT(field_id, year) DO UPDATE SET crop = excluded.crop",
                        (field_db_id, year, crop),
                    )
                    upserted += 1
                else:
                    result = conn.execute(
                        "DELETE FROM crop_history WHERE field_id = ? AND year = ?",
                        (field_db_id, year),
                    )
                    deleted += result.rowcount

    summary = f"取込完了: upsert {upserted} / delete {deleted}"
    if errors:
        summary += f" / エラー {len(errors)} 件"
    return templates.TemplateResponse(
        request,
        "history/_import_result.html",
        {"summary": summary, "errors": errors[:20]},
    )


@router.get("/export.csv")
def export_history_csv(
    user: CurrentUser,
    from_y: str | None = Query(None, alias="from"),
    to_y: str | None = Query(None, alias="to"),
):
    """履歴ピボットを CSV 出力 (BOM 付き UTF-8)。"""
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
    grid = {(r["field_id"], r["year"]): r["crop"] for r in rows}

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["ほ場ID", "ほ場名"] + years)
    for f in fields:
        w.writerow(
            [f["field_code"], f["name"] or ""]
            + [grid.get((f["id"], y), "") for y in years]
        )
    buf.seek(0)
    fname = f'crop_history_{years[0]}-{years[-1]}.csv'
    return StreamingResponse(
        io.BytesIO(buf.getvalue().encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


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
    """編集モード (input フィールドにフォーカス、datalist で作物候補)。"""
    with connect() as conn:
        _ensure_field_owned(conn, user["id"], field_id)
        crop = _read_cell(conn, field_id, year)
    return templates.TemplateResponse(
        request,
        "history/_cell_edit.html",
        {
            "field_id": field_id,
            "year": year,
            "crop": crop,
            "crops": _crop_suggestions(user["id"]),
        },
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
