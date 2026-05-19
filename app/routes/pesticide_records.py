"""防除記録 CRUD — 散布日 / ほ場 / 農薬名 / 希釈倍率 / 量 / 単位 / 備考。

写真添付や registry lookup は MVP のスコープ外 (テキスト入力のみ)。
"""
import csv
import io
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates

_FIELD_CODE_ALIASES = {"ほ場ID", "field_code", "圃場コード", "field_id"}
_DATE_ALIASES = {"散布日", "spray_date", "date"}
_NAME_ALIASES = {"農薬名", "pesticide_name", "name"}
_DIL_ALIASES = {"希釈倍率", "dilution_rate"}
_AMOUNT_ALIASES = {"量", "spray_amount", "amount"}
_UNIT_ALIASES = {"単位", "spray_unit", "unit"}
_NOTES_ALIASES = {"備考", "notes", "メモ"}

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
"""


def _build_record_filter(user_id: int, year: str | None, field_id: int | None) -> tuple[str, list]:
    clauses = ["r.user_id = ?"]
    params: list = [user_id]
    if year:
        clauses.append("strftime('%Y', r.spray_date) = ?")
        params.append(year)
    if field_id:
        clauses.append("r.field_id = ?")
        params.append(field_id)
    return " WHERE " + " AND ".join(clauses), params


def _fetch_records(
    user_id: int,
    year: str | None = None,
    field_id: int | None = None,
) -> list[dict]:
    where_sql, params = _build_record_filter(user_id, year, field_id)
    with connect() as conn:
        rows = conn.execute(
            _SELECT + where_sql + " ORDER BY r.spray_date DESC, r.id DESC",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def _fetch_record(user_id: int, rec_id: int) -> dict:
    with connect() as conn:
        row = conn.execute(
            _SELECT + " WHERE r.user_id = ? AND r.id = ?", (user_id, rec_id)
        ).fetchone()
    if row is None:
        raise HTTPException(404, "防除記録が見つかりません")
    return dict(row)


def _available_years(user_id: int) -> list[str]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT strftime('%Y', spray_date) AS y FROM pesticide_records "
            "WHERE user_id = ? ORDER BY y DESC",
            (user_id,),
        ).fetchall()
    return [r["y"] for r in rows if r["y"]]


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
def list_records(
    request: Request,
    user: CurrentUser,
    year: str | None = None,
    field_id: int | None = None,
):
    records = _fetch_records(user["id"], year=year, field_id=field_id)
    fields = _user_fields(user["id"])
    return templates.TemplateResponse(
        request,
        "pesticide_records/list.html",
        {
            "user": user,
            "records": records,
            "fields": fields,
            "available_years": _available_years(user["id"]),
            "filter_year": year or "",
            "filter_field_id": field_id or "",
        },
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


@router.get("/template.csv")
def pesticide_template():
    header = "散布日,ほ場ID,農薬名,希釈倍率,量,単位,備考\n"
    sample = "2026-05-10,F001,ベンレート水和剤,1000倍,0.3,L/10a,\n"
    return StreamingResponse(
        io.BytesIO((header + sample).encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="pesticide_records_template.csv"'},
    )


@router.post("/import")
async def import_records(
    request: Request,
    user: CurrentUser,
    file: UploadFile = File(...),
):
    """防除記録を CSV から取り込む。常に INSERT (upsert ではない)。"""
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

    col_map: dict[str, int | None] = {
        "date": None, "code": None, "name": None,
        "dilution": None, "amount": None, "unit": None, "notes": None,
    }
    for i, h in enumerate(headers):
        hs = (h or "").strip()
        if hs in _DATE_ALIASES:
            col_map["date"] = i
        elif hs in _FIELD_CODE_ALIASES:
            col_map["code"] = i
        elif hs in _NAME_ALIASES:
            col_map["name"] = i
        elif hs in _DIL_ALIASES:
            col_map["dilution"] = i
        elif hs in _AMOUNT_ALIASES:
            col_map["amount"] = i
        elif hs in _UNIT_ALIASES:
            col_map["unit"] = i
        elif hs in _NOTES_ALIASES:
            col_map["notes"] = i

    for required in ("date", "code", "name"):
        if col_map[required] is None:
            raise HTTPException(400, f"必須ヘッダ「{required}」(散布日/ほ場ID/農薬名) が見つかりません")

    added = 0
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
            def cell(key: str, default: str = "") -> str:
                idx = col_map[key]
                if idx is None or idx >= len(row):
                    return default
                return (row[idx] or "").strip()
            code = cell("code")
            date = cell("date")
            name = cell("name")
            if not (code and date and name):
                errors.append(f"{row_idx}行目: 必須欄が空")
                continue
            fid = field_map.get(code)
            if fid is None:
                errors.append(f"{row_idx}行目: 未登録のほ場「{code}」")
                continue
            amount = _opt_float(cell("amount"))
            conn.execute(
                "INSERT INTO pesticide_records "
                "(user_id, field_id, spray_date, pesticide_name, dilution_rate, "
                " spray_amount, spray_unit, notes) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (user["id"], fid, date, name, cell("dilution") or None,
                 amount, cell("unit") or None, cell("notes") or None),
            )
            added += 1

    summary = f"取込完了: 追加 {added}"
    if errors:
        summary += f" / エラー {len(errors)} 件"
    return templates.TemplateResponse(
        request,
        "pesticide_records/_import_result.html",
        {"summary": summary, "errors": errors[:20]},
    )


@router.get("/export.pdf")
def export_pdf(
    user: CurrentUser,
    year: str | None = None,
    field_id: int | None = None,
):
    from app.pdf_service import generate_pesticide_records_pdf
    records = _fetch_records(user["id"], year=year, field_id=field_id)
    title = "防除記録"
    if year:
        title += f" ({year}年)"
    pdf_bytes = generate_pesticide_records_pdf(records, title=title)
    return Response(
        pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="pesticide_records.pdf"'},
    )


@router.get("/export.csv")
def export_csv(
    user: CurrentUser,
    year: str | None = None,
    field_id: int | None = None,
):
    records = _fetch_records(user["id"], year=year, field_id=field_id)
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
