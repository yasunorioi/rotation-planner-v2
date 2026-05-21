"""作物マスタ CRUD — グローバル共有 (organization-scoped ではない)。

DEFAULT_CONSTRAINTS のような optimizer の数値設定ではなく、
作物の分類情報 (category, family) と表示順を管理する。
history/fields の datalist の一次ソース。
"""
import csv
import io
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates

from app.auth import CurrentUser
from app.db import connect

router = APIRouter(prefix="/crop-masters")
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)


def _fetch_all() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, name, category, family, display_order, is_active "
            "FROM crop_master ORDER BY display_order, name"
        ).fetchall()
    return [dict(r) for r in rows]


def _fetch_one(cid: int) -> dict:
    with connect() as conn:
        row = conn.execute(
            "SELECT id, name, category, family, display_order, is_active "
            "FROM crop_master WHERE id = ?",
            (cid,),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "作物マスタが見つかりません")
    return dict(row)


@router.get("/")
def list_crops(request: Request, user: CurrentUser):
    crops = _fetch_all()
    return templates.TemplateResponse(
        request, "crop_masters/list.html",
        {"user": user, "crops": crops},
    )


@router.get("/template.csv")
def template_csv():
    body = ("作物名,分類,科,display_order,is_active\n"
            "そば,穀物,タデ科,11,1\n").encode("utf-8-sig")
    return StreamingResponse(
        io.BytesIO(body),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="crop_master_template.csv"'},
    )


@router.get("/export.csv")
def export_csv(user: CurrentUser):
    crops = _fetch_all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["作物名", "分類", "科", "display_order", "is_active"])
    for c in crops:
        w.writerow([
            c["name"], c["category"] or "", c["family"] or "",
            c["display_order"], "1" if c["is_active"] else "0",
        ])
    return StreamingResponse(
        io.BytesIO(buf.getvalue().encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="crop_master.csv"'},
    )


_NAME_ALIASES = {"作物名", "name"}
_CAT_ALIASES = {"分類", "カテゴリ", "category"}
_FAM_ALIASES = {"科", "family"}
_ORDER_ALIASES = {"display_order", "順序"}
_ACTIVE_ALIASES = {"is_active", "有効"}


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

    col = {"name": None, "cat": None, "fam": None, "order": None, "active": None}
    for i, h in enumerate(headers):
        hs = (h or "").strip()
        if hs in _NAME_ALIASES: col["name"] = i
        elif hs in _CAT_ALIASES: col["cat"] = i
        elif hs in _FAM_ALIASES: col["fam"] = i
        elif hs in _ORDER_ALIASES: col["order"] = i
        elif hs in _ACTIVE_ALIASES: col["active"] = i
    if col["name"] is None:
        raise HTTPException(400, "ヘッダ「作物名」(name) が見つかりません")

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
                errors.append(f"{ri}行目: 作物名が空")
                continue
            cat = cell("cat") or None
            fam = cell("fam") or None
            try:
                order = int(cell("order")) if cell("order") else 0
            except ValueError:
                order = 0
            active = 0 if cell("active") in ("0", "false", "FALSE", "無効") else 1

            existing = conn.execute(
                "SELECT id FROM crop_master WHERE name = ?", (name,)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE crop_master SET category=?, family=?, "
                    "display_order=?, is_active=? WHERE id=?",
                    (cat, fam, order, active, existing["id"]),
                )
                updated += 1
            else:
                conn.execute(
                    "INSERT INTO crop_master (name, category, family, display_order, is_active) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (name, cat, fam, order, active),
                )
                added += 1

    summary = f"取込完了: 追加 {added} / 更新 {updated}"
    if errors:
        summary += f" / エラー {len(errors)} 件"
    return templates.TemplateResponse(
        request, "crop_masters/_import_result.html",
        {"summary": summary, "errors": errors[:20]},
    )


@router.get("/new", response_class=HTMLResponse)
def new_form(request: Request, user: CurrentUser):
    return templates.TemplateResponse(
        request, "crop_masters/_form.html", {"crop": None}
    )


@router.post("/", response_class=HTMLResponse)
def create_crop(
    request: Request, user: CurrentUser,
    name: str = Form(...),
    category: str = Form(""),
    family: str = Form(""),
    display_order: int = Form(0),
    is_active: bool = Form(False),
):
    with connect() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO crop_master (name, category, family, display_order, is_active) "
                "VALUES (?, ?, ?, ?, ?)",
                (name, category or None, family or None, display_order, int(is_active)),
            )
        except Exception as e:
            raise HTTPException(400, f"追加失敗: {e}")
        cid = cur.lastrowid
    return templates.TemplateResponse(
        request, "crop_masters/_row.html", {"crop": _fetch_one(cid)}
    )


@router.get("/{cid}/edit", response_class=HTMLResponse)
def edit_form(request: Request, user: CurrentUser, cid: int):
    return templates.TemplateResponse(
        request, "crop_masters/_form.html", {"crop": _fetch_one(cid)}
    )


@router.put("/{cid}", response_class=HTMLResponse)
def update_crop(
    request: Request, user: CurrentUser, cid: int,
    name: str = Form(...),
    category: str = Form(""),
    family: str = Form(""),
    display_order: int = Form(0),
    is_active: bool = Form(False),
):
    with connect() as conn:
        result = conn.execute(
            "UPDATE crop_master SET name=?, category=?, family=?, "
            "display_order=?, is_active=? WHERE id=?",
            (name, category or None, family or None, display_order, int(is_active), cid),
        )
        if result.rowcount == 0:
            raise HTTPException(404, "作物マスタが見つかりません")
    return templates.TemplateResponse(
        request, "crop_masters/_row.html", {"crop": _fetch_one(cid)}
    )


@router.delete("/{cid}")
def delete_crop(user: CurrentUser, cid: int):
    with connect() as conn:
        result = conn.execute("DELETE FROM crop_master WHERE id = ?", (cid,))
        if result.rowcount == 0:
            raise HTTPException(404, "作物マスタが見つかりません")
    return Response(status_code=200)
