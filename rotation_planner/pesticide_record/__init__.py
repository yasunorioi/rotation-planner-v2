"""
rotation_planner.pesticide_record - 防除記録モジュール

写真アップロードによる農薬名自動認識、EXIF解析、防除履歴管理を提供。

サブモジュール:
    - image_analyzer: 画像解析（EXIF抽出、Vision API連携）
    - export: CSV/PDFエクスポート
    - ui: GradioUIコンポーネント

Usage:
    from rotation_planner.pesticide_record import (
        extract_exif,
        recognize_pesticide_name,
        analyze_image,
        export_records_csv,
        export_records_pdf,
        create_pesticide_record_ui,
    )

    # 画像を解析
    result = analyze_image("/path/to/image.jpg")
    print(result['spray_date'])      # 撮影日時からの散布日
    print(result['pesticide_name'])  # 認識した農薬名
    print(result['gps'])             # GPS座標（あれば）

    # CSV/PDFエクスポート
    export_records_csv(records, "/tmp/records.csv")
    export_records_pdf(records, "/tmp/records.pdf", "田中太郎")
"""

from rotation_planner.pesticide_record.image_analyzer import (
    extract_exif,
    recognize_pesticide_name,
    analyze_image,
)

from rotation_planner.pesticide_record.export import (
    export_records_csv,
    export_records_pdf,
    check_export_support,
)

# UI (Gradio UI は削除済み。React版へ移行)

__all__ = [
    # image_analyzer
    "extract_exif",
    "recognize_pesticide_name",
    "analyze_image",
    # export
    "export_records_csv",
    "export_records_pdf",
    "check_export_support",
    # ui (Gradio UI は削除済み)
]
