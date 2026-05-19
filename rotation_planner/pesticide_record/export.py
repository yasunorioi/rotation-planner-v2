"""
防除記録エクスポートモジュール

防除記録をCSV/PDF形式でエクスポート。
JA提出用の帳票形式に対応。

Usage:
    from rotation_planner.pesticide_record.export import (
        export_records_csv,
        export_records_pdf,
    )

    # CSV出力
    csv_path = export_records_csv(records, "/tmp/防除記録.csv")

    # PDF出力
    pdf_path = export_records_pdf(records, "/tmp/防除記録.pdf", "田中太郎")
"""

import os
import csv
from datetime import datetime
from typing import List, Dict, Optional

# reportlab imports
try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import (
        SimpleDocTemplate,
        Table,
        TableStyle,
        Paragraph,
        Spacer,
    )
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False
    class _DummyColors:
        grey = None
        whitesmoke = None
        white = None
        @staticmethod
        def HexColor(v): return None
    colors = _DummyColors()
    Table = None
    TableStyle = None


# =============================================================================
# 日本語フォント設定（pesticide/pdf_export.pyと共通化）
# =============================================================================

_font_registered = False
_font_name = "Helvetica"


def _register_japanese_font() -> str:
    """日本語フォントを登録して使用可能なフォント名を返す"""
    global _font_registered, _font_name

    if _font_registered:
        return _font_name

    if not REPORTLAB_AVAILABLE:
        return _font_name

    # reportlab内蔵のCIDフォント（HeiseiKakuGo-W5）を使用
    try:
        pdfmetrics.registerFont(UnicodeCIDFont('HeiseiKakuGo-W5'))
        _font_name = "HeiseiKakuGo-W5"
        _font_registered = True
    except Exception:
        pass

    return _font_name


# =============================================================================
# CSV エクスポート
# =============================================================================

def export_records_csv(records: List[Dict], output_path: str) -> str:
    """
    防除記録をCSV出力

    Args:
        records: 防除記録リスト
        output_path: 出力ファイルパス

    Returns:
        出力ファイルパス

    CSV形式:
        散布日, ほ場名, 地区, 面積(ha), 作物, 農薬名, 希釈倍率, 散布量, 備考
    """
    if not records:
        # 空でもヘッダーだけ出力
        records = []

    headers = [
        "散布日",
        "ほ場名",
        "地区",
        "面積(ha)",
        "作物",
        "農薬名",
        "希釈倍率",
        "散布量",
        "備考"
    ]

    with open(output_path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(headers)

        for rec in records:
            row = [
                rec.get('spray_date', ''),
                rec.get('field_name', rec.get('field_code', '')),
                rec.get('district', ''),
                rec.get('area_ha', ''),
                rec.get('crop', ''),
                rec.get('pesticide_name', ''),
                rec.get('dilution_rate', ''),
                rec.get('spray_amount', ''),
                rec.get('notes', ''),
            ]
            writer.writerow(row)

    return output_path


# =============================================================================
# PDF エクスポート
# =============================================================================

def export_records_pdf(
    records: List[Dict],
    output_path: str,
    user_name: str,
    start_date: str = None,
    end_date: str = None
) -> str:
    """
    防除記録をPDF出力（JA提出用）

    Args:
        records: 防除記録リスト
        output_path: 出力ファイルパス
        user_name: 農家名
        start_date: 対象期間開始日（YYYY-MM-DD形式）
        end_date: 対象期間終了日（YYYY-MM-DD形式）

    Returns:
        出力ファイルパス
    """
    if not REPORTLAB_AVAILABLE:
        raise RuntimeError("reportlab がインストールされていません")

    # 日本語フォント登録
    font_name = _register_japanese_font()

    # ドキュメント作成
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=15*mm,
        leftMargin=15*mm,
        topMargin=15*mm,
        bottomMargin=15*mm
    )

    # スタイル設定
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        'JapaneseTitle',
        parent=styles['Title'],
        fontName=font_name,
        fontSize=18,
        leading=22,
        alignment=1,  # CENTER
        spaceAfter=8*mm
    )

    header_style = ParagraphStyle(
        'JapaneseHeader',
        parent=styles['Normal'],
        fontName=font_name,
        fontSize=11,
        leading=14,
        spaceAfter=3*mm
    )

    footer_style = ParagraphStyle(
        'JapaneseFooter',
        parent=styles['Normal'],
        fontName=font_name,
        fontSize=10,
        leading=12,
        spaceBefore=5*mm
    )

    # コンテンツ構築
    elements = []

    # タイトル
    elements.append(Paragraph("防除履歴報告書", title_style))

    # ヘッダー情報
    output_date = datetime.now().strftime("%Y年%m月%d日")

    # 期間表示
    if start_date and end_date:
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            period_str = f"{start_dt.strftime('%Y年%m月')}〜{end_dt.strftime('%Y年%m月')}"
        except ValueError:
            period_str = f"{start_date}〜{end_date}"
    elif records:
        # レコードから期間を推定
        dates = [r.get('spray_date', '') for r in records if r.get('spray_date')]
        if dates:
            period_str = f"{min(dates)}〜{max(dates)}"
        else:
            period_str = "（期間不明）"
    else:
        period_str = "（期間不明）"

    elements.append(Paragraph(f"農家名: {user_name}", header_style))
    elements.append(Paragraph(f"対象期間: {period_str}", header_style))
    elements.append(Paragraph(f"出力日: {output_date}", header_style))

    elements.append(Spacer(1, 5*mm))

    # テーブルデータ作成
    if records:
        table_data = [["日付", "ほ場名", "作物", "農薬名", "倍率", "散布量", "備考"]]

        for rec in records:
            spray_date = rec.get('spray_date', '')
            # 日付を短縮形式に
            if spray_date and len(spray_date) >= 10:
                try:
                    dt = datetime.strptime(spray_date[:10], "%Y-%m-%d")
                    spray_date_short = dt.strftime("%m/%d")
                except ValueError:
                    spray_date_short = spray_date[:5]
            else:
                spray_date_short = spray_date

            row = [
                spray_date_short,
                str(rec.get('field_name', rec.get('field_code', '')))[:10],  # 長すぎる場合は切り詰め
                str(rec.get('crop', ''))[:6],
                str(rec.get('pesticide_name', ''))[:12],
                str(rec.get('dilution_rate', '')),
                str(rec.get('spray_amount', '')),
                str(rec.get('notes', ''))[:10],
            ]
            table_data.append(row)

        # テーブル作成
        table = _create_table(table_data, font_name)
        elements.append(table)
    else:
        elements.append(Paragraph("（記録がありません）", header_style))

    elements.append(Spacer(1, 5*mm))

    # フッター（合計件数）
    elements.append(Paragraph(f"合計: {len(records)}件", footer_style))

    # PDF生成
    try:
        doc.build(elements)
        return output_path
    except Exception as e:
        print(f"PDF生成エラー: {e}")
        return ""


