"""
rotation_planner.common.ui_utils - 共通UIユーティリティ

全UIモジュールで使用する共通コンポーネント・関数。
"""
import html as _html


def format_alert(message: str, alert_type: str = "info") -> str:
    """
    アラートバナー用のHTMLを生成

    Args:
        message: 表示するメッセージ
        alert_type: アラートタイプ ("success", "error", "warning", "info")

    Returns:
        HTML文字列
    """
    colors = {
        "success": ("#d4edda", "#155724", "#c3e6cb"),  # 緑
        "error": ("#f8d7da", "#721c24", "#f5c6cb"),    # 赤
        "warning": ("#fff3cd", "#856404", "#ffeeba"),  # 黄
        "info": ("#d1ecf1", "#0c5460", "#bee5eb"),     # 青
    }
    bg, text, border = colors.get(alert_type, colors["info"])

    return f"""
    <div style="
        background: {bg};
        color: {text};
        border: 1px solid {border};
        padding: 12px 20px;
        border-radius: 6px;
        font-size: 1.1em;
        font-weight: 500;
        margin: 10px 0;
    ">{_html.escape(message)}</div>
    """


def format_success(message: str) -> str:
    """成功メッセージ（緑）"""
    return format_alert(message, "success")


def format_error(message: str) -> str:
    """エラーメッセージ（赤）"""
    return format_alert(message, "error")


def format_warning(message: str) -> str:
    """警告メッセージ（黄）"""
    return format_alert(message, "warning")


def format_info(message: str) -> str:
    """情報メッセージ（青）"""
    return format_alert(message, "info")


__all__ = [
    "format_alert",
    "format_success",
    "format_error",
    "format_warning",
    "format_info",
]
