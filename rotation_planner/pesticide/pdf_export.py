"""
農薬発注リスト PDF出力モジュール

reportlab を使用して農薬発注リストをPDFで出力。
日本語フォント対応（Noto Sans CJK JP）。

Usage:
    from rotation_planner.pesticide.pdf_export import generate_pesticide_order_pdf

    pdf_path = generate_pesticide_order_pdf(
        summary_df, detail_df, "春作業用", "R6", "/tmp/output.pdf"
    )
"""

import os
from datetime import datetime
from typing import Optional
import pandas as pd

# reportlab imports
try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
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
    # ダミー定義（関数シグネチャのためにモジュールレベルで必要）
    class _DummyColors:
        grey = None
        whitesmoke = None
        white = None
        @staticmethod
        def HexColor(v): return None
    colors = _DummyColors()
    Table = None


# =============================================================================
# 日本語フォント設定
# =============================================================================

# システムフォントのパス候補（.ttfまたは.otfを優先、.ttcはサブフォントインデックス指定が必要）
FONT_PATHS = [
    # Linux - 単体フォントファイル（優先）
    "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf",
    "/usr/share/fonts/truetype/ipafont/ipag.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJKjp-Regular.otf",
    # Linux - TTC（コレクション）フォント
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 0),  # JP=0
    ("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", 0),
    # macOS
    "/Library/Fonts/NotoSansCJKjp-Regular.otf",
    ("/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc", 0),
    # Windows
    ("/c/Windows/Fonts/msgothic.ttc", 0),
    ("/c/Windows/Fonts/meiryo.ttc", 0),
    "C:/Windows/Fonts/msgothic.ttc",
    "C:/Windows/Fonts/meiryo.ttc",
]

_font_registered = False
_font_name = "Helvetica"  # フォールバック


def _register_japanese_font() -> str:
    """日本語フォントを登録して使用可能なフォント名を返す"""
    global _font_registered, _font_name

    if _font_registered:
        return _font_name

    if not REPORTLAB_AVAILABLE:
        return _font_name

    # 方法1: reportlab内蔵のCIDフォント（HeiseiKakuGo-W5）を試す
    try:
        pdfmetrics.registerFont(UnicodeCIDFont('HeiseiKakuGo-W5'))
        _font_name = "HeiseiKakuGo-W5"
        _font_registered = True
        return _font_name
    except Exception:
        pass

    # 方法2: システムフォントを試す
    for font_entry in FONT_PATHS:
        # タプルの場合は (path, subfontIndex) 形式
        if isinstance(font_entry, tuple):
            font_path, subfont_index = font_entry
        else:
            font_path = font_entry
            subfont_index = None

        if os.path.exists(font_path):
            try:
                if subfont_index is not None:
                    # TTC（コレクション）フォントの場合
                    pdfmetrics.registerFont(TTFont("JapaneseFont", font_path, subfontIndex=subfont_index))
                else:
                    # 通常のTTF/OTFフォント
                    pdfmetrics.registerFont(TTFont("JapaneseFont", font_path))
                _font_name = "JapaneseFont"
                _font_registered = True
                return _font_name
            except Exception:
                continue

    # フォントが見つからない場合はHelveticaを使用（日本語は文字化け）
    _font_registered = True
    return _font_name


# =============================================================================
# PDF生成
# =============================================================================

