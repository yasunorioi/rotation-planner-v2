"""ほ場 CRUD — HTMX で行単位 add/edit/delete。ポリゴン編集は別ページ。"""
import csv
import io
import json
import re
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates

from app.auth import CurrentUser
from app.db import connect

SAPPORO = [43.0642, 141.3469]  # ポリゴン未登録時のデフォルト中心

# CSV ヘッダの別名 (v1 テンプレートとの互換性)
_FIELD_CODE_ALIASES = {"ほ場ID", "field_code", "圃場コード", "field_id"}
_DISTRICT_ALIASES = {"地区", "district"}
_NAME_ALIASES = {"ほ場名", "圃場名", "name"}
_AREA_HA_ALIASES = {"area_ha", "面積_ha", "area(ha)"}
_AREA_A_ALIASES = {"area", "area_a", "面積_a", "面積(a)", "面積"}  # アール
_BEET_ALIASES = {"beet_forbidden", "てんさい禁忌"}
_NOTES_ALIASES = {"notes", "備考", "メモ"}
_YEAR_PATTERN = re.compile(r"^R\d+$")

router = APIRouter(prefix="/fields")
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


_FIELD_COLS = (
    "id, field_code, district, name, area_ha, beet_forbidden, notes, "
    "(coordinates_json IS NOT NULL) AS has_polygon"
)


