"""PDF 出力サービス — reportlab で輪作計画と防除記録の PDF を生成。

日本語フォントはシステムにある Noto Sans CJK を優先、なければフォールバック。
"""
import io
import os
from datetime import datetime
from typing import Optional


_FONT_PATHS = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-VF.otf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
    "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf",
    # macOS フォールバック
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
]

_registered = False


def _ensure_font() -> str:
    """日本語フォントを登録し、フォント名を返す。"""
    global _registered
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    if _registered:
        return "RPv2JP"

    for path in _FONT_PATHS:
        if not os.path.exists(path):
            continue
        try:
            pdfmetrics.registerFont(TTFont("RPv2JP", path))
            _registered = True
            return "RPv2JP"
        except Exception:
            continue
    return "Helvetica"  # フォールバック (日本語は化ける)


def generate_plan_pdf(plan: dict, result: dict) -> bytes:
    """輪作計画 PDF を生成して bytes を返す。"""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate,
        Paragraph,
        Spacer,
        Table,
        TableStyle,
    )

    font = _ensure_font()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
    )

    title_style = ParagraphStyle(
        name="title", fontName=font, fontSize=16, spaceAfter=6,
    )
    meta_style = ParagraphStyle(
        name="meta", fontName=font, fontSize=10, textColor=colors.grey, spaceAfter=10,
    )
    h2 = ParagraphStyle(name="h2", fontName=font, fontSize=12, spaceBefore=10, spaceAfter=4)

    story = []
    story.append(Paragraph(plan["name"], title_style))
    story.append(Paragraph(
        f"対象年度: {plan['start_year']} 〜 {plan['end_year']} | "
        f"生成日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        meta_style,
    ))

    if not result.get("ok"):
        story.append(Paragraph(f"エラー: {result.get('message', '')}", meta_style))
    else:
        story.append(Paragraph(result["message"], meta_style))

        # ほ場 × 年表
        story.append(Paragraph("ほ場 × 年別 計画", h2))
        years = result["past_years"] + result["future_years"]
        header = ["圃場"] + years
        rows = [header]
        for code in result["field_codes"]:
            row = [code]
            for y in years:
                row.append(result["grid"].get((code, y), ""))
            rows.append(row)
        col_widths = [25 * mm] + [18 * mm] * len(years)
        table = Table(rows, colWidths=col_widths, repeatRows=1)
        past_n = len(result["past_years"])
        style = TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), font),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef")),
            ("BACKGROUND", (1, 1), (past_n, -1), colors.HexColor("#f2f2f2")),
            ("TEXTCOLOR", (1, 1), (past_n, -1), colors.grey),
            ("BACKGROUND", (past_n + 1, 1), (-1, -1), colors.HexColor("#fffceb")),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ])
        table.setStyle(style)
        story.append(table)

        # サマリ表
        if result.get("crops_in_result"):
            story.append(Spacer(1, 10))
            story.append(Paragraph("年別 × 作物別 合計面積 (ha)", h2))
            crops = result["crops_in_result"]
            srows = [["年"] + crops]
            for y in years:
                row = [y]
                for crop in crops:
                    v = result["summary"][y].get(crop, 0)
                    row.append(f"{v:.2f}" if v else "")
                srows.append(row)
            stable = Table(srows, repeatRows=1)
            stable.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (-1, -1), font),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ]))
            story.append(stable)

    doc.build(story)
    return buf.getvalue()


def generate_pesticide_records_pdf(records: list[dict], title: str = "防除記録") -> bytes:
    """防除記録 PDF を生成して bytes を返す。"""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate,
        Paragraph,
        Table,
        TableStyle,
    )

    font = _ensure_font()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
    )
    title_style = ParagraphStyle(name="title", fontName=font, fontSize=16, spaceAfter=6)
    meta_style = ParagraphStyle(name="meta", fontName=font, fontSize=10, textColor=colors.grey, spaceAfter=10)

    story = [
        Paragraph(title, title_style),
        Paragraph(f"件数: {len(records)} | 出力日: {datetime.now().strftime('%Y-%m-%d')}", meta_style),
    ]

    header = ["散布日", "圃場", "農薬名", "希釈倍率", "量", "単位", "備考"]
    rows = [header]
    for r in records:
        rows.append([
            str(r["spray_date"]),
            f"{r['field_code']} {r['field_name'] or ''}".strip(),
            r["pesticide_name"],
            r["dilution_rate"] or "",
            f"{r['spray_amount']:.2f}" if r["spray_amount"] is not None else "",
            r["spray_unit"] or "",
            r["notes"] or "",
        ])
    col_widths = [22*mm, 35*mm, 50*mm, 22*mm, 15*mm, 20*mm, 60*mm]
    table = Table(rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef")),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(table)
    doc.build(story)
    return buf.getvalue()