def generate_pesticide_order_pdf(
    summary_df: pd.DataFrame,
    detail_df: pd.DataFrame,
    order_name: str,
    target_year: str,
    output_path: str
) -> str:
    """
    農薬発注リストをPDFで出力

    Args:
        summary_df: 農薬別必要量サマリー DataFrame
        detail_df: 月別詳細 DataFrame
        order_name: 発注名
        target_year: 対象年（例: "R6"）
        output_path: 出力ファイルパス

    Returns:
        出力ファイルパス（成功時）、エラー時は空文字列

    Raises:
        RuntimeError: reportlabが利用できない場合
    """
    if not REPORTLAB_AVAILABLE:
        raise RuntimeError("reportlab がインストールされていません。pip install reportlab を実行してください。")

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
        spaceAfter=10*mm
    )

    subtitle_style = ParagraphStyle(
        'JapaneseSubtitle',
        parent=styles['Normal'],
        fontName=font_name,
        fontSize=11,
        leading=14,
        spaceAfter=5*mm
    )

    section_style = ParagraphStyle(
        'JapaneseSection',
        parent=styles['Heading2'],
        fontName=font_name,
        fontSize=14,
        leading=18,
        spaceBefore=8*mm,
        spaceAfter=5*mm
    )

    # コンテンツ構築
    elements = []

    # タイトル
    elements.append(Paragraph("農薬発注リスト", title_style))

    # サブタイトル（発注名、対象年、出力日）
    output_date = datetime.now().strftime("%Y年%m月%d日")
    subtitle_text = f"発注名: {order_name} | 対象年: {target_year} | 出力日: {output_date}"
    elements.append(Paragraph(subtitle_text, subtitle_style))

    elements.append(Spacer(1, 5*mm))

    # セクション1: 農薬別必要量サマリー
    elements.append(Paragraph("農薬別必要量サマリー", section_style))

    if summary_df is not None and not summary_df.empty:
        summary_table = _create_table(summary_df, font_name, header_color=colors.HexColor("#4472C4"))
        elements.append(summary_table)
    else:
        elements.append(Paragraph("データがありません", subtitle_style))

    elements.append(Spacer(1, 10*mm))

    # セクション2: 月別詳細
    elements.append(Paragraph("月別詳細", section_style))

    if detail_df is not None and not detail_df.empty:
        detail_table = _create_table(detail_df, font_name, header_color=colors.HexColor("#70AD47"))
        elements.append(detail_table)
    else:
        elements.append(Paragraph("データがありません", subtitle_style))

    # PDF生成
    try:
        doc.build(elements)
        return output_path
    except Exception as e:
        print(f"PDF生成エラー: {e}")
        return ""


def _create_table(df: pd.DataFrame, font_name: str, header_color=None) -> Table:
    """DataFrameからreportlabのTableを作成"""
    if header_color is None:
        header_color = colors.grey

    # ヘッダー行
    headers = list(df.columns)

    # データ行
    data = [headers]
    for _, row in df.iterrows():
        data.append([str(v) if pd.notna(v) else "" for v in row])

    # 列幅を計算（A4幅に収まるように）
    available_width = A4[0] - 30*mm  # 左右マージン分を引く
    col_count = len(headers)
    col_width = available_width / col_count

    # テーブル作成
    table = Table(data, colWidths=[col_width] * col_count)

    # スタイル設定
    style = TableStyle([
        # ヘッダー
        ('BACKGROUND', (0, 0), (-1, 0), header_color),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, 0), font_name),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 0), (-1, 0), 8),

        # データ行
        ('FONTNAME', (0, 1), (-1, -1), font_name),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('ALIGN', (0, 1), (-1, -1), 'LEFT'),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 5),
        ('TOPPADDING', (0, 1), (-1, -1), 5),

        # 罫線
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),

        # 交互の背景色
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F2F2")]),
    ])

    table.setStyle(style)
    return table


# =============================================================================
# ユーティリティ
# =============================================================================

def check_pdf_support() -> dict:
    """PDF出力機能のサポート状況を確認"""
    font_name = _register_japanese_font() if REPORTLAB_AVAILABLE else None

    return {
        "reportlab_available": REPORTLAB_AVAILABLE,
        "japanese_font_available": font_name not in (None, "Helvetica"),
        "font_name": font_name,
    }


# =============================================================================
# テスト用
# =============================================================================

if __name__ == "__main__":
    # サポート状況確認
    support = check_pdf_support()
    print(f"PDF Support: {support}")

    # テストデータ
    summary_df = pd.DataFrame({
        "農薬名": ["トップジンM水和剤", "スミチオン乳剤"],
        "必要量": ["5.00", "3.50"],
        "単位": ["L", "L"],
        "対象作物": ["てんさい", "大豆"],
        "対象病害虫": ["苗立枯病", "アブラムシ"],
    })

    detail_df = pd.DataFrame({
        "月": [4, 5],
        "作物": ["てんさい", "大豆"],
        "対象": ["苗立枯病", "アブラムシ"],
        "農薬名": ["トップジンM水和剤", "スミチオン乳剤"],
        "必要量": ["5.00L", "3.50L"],
        "面積(ha)": [10.0, 8.5],
    })

    # PDF生成
    try:
        output = generate_pesticide_order_pdf(
            summary_df, detail_df, "テスト発注", "R6", "/tmp/test_pesticide_order.pdf"
        )
        print(f"PDF generated: {output}")
    except Exception as e:
        print(f"Error: {e}")