def _fetch_fields(user_id: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            f"SELECT {_FIELD_COLS} FROM fields WHERE user_id = ? ORDER BY field_code",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def _fetch_field(user_id: int, field_id: int) -> dict:
    with connect() as conn:
        row = conn.execute(
            f"SELECT {_FIELD_COLS} FROM fields WHERE id = ? AND user_id = ?",
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


@router.get("/template.csv")
def download_template():
    """v1 互換の CSV テンプレートを返す。"""
    header = "ほ場ID,地区,ほ場名,area,beet_forbidden,R5,R6,R7,R8\n"
    sample = "F001,北地区,北1号,280,0,春小麦,大豆,秋小麦,てんさい\n"
    body = (header + sample).encode("utf-8-sig")
    return StreamingResponse(
        io.BytesIO(body),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="fields_template.csv"'},
    )


@router.get("/export.csv")
def export_fields_csv(user: CurrentUser):
    """ほ場 (+ 履歴) を CSV エクスポート。インポート CSV と互換。"""
    with connect() as conn:
        fields = conn.execute(
            "SELECT id, field_code, district, name, area_ha, beet_forbidden, notes "
            "FROM fields WHERE user_id = ? ORDER BY field_code",
            (user["id"],),
        ).fetchall()
        rows = conn.execute(
            "SELECT h.field_id, h.year, h.crop FROM crop_history h "
            "JOIN fields f ON h.field_id = f.id WHERE f.user_id = ?",
            (user["id"],),
        ).fetchall()
    history: dict[int, dict[str, str]] = {}
    year_set: set[str] = set()
    for r in rows:
        history.setdefault(r["field_id"], {})[r["year"]] = r["crop"]
        year_set.add(r["year"])
    years = sorted(year_set, key=lambda y: int(y[1:]) if y.startswith("R") and y[1:].isdigit() else 0)

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["ほ場ID", "地区", "ほ場名", "area", "beet_forbidden", "備考"] + years)
    for f in fields:
        w.writerow([
            f["field_code"], f["district"] or "", f["name"] or "",
            f"{f['area_ha'] * 100:.1f}",  # ha → a
            "1" if f["beet_forbidden"] else "0",
            f["notes"] or "",
        ] + [history.get(f["id"], {}).get(y, "") for y in years])
    buf.seek(0)
    return StreamingResponse(
        io.BytesIO(buf.getvalue().encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="fields.csv"'},
    )


def _match_alias(name: str, aliases: set[str]) -> bool:
    return name.strip() in aliases


def _classify_columns(headers: list[str]) -> dict:
    """CSV ヘッダから列マッピングを構築。"""
    mapping = {
        "field_code": None,
        "district": None,
        "name": None,
        "area_ha": None,
        "area_a": None,
        "beet_forbidden": None,
        "notes": None,
        "years": [],  # list of (col_index, year_str)
    }
    for i, h in enumerate(headers):
        hs = (h or "").strip()
        if _match_alias(hs, _FIELD_CODE_ALIASES):
            mapping["field_code"] = i
        elif _match_alias(hs, _DISTRICT_ALIASES):
            mapping["district"] = i
        elif _match_alias(hs, _NAME_ALIASES):
            mapping["name"] = i
        elif _match_alias(hs, _AREA_HA_ALIASES):
            mapping["area_ha"] = i
        elif _match_alias(hs, _AREA_A_ALIASES):
            mapping["area_a"] = i
        elif _match_alias(hs, _BEET_ALIASES):
            mapping["beet_forbidden"] = i
        elif _match_alias(hs, _NOTES_ALIASES):
            mapping["notes"] = i
        elif _YEAR_PATTERN.match(hs):
            mapping["years"].append((i, hs))
    return mapping


@router.post("/import")
async def import_csv(
    request: Request,
    user: CurrentUser,
    file: UploadFile = File(...),
):
    """v1 互換のCSV を取り込む。ほ場をupsert、年列があれば作付履歴もupsert。"""
    raw = await file.read()
    # BOM 付き UTF-8 を許容
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = raw.decode("cp932")  # 古いExcel保存への保険
        except UnicodeDecodeError:
            raise HTTPException(400, "CSV のデコードに失敗 (UTF-8 もしくは CP932 で保存してください)")

    reader = csv.reader(io.StringIO(text))
    try:
        headers = next(reader)
    except StopIteration:
        raise HTTPException(400, "CSV が空です")
    cols = _classify_columns(headers)
    if cols["field_code"] is None:
        raise HTTPException(400, "ヘッダ「ほ場ID」(または field_code) が見つかりません")
    if cols["area_ha"] is None and cols["area_a"] is None:
        raise HTTPException(400, "ヘッダ「area」(アール) もしくは「area_ha」が見つかりません")

    added = 0
    updated = 0
    history_added = 0
    errors: list[str] = []

    with connect() as conn:
        for row_idx, row in enumerate(reader, start=2):
            if not row or all((c or "").strip() == "" for c in row):
                continue
            try:
                code = row[cols["field_code"]].strip()
                if not code:
                    errors.append(f"{row_idx}行目: ほ場IDが空")
                    continue
                if cols["area_ha"] is not None:
                    area_ha = float(row[cols["area_ha"]])
                else:
                    area_ha = float(row[cols["area_a"]]) / 100.0
                district = row[cols["district"]].strip() if cols["district"] is not None and cols["district"] < len(row) else None
                name = row[cols["name"]].strip() if cols["name"] is not None and cols["name"] < len(row) else None
                beet = 0
                if cols["beet_forbidden"] is not None and cols["beet_forbidden"] < len(row):
                    raw_b = row[cols["beet_forbidden"]].strip().lower()
                    beet = 1 if raw_b in ("1", "true", "yes", "禁") else 0
                notes = row[cols["notes"]].strip() if cols["notes"] is not None and cols["notes"] < len(row) else None
            except (ValueError, IndexError) as e:
                errors.append(f"{row_idx}行目: {e}")
                continue

            # Upsert field
            existing = conn.execute(
                "SELECT id FROM fields WHERE user_id = ? AND field_code = ?",
                (user["id"], code),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE fields SET district=?, name=?, area_ha=?, beet_forbidden=?, "
                    "notes=COALESCE(?, notes), updated_at=CURRENT_TIMESTAMP "
                    "WHERE id=?",
                    (district or None, name or None, area_ha, beet, notes or None, existing["id"]),
                )
                field_db_id = existing["id"]
                updated += 1
            else:
                cur = conn.execute(
                    "INSERT INTO fields (user_id, field_code, district, name, area_ha, beet_forbidden, notes) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (user["id"], code, district or None, name or None, area_ha, beet, notes or None),
                )
                field_db_id = cur.lastrowid
                added += 1

            # 年列があれば履歴も upsert
            for col_idx, year in cols["years"]:
                if col_idx >= len(row):
                    continue
                crop = row[col_idx].strip()
                if not crop:
                    continue
                conn.execute(
                    "INSERT INTO crop_history (field_id, year, crop) VALUES (?, ?, ?) "
                    "ON CONFLICT(field_id, year) DO UPDATE SET crop = excluded.crop",
                    (field_db_id, year, crop),
                )
                history_added += 1

    summary = f"取込完了: 追加 {added} / 更新 {updated} / 履歴 {history_added}"
    if errors:
        summary += f" / エラー {len(errors)} 件"
    return templates.TemplateResponse(
        request,
        "fields/_import_result.html",
        {"summary": summary, "errors": errors[:20]},
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
