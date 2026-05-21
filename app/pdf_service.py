"""PDF 出力サービス — reportlab で輪作計画と防除記録の PDF を生成。

日本語フォントはシステムにある Noto Sans CJK を優先、なければフォールバック。
ロゴは <project-root>/data/logo.{png,jpg,gif} があれば PDF ヘッダに表示。
"""
import io
import os
from datetime import datetime
from pathlib import Path
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

_LOGO_CANDIDATES = ("logo.png", "logo.jpg", "logo.jpeg", "logo.gif")
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

_registered = False


def _find_logo() -> Path | None:
    for name in _LOGO_CANDIDATES:
        p = _DATA_DIR / name
        if p.exists():
            return p
    return None


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


def _header_block(title: str, subtitle: str, font: str):
    """ロゴ (あれば) と タイトル/サブタイトル を横並びにした Flowable を返す。"""
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, Paragraph, Table, TableStyle

    title_style = ParagraphStyle(name="title", fontName=font, fontSize=16, spaceAfter=2)
    sub_style = ParagraphStyle(name="sub", fontName=font, fontSize=10, textColor=colors.grey)

    text_cell = [Paragraph(title, title_style), Paragraph(subtitle, sub_style)]
    logo = _find_logo()
    if logo is not None:
        try:
            img = Image(str(logo), width=22 * mm, height=22 * mm, kind="proportional")
            row = [[img, text_cell]]
            col_widths = [25 * mm, None]
        except Exception:
            row = [[text_cell]]
            col_widths = [None]
    else:
        row = [[text_cell]]
        col_widths = [None]
    tbl = Table(row, colWidths=col_widths)
    tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return tbl


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

    meta_style = ParagraphStyle(
        name="meta", fontName=font, fontSize=10, textColor=colors.grey, spaceAfter=10,
    )
    h2 = ParagraphStyle(name="h2", fontName=font, fontSize=12, spaceBefore=10, spaceAfter=4)

    story = []
    story.append(_header_block(
        plan["name"],
        f"対象年度: {plan['start_year']} 〜 {plan['end_year']} | "
        f"生成日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        font,
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


def generate_compare_pdf(plan: dict, snapshot: dict, actual: dict, title: str | None = None) -> bytes:
    """計画スナップショット vs 実績の比較 PDF。
    actual は dict[(field_code, year)] -> crop。snapshot["grid"] は "code|year" 文字列キー。"""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

    font = _ensure_font()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
    )
    years = snapshot["past_years"] + snapshot["future_years"]
    header = ["圃場"] + years
    rows = [header]
    diff_count = 0
    match_count = 0
    for code in snapshot["field_codes"]:
        row = [code]
        for y in years:
            planned = snapshot["grid"].get(f"{code}|{y}", "")
            act = actual.get((code, y), "")
            if planned and act:
                if planned == act:
                    row.append(act)
                    match_count += 1
                else:
                    row.append(f"{planned}→{act}")
                    diff_count += 1
            elif planned:
                row.append(f"({planned})")
            elif act:
                row.append(f"[{act}]")
            else:
                row.append("—")
        rows.append(row)

    col_widths = [25 * mm] + [22 * mm] * len(years)
    table = Table(rows, colWidths=col_widths, repeatRows=1)
    # セル個別色: 一致=緑, 差分=黄, 計画のみ=青, 実績のみ=灰
    style_cmds = [
        ("FONTNAME", (0, 0), (-1, -1), font),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef")),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
    ]
    for ri, code in enumerate(snapshot["field_codes"], start=1):
        for ci, y in enumerate(years, start=1):
            planned = snapshot["grid"].get(f"{code}|{y}", "")
            act = actual.get((code, y), "")
            if planned and act:
                if planned == act:
                    style_cmds.append(("BACKGROUND", (ci, ri), (ci, ri), colors.HexColor("#d8f3dc")))
                else:
                    style_cmds.append(("BACKGROUND", (ci, ri), (ci, ri), colors.HexColor("#fff3cd")))
            elif planned:
                style_cmds.append(("BACKGROUND", (ci, ri), (ci, ri), colors.HexColor("#e3f2fd")))
            elif act:
                style_cmds.append(("BACKGROUND", (ci, ri), (ci, ri), colors.HexColor("#f0f0f0")))
    table.setStyle(TableStyle(style_cmds))

    title_text = title or f"{plan['name']} — 計画 vs 実績"
    subtitle = (f"スナップショット: {snapshot.get('taken_at', '?')} | "
                f"一致 {match_count} / 差分 {diff_count} | "
                f"出力日: {datetime.now().strftime('%Y-%m-%d')}")
    story = [_header_block(title_text, subtitle, font), table]
    doc.build(story)
    return buf.getvalue()


def generate_aggregation_pdf(data: dict, title: str = "作付集計") -> bytes:
    """年×作物の集計表 PDF を生成。"""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

    font = _ensure_font()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
    )
    crops = data["crops"]
    years = data["years"]
    rows = [["年"] + crops + ["合計"]]
    for y in years:
        row = [y]
        for c in crops:
            v = data["summary"][y].get(c, 0)
            row.append(f"{v:.2f}" if v else "")
        row.append(f"{data['year_total'][y]:.2f}")
        rows.append(row)
    table = Table(rows, repeatRows=1)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef")),
        ("BACKGROUND", (-1, 0), (-1, -1), colors.HexColor("#d8f3dc")),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
    ]))
    story = [
        _header_block(title, f"出力日: {datetime.now().strftime('%Y-%m-%d')}", font),
        table,
    ]
    doc.build(story)
    return buf.getvalue()


def generate_pesticide_records_pdf(records: list[dict], title: str = "防除記録") -> bytes:
    """防除記録 PDF を生成して bytes を返す。"""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

    font = _ensure_font()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
    )

    story = [
        _header_block(
            title,
            f"件数: {len(records)} | 出力日: {datetime.now().strftime('%Y-%m-%d')}",
            font,
        ),
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
