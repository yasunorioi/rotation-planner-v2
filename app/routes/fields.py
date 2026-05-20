"""ほ場 CRUD — HTMX で行単位 add/edit/delete。ポリゴン編集は別ページ。"""
import csv
import io
import json
import os
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
_FIXED_CROP_ALIASES = {"fixed_crop", "固定作物"}
_NOTES_ALIASES = {"notes", "備考", "メモ"}
_YEAR_PATTERN = re.compile(r"^R\d+$")

router = APIRouter(prefix="/fields")
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


_FIELD_COLS = (
    "id, field_code, district, name, area_ha, beet_forbidden, fixed_crop, notes, "
    "(coordinates_json IS NOT NULL) AS has_polygon"
)


def _crop_suggestions(user_id: int) -> list[str]:
    """fields の form で使う作物候補。history と同じ集合。"""
    from rotation_planner.app import DEFAULT_CONSTRAINTS
    import json as _json

    seen: dict[str, None] = {}
    for c in DEFAULT_CONSTRAINTS.keys():
        seen.setdefault(c, None)
    with connect() as conn:
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


def _build_field_filter(district: str | None, polygon: str | None) -> tuple[str, list]:
    clauses = ["user_id = ?"]
    params: list = []
    if district:
        clauses.append("district = ?")
        params.append(district)
    if polygon == "有":
        clauses.append("coordinates_json IS NOT NULL")
    elif polygon == "無":
        clauses.append("coordinates_json IS NULL")
    return " AND ".join(clauses), params


def _fetch_fields(
    user_id: int,
    district: str | None = None,
    polygon: str | None = None,
) -> list[dict]:
    where_sql, params = _build_field_filter(district, polygon)
    with connect() as conn:
        rows = conn.execute(
            f"SELECT {_FIELD_COLS} FROM fields WHERE {where_sql} ORDER BY field_code",
            ([user_id] + params),
        ).fetchall()
    return [dict(r) for r in rows]


def _distinct_districts(user_id: int) -> list[str]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT district FROM fields "
            "WHERE user_id = ? AND district IS NOT NULL AND district != '' "
            "ORDER BY district",
            (user_id,),
        ).fetchall()
    return [r["district"] for r in rows]


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
def list_fields(
    request: Request,
    user: CurrentUser,
    district: str | None = None,
    polygon: str | None = None,
):
    fields = _fetch_fields(user["id"], district=district, polygon=polygon)
    districts = _distinct_districts(user["id"])
    return templates.TemplateResponse(
        request,
        "fields/list.html",
        {
            "user": user,
            "fields": fields,
            "districts": districts,
            "filter_district": district or "",
            "filter_polygon": polygon or "",
        },
    )


@router.get("/new", response_class=HTMLResponse)
def new_field_form(request: Request, user: CurrentUser):
    return templates.TemplateResponse(
        request, "fields/_form.html",
        {
            "field": None,
            "crops": _crop_suggestions(user["id"]),
            "districts": _distinct_districts(user["id"]),
        },
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
    fixed_crop: str = Form(""),
    notes: str = Form(""),
):
    with connect() as conn:
        cursor = conn.execute(
            "INSERT INTO fields (user_id, field_code, district, name, area_ha, beet_forbidden, fixed_crop, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user["id"], field_code, district or None, name or None, area_ha,
             int(beet_forbidden), fixed_crop.strip() or None, notes or None),
        )
        field_id = cursor.lastrowid
    field = _fetch_field(user["id"], field_id)
    return templates.TemplateResponse(request, "fields/_row.html", {"field": field})


@router.get("/{field_id}/edit", response_class=HTMLResponse)
def edit_field_form(request: Request, user: CurrentUser, field_id: int):
    field = _fetch_field(user["id"], field_id)
    return templates.TemplateResponse(
        request, "fields/_form.html",
        {
            "field": field,
            "crops": _crop_suggestions(user["id"]),
            "districts": _distinct_districts(user["id"]),
        },
    )