def _create_table(data: List[List[str]], font_name: str) -> Table:
    """テーブルを作成"""
    # 列幅設定（A4に収まるように）
    col_widths = [18*mm, 28*mm, 18*mm, 35*mm, 20*mm, 22*mm, 25*mm]

    table = Table(data, colWidths=col_widths)

    style = TableStyle([
        # ヘッダー行
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#2E7D32")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, 0), font_name),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
        ('TOPPADDING', (0, 0), (-1, 0), 6),

        # データ行
        ('FONTNAME', (0, 1), (-1, -1), font_name),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('ALIGN', (0, 1), (-1, -1), 'LEFT'),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
        ('TOPPADDING', (0, 1), (-1, -1), 4),

        # 罫線
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),

        # 交互の背景色
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#E8F5E9")]),
    ])

    table.setStyle(style)
    return table


# =============================================================================
# ユーティリティ
# =============================================================================

def check_export_support() -> dict:
    """エクスポート機能のサポート状況を確認"""
    font_name = _register_japanese_font() if REPORTLAB_AVAILABLE else None

    return {
        "csv_available": True,
        "pdf_available": REPORTLAB_AVAILABLE,
        "japanese_font_available": font_name not in (None, "Helvetica"),
        "font_name": font_name,
    }


# =============================================================================
# テスト用
# =============================================================================

if __name__ == "__main__":
    # サポート状況確認
    support = check_export_support()
    print(f"Export Support: {support}")

    # テストデータ
    test_records = [
        {
            "spray_date": "2026-02-01",
            "field_name": "本田1号",
            "district": "東地区",
            "area_ha": 2.5,
            "crop": "大豆",
            "pesticide_name": "トップジンM水和剤",
            "dilution_rate": "1000倍",
            "spray_amount": "50L",
            "notes": "晴天時散布",
        },
        {
            "spray_date": "2026-02-05",
            "field_name": "本田2号",
            "district": "西地区",
            "area_ha": 3.0,
            "crop": "てんさい",
            "pesticide_name": "ダコニール1000",
            "dilution_rate": "500倍",
            "spray_amount": "80L",
            "notes": "",
        },
    ]

    # CSV出力テスト
    csv_path = export_records_csv(test_records, "/tmp/test_pesticide_records.csv")
    print(f"CSV exported: {csv_path}")

    # PDF出力テスト
    if REPORTLAB_AVAILABLE:
        pdf_path = export_records_pdf(
            test_records,
            "/tmp/test_pesticide_records.pdf",
            "田中太郎",
            "2026-01-01",
            "2026-12-31"
        )
        print(f"PDF exported: {pdf_path}")

        import os
        if os.path.exists(pdf_path):
            print(f"PDF size: {os.path.getsize(pdf_path)} bytes")
