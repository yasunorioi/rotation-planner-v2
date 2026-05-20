"""農薬マスタ CRUD — 名前・作物・希釈倍率・用途・備考のメタデータ。

組織 (org_id) スコープではなくグローバル共有 (org_id NULL) のレコードを扱う。
防除記録 form の datalist のソースとして利用。
"""
import csv
import io
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates

from app.auth import CurrentUser
from app.db import connect

router = APIRouter(prefix="/pesticide-masters")
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)


def _fetch_masters() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, name, crop, dilution_rate, application_method, "
            "usage_timing, notes FROM pesticide_masters ORDER BY name"
        ).fetchall()
    return [dict(r) for r in rows]


def _fetch_master(master_id: int) -> dict:
    with connect() as conn:
        row = conn.execute(
            "SELECT id, name, crop, dilution_rate, application_method, "
            "usage_timing, notes FROM pesticide_masters WHERE id = ?",
            (master_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "農薬マスタが見つかりません")
    return dict(row)


@router.get("/")
def list_masters(request: Request, user: CurrentUser):
    masters = _fetch_masters()
    return templates.TemplateResponse(
        request, "pesticide_masters/list.html",
        {"user": user, "masters": masters},
    )


@router.get("/template.csv")
def template_csv():
    body = ("農薬名,対象作物,希釈倍率,用途,使用時期,備考\n"
            "ベンレート水和剤,てんさい,1000倍,殺菌,5月,例: 褐斑病対策\n").encode("utf-8-sig")
    return StreamingResponse(
        io.BytesIO(body),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="pesticide_masters_template.csv"'},
    )


@router.get("/export.csv")
def export_csv(user: CurrentUser):
    masters = _fetch_masters()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["農薬名", "対象作物", "希釈倍率", "用途", "使用時期", "備考"])
    for m in masters:
        w.writerow([
            m["name"], m["crop"] or "", m["dilution_rate"] or "",
            m["application_method"] or "", m["usage_timing"] or "", m["notes"] or "",
        ])
    return StreamingResponse(
        io.BytesIO(buf.getvalue().encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="pesticide_masters.csv"'},
    )


_NAME_ALIASES = {"農薬名", "name", "pesticide_name"}
_CROP_ALIASES = {"対象作物", "作物", "crop"}
_DIL_ALIASES = {"希釈倍率", "dilution_rate"}
_APP_ALIASES = {"用途", "対象", "application_method", "target"}
_TIMING_ALIASES = {"使用時期", "時期", "usage_timing", "period"}
_NOTES_ALIASES = {"備考", "notes"}


@router.post("/import")
async def import_csv(request: Request, user: CurrentUser, file: UploadFile = File(...)):
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

    col = {"name": None, "crop": None, "dilution": None, "app": None, "timing": None, "notes": None}
    for i, h in enumerate(headers):
        hs = (h or "").strip()
        if hs in _NAME_ALIASES: col["name"] = i
        elif hs in _CROP_ALIASES: col["crop"] = i
        elif hs in _DIL_ALIASES: col["dilution"] = i
        elif hs in _APP_ALIASES: col["app"] = i
        elif hs in _TIMING_ALIASES: col["timing"] = i
        elif hs in _NOTES_ALIASES: col["notes"] = i
    if col["name"] is None:
        raise HTTPException(400, "ヘッダ「農薬名」(name) が見つかりません")

    added = 0
    updated = 0
    errors: list[str] = []
    with connect() as conn:
        for ri, row in enumerate(reader, start=2):
            if not row or all((c or "").strip() == "" for c in row):
                continue
            def cell(k):
                idx = col[k]
                if idx is None or idx >= len(row):
                    return ""
                return (row[idx] or "").strip()
            name = cell("name")
            if not name:
                errors.append(f"{ri}行目: 農薬名が空")
                continue
            crop = cell("crop") or None
            dil = cell("dilution") or None
            app = cell("app") or None
            timing = cell("timing") or None
            notes = cell("notes") or None
            # 同名 (name + crop) で upsert
            existing = conn.execute(
                "SELECT id FROM pesticide_masters WHERE name = ? "
                "AND COALESCE(crop, '') = COALESCE(?, '')",
                (name, crop),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE pesticide_masters SET dilution_rate=?, application_method=?, "
                    "usage_timing=?, notes=? WHERE id=?",
                    (dil, app, timing, notes, existing["id"]),
                )
                updated += 1
            else:
                conn.execute(
                    "INSERT INTO pesticide_masters (name, crop, dilution_rate, "
                    "application_method, usage_timing, notes) VALUES (?, ?, ?, ?, ?, ?)",
                    (name, crop, dil, app, timing, notes),
                )
                added += 1

    summary = f"取込完了: 追加 {added} / 更新 {updated}"
    if errors:
        summary += f" / エラー {len(errors)} 件"
    return templates.TemplateResponse(
        request, "pesticide_masters/_import_result.html",
        {"summary": summary, "errors": errors[:20]},
    )


@router.get("/new", response_class=HTMLResponse)
def new_form(request: Request, user: CurrentUser):
    return templates.TemplateResponse(
        request, "pesticide_masters/_form.html", {"master": None}
    )


@router.post("/", response_class=HTMLResponse)
def create_master(
    request: Request, user: CurrentUser,
    name: str = Form(...),
    crop: str = Form(""),
    dilution_rate: str = Form(""),
    application_method: str = Form(""),
    usage_timing: str = Form(""),
    notes: str = Form(""),
):
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO pesticide_masters (name, crop, dilution_rate, "
            "application_method, usage_timing, notes) VALUES (?, ?, ?, ?, ?, ?)",
            (name, crop or None, dilution_rate or None,
             application_method or None, usage_timing or None, notes or None),
        )
        mid = cur.lastrowid
    return templates.TemplateResponse(
        request, "pesticide_masters/_row.html", {"master": _fetch_master(mid)}
    )


@router.get("/{master_id}/edit", response_class=HTMLResponse)
def edit_form(request: Request, user: CurrentUser, master_id: int):
    return templates.TemplateResponse(
        request, "pesticide_masters/_form.html",
        {"master": _fetch_master(master_id)},
    )


@router.put("/{master_id}", response_class=HTMLResponse)
def update_master(
    request: Request, user: CurrentUser, master_id: int,
    name: str = Form(...),
    crop: str = Form(""),
    dilution_rate: str = Form(""),
    application_method: str = Form(""),
    usage_timing: str = Form(""),
    notes: str = Form(""),
):
    with connect() as conn:
        result = conn.execute(
            "UPDATE pesticide_masters SET name=?, crop=?, dilution_rate=?, "
            "application_method=?, usage_timing=?, notes=? WHERE id=?",
            (name, crop or None, dilution_rate or None,
             application_method or None, usage_timing or None, notes or None,
             master_id),
        )
        if result.rowcount == 0:
            raise HTTPException(404, "農薬マスタが見つかりません")
    return templates.TemplateResponse(
        request, "pesticide_masters/_row.html",
        {"master": _fetch_master(master_id)},
    )


@router.delete("/{master_id}")
def delete_master(user: CurrentUser, master_id: int):
    with connect() as conn:
        result = conn.execute(
            "DELETE FROM pesticide_masters WHERE id = ?", (master_id,)
        )
        if result.rowcount == 0:
            raise HTTPException(404, "農薬マスタが見つかりません")
    return Response(status_code=200)