@router.get("/{field_id}/detail")
def field_detail(request: Request, user: CurrentUser, field_id: int):
    """1ほ場の年表 + 最近の防除記録。"""
    field = _fetch_field(user["id"], field_id)
    with connect() as conn:
        history_rows = conn.execute(
            "SELECT year, crop, is_inferred, created_at FROM crop_history "
            "WHERE field_id = ? ORDER BY year DESC",
            (field_id,),
        ).fetchall()
        records = conn.execute(
            "SELECT id, spray_date, pesticide_name, dilution_rate, spray_amount, spray_unit, notes "
            "FROM pesticide_records WHERE field_id = ? AND user_id = ? "
            "ORDER BY spray_date DESC, id DESC LIMIT 20",
            (field_id, user["id"]),
        ).fetchall()
    return templates.TemplateResponse(
        request, "fields/detail.html",
        {
            "user": user,
            "field": field,
            "history": [dict(r) for r in history_rows],
            "records": [dict(r) for r in records],
        },
    )


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
    fixed_crop: str = Form(""),
    notes: str = Form(""),
):
    with connect() as conn:
        result = conn.execute(
            "UPDATE fields SET field_code=?, district=?, name=?, area_ha=?, beet_forbidden=?, "
            "fixed_crop=?, notes=?, updated_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?",
            (field_code, district or None, name or None, area_ha, int(beet_forbidden),
             fixed_crop.strip() or None, notes or None,
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


def _geodesic_area_ha(geojson_feature: dict | None) -> float | None:
    """GeoJSON Feature/Geometry から測地線面積(ha)を計算。失敗時 None。"""
    if not geojson_feature:
        return None
    geom = geojson_feature.get("geometry") if geojson_feature.get("type") == "Feature" else geojson_feature
    if not geom or geom.get("type") != "Polygon":
        return None
    coords = geom.get("coordinates") or []
    if not coords or len(coords[0]) < 3:
        return None
    try:
        from shapely.geometry import Polygon as _ShPoly
        from rotation_planner.field.spatial import calculate_geodesic_area_ha
        ring = [(p[0], p[1]) for p in coords[0]]
        return round(calculate_geodesic_area_ha(_ShPoly(ring)), 4)
    except Exception:
        return None


@router.get("/{field_id}/polygon")
def polygon_editor(request: Request, user: CurrentUser, field_id: int):
    with connect() as conn:
        row = conn.execute(
            "SELECT id, field_code, name, area_ha, coordinates_json FROM fields "
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
            "computed_area_ha": _geodesic_area_ha(existing),
            "map_data": {
                "center": SAPPORO,
                "zoom": 10,
                "geojson": existing,
            },
        },
    )


@router.get("/template.csv")
def download_template():
    """v1 互換 + fixed_crop 拡張の CSV テンプレートを返す。"""
    header = "ほ場ID,地区,ほ場名,area,beet_forbidden,固定作物,R5,R6,R7,R8\n"
    sample = "F001,北地区,北1号,280,0,,春小麦,大豆,秋小麦,てんさい\n"
    body = (header + sample).encode("utf-8-sig")
    return StreamingResponse(
        io.BytesIO(body),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="fields_template.csv"'},
    )


@router.post("/import_kml")
async def import_kml(
    request: Request,
    user: CurrentUser,
    file: UploadFile = File(...),
):
    """KML / KMZ をアップロードして、ほ場ポリゴン (+面積) を upsert。
    各 Placemark の name を field_code として扱う。同名は更新、新規は追加。"""
    from rotation_planner.field.kml_parser import parse_kml_or_kmz_bytes

    raw = await file.read()
    try:
        items = parse_kml_or_kmz_bytes(raw, file.filename or "uploaded.kml")
    except Exception as e:
        raise HTTPException(400, f"KML/KMZ パース失敗: {e}")

    if not items:
        return templates.TemplateResponse(
            request,
            "fields/_import_result.html",
            {"summary": "Placemark が見つかりませんでした", "errors": []},
        )

    added = 0
    updated = 0
    errors: list[str] = []
    with connect() as conn:
        for i, item in enumerate(items, start=1):
            name = (item.get("name") or "").strip() or f"placemark_{i}"
            coords = item.get("coordinates")
            if not coords or len(coords) < 3:
                errors.append(f"{name}: 座標が不正")
                continue
            # ライブラリの KML パーサは [lat, lng] を返すので、
            # GeoJSON 標準の [lng, lat] にスワップ
            ring = [[p[1], p[0]] for p in coords]
            # KML の座標は閉じてない場合もある → 閉じる
            if ring[0] != ring[-1]:
                ring.append(ring[0])
            feature = {
                "type": "Feature",
                "properties": {"source": "kml"},
                "geometry": {"type": "Polygon", "coordinates": [ring]},
            }
            coords_json = json.dumps(feature, ensure_ascii=False)
            area_ha = float(item.get("area_ha") or 0.0)

            existing = conn.execute(
                "SELECT id FROM fields WHERE user_id = ? AND field_code = ?",
                (user["id"], name),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE fields SET coordinates_json = ?, area_ha = ?, "
                    "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (coords_json, area_ha, existing["id"]),
                )
                updated += 1
            else:
                conn.execute(
                    "INSERT INTO fields (user_id, field_code, name, area_ha, coordinates_json) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (user["id"], name, name, area_ha, coords_json),
                )
                added += 1

    summary = f"KML 取込完了: 追加 {added} / 更新 {updated}"
    if errors:
        summary += f" / エラー {len(errors)} 件"
    return templates.TemplateResponse(
        request,
        "fields/_import_result.html",
        {"summary": summary, "errors": errors[:20]},
    )


@router.get("/polygons.kml")
def export_polygons_kml(user: CurrentUser):
    """ユーザーのほ場ポリゴンを KML として返す。"""
    from rotation_planner.field.kml_parser import generate_kml_content

    with connect() as conn:
        rows = conn.execute(
            "SELECT field_code, name, district, area_ha, coordinates_json "
            "FROM fields WHERE user_id = ? AND coordinates_json IS NOT NULL "
            "ORDER BY field_code",
            (user["id"],),
        ).fetchall()
    items: list[dict] = []
    for r in rows:
        try:
            feat = json.loads(r["coordinates_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        geom = feat.get("geometry") if feat.get("type") == "Feature" else feat
        if not geom or geom.get("type") != "Polygon":
            continue
        coords = geom.get("coordinates", [[]])[0]
        # GeoJSON [lng, lat] → ライブラリの generate_kml_content が期待する [lat, lng]
        coords_lat_lng = [[c[1], c[0]] for c in coords]
        items.append({
            "name": r["field_code"],
            "description": f"{r['name'] or ''} / {r['district'] or ''} / {r['area_ha']:.2f}ha",
            "coordinates": coords_lat_lng,
        })
    kml = generate_kml_content(items, name="rotation-planner ほ場")
    return Response(
        kml.encode("utf-8"),
        media_type="application/vnd.google-earth.kml+xml",
        headers={"Content-Disposition": 'attachment; filename="fields.kml"'},
    )


@router.get("/polygons.kmz")
def export_polygons_kmz(user: CurrentUser):
    """KMZ (zip された KML) を返す。"""
    import tempfile
    from rotation_planner.field.kml_parser import export_fields_to_kmz

    with connect() as conn:
        rows = conn.execute(
            "SELECT field_code, name, district, area_ha, coordinates_json "
            "FROM fields WHERE user_id = ? AND coordinates_json IS NOT NULL",
            (user["id"],),
        ).fetchall()
    items = []
    for r in rows:
        try:
            feat = json.loads(r["coordinates_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        geom = feat.get("geometry") if feat.get("type") == "Feature" else feat
        if not geom or geom.get("type") != "Polygon":
            continue
        coords = geom.get("coordinates", [[]])[0]
        # GeoJSON [lng, lat] → ライブラリの export が期待する [lat, lng]
        coords_lat_lng = [[c[1], c[0]] for c in coords]
        items.append({
            "name": r["field_code"],
            "description": f"{r['name'] or ''} / {r['district'] or ''} / {r['area_ha']:.2f}ha",
            "coordinates": coords_lat_lng,
        })
    with tempfile.NamedTemporaryFile(suffix=".kmz", delete=False) as tmp:
        kmz_path = tmp.name
    try:
        export_fields_to_kmz(items, kmz_path, name="rotation-planner ほ場")
        with open(kmz_path, "rb") as f:
            body = f.read()
    finally:
        os.unlink(kmz_path)
    return Response(
        body,
        media_type="application/vnd.google-earth.kmz",
        headers={"Content-Disposition": 'attachment; filename="fields.kmz"'},
    )


@router.get("/polygons.geojson")
def export_polygons_geojson(user: CurrentUser):
    """ユーザーのほ場ポリゴンを GeoJSON FeatureCollection として返す。"""
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, field_code, name, district, area_ha, coordinates_json "
            "FROM fields WHERE user_id = ? AND coordinates_json IS NOT NULL "
            "ORDER BY field_code",
            (user["id"],),
        ).fetchall()
    features = []
    for r in rows:
        try:
            feat = json.loads(r["coordinates_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        geom = feat.get("geometry") if feat.get("type") == "Feature" else feat
        if not geom or geom.get("type") != "Polygon":
            continue
        features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": {
                "id": r["id"],
                "field_code": r["field_code"],
                "name": r["name"] or "",
                "district": r["district"] or "",
                "area_ha": r["area_ha"],
            },
        })
    body = json.dumps(
        {"type": "FeatureCollection", "features": features},
        ensure_ascii=False,
        indent=2,
    )
    return Response(
        body.encode("utf-8"),
        media_type="application/geo+json",
        headers={"Content-Disposition": 'attachment; filename="fields.geojson"'},
    )


@router.get("/map")
def fields_map(request: Request, user: CurrentUser):
    return templates.TemplateResponse(
        request, "fields/map.html", {"user": user}
    )


@router.get("/export.csv")
def export_fields_csv(
    user: CurrentUser,
    district: str | None = None,
    polygon: str | None = None,
):
    """ほ場 (+ 履歴) を CSV エクスポート。インポート CSV と互換。
    一覧と同じ district/polygon フィルタが効く。"""
    where_sql, params = _build_field_filter(district, polygon)
    with connect() as conn:
        fields = conn.execute(
            f"SELECT id, field_code, district, name, area_ha, beet_forbidden, fixed_crop, notes "
            f"FROM fields WHERE {where_sql} ORDER BY field_code",
            ([user["id"]] + params),
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
    w.writerow(["ほ場ID", "地区", "ほ場名", "area", "beet_forbidden", "固定作物", "備考"] + years)
    for f in fields:
        w.writerow([
            f["field_code"], f["district"] or "", f["name"] or "",
            f"{f['area_ha'] * 100:.1f}",  # ha → a
            "1" if f["beet_forbidden"] else "0",
            f["fixed_crop"] or "",
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
        "fixed_crop": None,
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
        elif _match_alias(hs, _FIXED_CROP_ALIASES):
            mapping["fixed_crop"] = i
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
                fixed_crop = None
                if cols["fixed_crop"] is not None and cols["fixed_crop"] < len(row):
                    fixed_crop = (row[cols["fixed_crop"]].strip() or None)
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
                    "fixed_crop=COALESCE(?, fixed_crop), notes=COALESCE(?, notes), "
                    "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (district or None, name or None, area_ha, beet,
                     fixed_crop, notes or None, existing["id"]),
                )
                field_db_id = existing["id"]
                updated += 1
            else:
                cur = conn.execute(
                    "INSERT INTO fields (user_id, field_code, district, name, area_ha, "
                    "beet_forbidden, fixed_crop, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (user["id"], code, district or None, name or None, area_ha,
                     beet, fixed_crop, notes or None),
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


@router.post("/{field_id}/polygon/sync_area")
def sync_area_from_polygon(user: CurrentUser, field_id: int):
    """coordinates_json の測地線面積を area_ha に書き込む。"""
    with connect() as conn:
        row = conn.execute(
            "SELECT coordinates_json FROM fields WHERE id = ? AND user_id = ?",
            (field_id, user["id"]),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "ほ場が見つかりません")
        try:
            feat = json.loads(row["coordinates_json"]) if row["coordinates_json"] else None
        except json.JSONDecodeError:
            feat = None
        area = _geodesic_area_ha(feat)
        if area is None:
            raise HTTPException(400, "ポリゴンが登録されていないか、面積を計算できません")
        conn.execute(
            "UPDATE fields SET area_ha = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (area, field_id),
        )
    return RedirectResponse(f"/fields/{field_id}/polygon", status_code=303)


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
