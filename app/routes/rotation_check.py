"""作物科ベースの輪作チェック。

crop_master.family を使って、各ほ場の連作/間隔状況を診断する。
- 連作 (前年と同じ family): 警告
- 短期再作付 (N年以内): 注意
- 長期同一系: 観察 (情報のみ)
"""
from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.templating import Jinja2Templates

from app.auth import CurrentUser
from app.db import connect

router = APIRouter(prefix="/rotation-check")
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)


def _family_map() -> dict[str, str]:
    """crop_master の name → family のマップ。"""
    with connect() as conn:
        return {
            r["name"]: r["family"]
            for r in conn.execute(
                "SELECT name, family FROM crop_master WHERE family IS NOT NULL"
            )
        }


def _diagnose(user_id: int, gap_threshold: int) -> dict:
    """ほ場ごとに履歴を時系列で並べ、連作や短期再作付を検出。"""
    fam = _family_map()
    with connect() as conn:
        rows = conn.execute(
            "SELECT f.id AS field_id, f.field_code, f.name AS field_name, "
            "h.year, h.crop "
            "FROM fields f "
            "JOIN crop_history h ON h.field_id = f.id "
            "WHERE f.user_id = ? "
            "ORDER BY f.field_code, h.year",
            (user_id,),
        ).fetchall()

    # ほ場ごとに [(year, crop, family), ...] を整理
    by_field: dict[int, dict] = {}
    for r in rows:
        d = by_field.setdefault(r["field_id"], {
            "field_code": r["field_code"],
            "field_name": r["field_name"],
            "history": [],
        })
        # year は "R6" 形式 → 数値化
        y = r["year"]
        try:
            yn = int(y[1:]) if y.startswith("R") else int(y)
        except ValueError:
            continue
        d["history"].append({
            "year": y, "year_n": yn,
            "crop": r["crop"], "family": fam.get(r["crop"]),
        })

    consecutive: list[dict] = []  # 連作 (year_n が連続で family 同じ)
    short_repeat: list[dict] = []  # gap_threshold 年以内に同 family 再作付

    for field_id, d in by_field.items():
        hist = sorted(d["history"], key=lambda e: e["year_n"])
        for i, e in enumerate(hist):
            if e["family"] is None:
                continue
            # 連作チェック
            if i > 0 and hist[i - 1]["year_n"] + 1 == e["year_n"] and hist[i - 1]["family"] == e["family"]:
                consecutive.append({
                    "field_code": d["field_code"],
                    "field_name": d["field_name"],
                    "prev_year": hist[i - 1]["year"],
                    "prev_crop": hist[i - 1]["crop"],
                    "year": e["year"],
                    "crop": e["crop"],
                    "family": e["family"],
                })
            # 短期再作付チェック (連作は別計上なので gap >= 1 のみ)
            for j in range(i - 1, -1, -1):
                gap = e["year_n"] - hist[j]["year_n"]
                if gap == 0 or gap > gap_threshold:
                    break
                if gap >= 2 and hist[j]["family"] == e["family"]:
                    short_repeat.append({
                        "field_code": d["field_code"],
                        "field_name": d["field_name"],
                        "prev_year": hist[j]["year"],
                        "prev_crop": hist[j]["crop"],
                        "year": e["year"],
                        "crop": e["crop"],
                        "family": e["family"],
                        "gap": gap,
                    })
                    break  # 直近1件だけで十分

    # 科未分類の作物
    with connect() as conn:
        unclassified = [r["crop"] for r in conn.execute(
            "SELECT DISTINCT h.crop FROM crop_history h "
            "JOIN fields f ON h.field_id = f.id "
            "WHERE f.user_id = ? AND h.crop NOT IN ("
            "  SELECT name FROM crop_master WHERE family IS NOT NULL"
            ") AND h.crop IS NOT NULL AND h.crop != ''",
            (user_id,),
        ).fetchall()]

    return {
        "consecutive": consecutive,
        "short_repeat": short_repeat,
        "unclassified": unclassified,
        "gap_threshold": gap_threshold,
        "field_count": len(by_field),
    }


@router.get("/")
def rotation_check_page(
    request: Request,
    user: CurrentUser,
    gap: int = Query(4, ge=1, le=10),
):
    data = _diagnose(user["id"], gap)
    return templates.TemplateResponse(
        request, "rotation_check/index.html",
        {"user": user, "data": data},
    )
