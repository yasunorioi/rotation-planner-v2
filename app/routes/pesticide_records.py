"""防除記録 CRUD — 散布日 / ほ場 / 農薬名 / 希釈倍率 / 量 / 単位 / 備考。

写真添付や registry lookup は MVP のスコープ外 (テキスト入力のみ)。
"""
import csv
import io
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates

from app.auth import CurrentUser
from app.db import connect

router = APIRouter(prefix="/pesticide-records")
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


_SELECT = """
SELECT r.id, r.field_id, r.spray_date, r.pesticide_name, r.dilution_rate,
       r.spray_amount, r.spray_unit, r.notes,
       f.field_code, f.name AS field_name
FROM pesticide_records r
JOIN fields f ON r.field_id = f.id
WHERE r.user_id = ?
"""


def _fetch_records(user_id: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            _SELECT + " ORDER BY r.spray_date DESC, r.id DESC", (user_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def _fetch_record(user_id: int, rec_id: int) -> dict:
    with connect() as conn:
        row = conn.execute(_SELECT + " AND r.id = ?", (user_id, rec_id)).fetchone()
    if row is None:
        raise HTTPException(404, "防除記録が見つかりません")
    return dict(row)


def _user_fields(user_id: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, field_code, name FROM fields WHERE user_id = ? ORDER BY field_code",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def _ensure_field_owned(conn, user_id: int, field_id: int) -> None:
    row = conn.execute(
        "SELECT 1 FROM fields WHERE id = ? AND user_id = ?", (field_id, user_id)
    ).fetchone()
    if row is None:
        raise HTTPException(400, "ほ場が選択されていません (または他ユーザのほ場)")


@router.get("/")
def list_records(request: Request, user: CurrentUser):
    records = _fetch_records(user["id"])
    fields = _user_fields(user["id"])
    return templates.TemplateResponse(
        request,
        "pesticide_records/list.html",
        {"user": user, "records": records, "fields": fields},
    )


@router.get("/new", response_class=HTMLResponse)
def new_form(request: Request, user: CurrentUser):
    fields = _user_fields(user["id"])
    return templates.TemplateResponse(
        request, "pesticide_records/_form.html", {"record": None, "fields": fields}
    )


def _opt_float(s: str):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


@router.post("/", response_class=HTMLResponse)
def create_record(
    request: Request,
    user: CurrentUser,
    field_id: int = Form(...),
    spray_date: str = Form(...),
    pesticide_name: str = Form(...),
    dilution_rate: str = Form(""),
    spray_amount: str = Form(""),
    spray_unit: str = Form(""),
    notes: str = Form(""),
):
    amount = _opt_float(spray_amount)
    with connect() as conn:
        _ensure_field_owned(conn, user["id"], field_id)
        cursor = conn.execute(
            "INSERT INTO pesticide_records "
            "(user_id, field_id, spray_date, pesticide_name, dilution_rate, "
            " spray_amount, spray_unit, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user["id"], field_id, spray_date, pesticide_name,
             dilution_rate or None, amount, spray_unit or None, notes or None),
        )
        rec_id = cursor.lastrowid
    record = _fetch_record(user["id"], rec_id)
    return templates.TemplateResponse(
        request, "pesticide_records/_row.html", {"record": record}
    )


@router.get("/export.csv")
def export_csv(user: CurrentUser):
    records = _fetch_records(user["id"])
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["散布日", "ほ場ID", "ほ場名", "農薬名", "希釈倍率", "量", "単位", "備考"])
    for r in records:
        w.writerow([
            r["spray_date"], r["field_code"], r["field_name"] or "",
            r["pesticide_name"], r["dilution_rate"] or "",
            r["spray_amount"] if r["spray_amount"] is not None else "",
            r["spray_unit"] or "", r["notes"] or "",
        ])
    buf.seek(0)
    return StreamingResponse(
        io.BytesIO(buf.getvalue().encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="pesticide_records.csv"'},
    )


@router.get("/{rec_id}/edit", response_class=HTMLResponse)
def edit_form(request: Request, user: CurrentUser, rec_id: int):
    record = _fetch_record(user["id"], rec_id)
    fields = _user_fields(user["id"])
    return templates.TemplateResponse(
        request, "pesticide_records/_form.html", {"record": record, "fields": fields}
    )


@router.put("/{rec_id}", response_class=HTMLResponse)
def update_record(
    request: Request,
    user: CurrentUser,
    rec_id: int,
    field_id: int = Form(...),
    spray_date: str = Form(...),
    pesticide_name: str = Form(...),
    dilution_rate: str = Form(""),
    spray_amount: str = Form(""),
    spray_unit: str = Form(""),
    notes: str = Form(""),
):
    amount = _opt_float(spray_amount)
    with connect() as conn:
        _ensure_field_owned(conn, user["id"], field_id)
        result = conn.execute(
            "UPDATE pesticide_records SET field_id=?, spray_date=?, pesticide_name=?, "
            "dilution_rate=?, spray_amount=?, spray_unit=?, notes=?, "
            "updated_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?",
            (field_id, spray_date, pesticide_name, dilution_rate or None,
             amount, spray_unit or None, notes or None, rec_id, user["id"]),
        )
        if result.rowcount == 0:
            raise HTTPException(404, "防除記録が見つかりません")
    record = _fetch_record(user["id"], rec_id)
    return templates.TemplateResponse(
        request, "pesticide_records/_row.html", {"record": record}
    )


@router.delete("/{rec_id}")
def delete_record(user: CurrentUser, rec_id: int):
    with connect() as conn:
        result = conn.execute(
            "DELETE FROM pesticide_records WHERE id = ? AND user_id = ?",
            (rec_id, user["id"]),
        )
        if result.rowcount == 0:
            raise HTTPException(404, "防除記録が見つかりません")
    return Response(status_code=200)
