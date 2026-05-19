"""集計画面 — 年×作物の合計面積を作付履歴から計算。

CSV / PDF 出力に対応。年範囲はクエリパラメータで絞り込み可。
"""
import csv
import io
from pathlib import Path

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import StreamingResponse
from fastapi.templating import Jinja2Templates

from app.auth import CurrentUser
from app.db import connect
from rotation_planner.common.year_utils import generate_year_choices

router = APIRouter(prefix="/aggregation")
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)


def _year_range(from_y: str | None, to_y: str | None) -> list[str]:
    if from_y and to_y and from_y.startswith("R") and to_y.startswith("R"):
        try:
            s, e = int(from_y[1:]), int(to_y[1:])
            if s <= e:
                return [f"R{n}" for n in range(s, e + 1)]
        except ValueError:
            pass
    return generate_year_choices(start_offset=-3, end_offset=2)


def _compute_aggregation(user_id: int, years: list[str]) -> dict:
    """年×作物 → 合計面積 + 列挙された作物リストを返す。"""
    with connect() as conn:
        rows = conn.execute(
            "SELECT h.year, h.crop, f.area_ha FROM crop_history h "
            "JOIN fields f ON h.field_id = f.id "
            "WHERE f.user_id = ?",
            (user_id,),
        ).fetchall()
    summary: dict[str, dict[str, float]] = {y: {} for y in years}
    counts: dict[str, dict[str, int]] = {y: {} for y in years}
    crops: list[str] = []
    seen: set[str] = set()
    year_set = set(years)
    for r in rows:
        y = r["year"]
        crop = r["crop"]
        if y not in year_set or not crop:
            continue
        if crop not in seen:
            seen.add(crop)
            crops.append(crop)
        summary[y][crop] = summary[y].get(crop, 0.0) + float(r["area_ha"] or 0.0)
        counts[y][crop] = counts[y].get(crop, 0) + 1
    crops.sort()
    return {
        "years": years,
        "crops": crops,
        "summary": summary,
        "counts": counts,
        "year_total": {y: sum(summary[y].values()) for y in years},
    }


@router.get("/")
def aggregation_page(
    request: Request,
    user: CurrentUser,
    from_y: str | None = Query(None, alias="from"),
    to_y: str | None = Query(None, alias="to"),
):
    years = _year_range(from_y, to_y)
    data = _compute_aggregation(user["id"], years)
    return templates.TemplateResponse(
        request,
        "aggregation/index.html",
        {
            "user": user,
            "data": data,
            "from_y": years[0],
            "to_y": years[-1],
        },
    )


@router.get("/export.csv")
def aggregation_csv(
    user: CurrentUser,
    from_y: str | None = Query(None, alias="from"),
    to_y: str | None = Query(None, alias="to"),
):
    years = _year_range(from_y, to_y)
    data = _compute_aggregation(user["id"], years)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["年"] + data["crops"] + ["合計"])
    for y in years:
        row = [y]
        for c in data["crops"]:
            v = data["summary"][y].get(c, 0.0)
            row.append(f"{v:.2f}" if v else "")
        row.append(f"{data['year_total'][y]:.2f}")
        w.writerow(row)
    return StreamingResponse(
        io.BytesIO(buf.getvalue().encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="aggregation_{years[0]}-{years[-1]}.csv"'},
    )


@router.get("/export.pdf")
def aggregation_pdf(
    user: CurrentUser,
    from_y: str | None = Query(None, alias="from"),
    to_y: str | None = Query(None, alias="to"),
):
    from app.pdf_service import generate_aggregation_pdf

    years = _year_range(from_y, to_y)
    data = _compute_aggregation(user["id"], years)
    pdf_bytes = generate_aggregation_pdf(data, title=f"作付集計 {years[0]}〜{years[-1]}")
    return Response(
        pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="aggregation_{years[0]}-{years[-1]}.pdf"'},
    )
