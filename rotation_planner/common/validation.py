"""
入力バリデーションモジュール

ValidationResult を用いた宣言的バリデーション。
汎用関数 + エンティティ固有バリデーションを提供。
"""

from dataclasses import dataclass
from typing import Optional, List

from rotation_planner.common.exceptions import ValidationError


# ============================================================
# バリデーション結果クラス
# ============================================================

@dataclass
class FieldError:
    """フィールド単位のエラー"""
    field: str
    message: str


class ValidationResult:
    """バリデーション結果"""

    def __init__(self):
        self.errors: List[FieldError] = []

    def add_error(self, field: str, message: str):
        self.errors.append(FieldError(field=field, message=message))

    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def get_error_messages(self) -> List[str]:
        return [f"{e.field}: {e.message}" for e in self.errors]

    def get_first_error(self) -> Optional[str]:
        return self.errors[0].message if self.errors else None


# ============================================================
# 汎用バリデーション関数
# ============================================================

def validate_required(value, field_name: str, result: ValidationResult):
    """必須項目チェック"""
    if value is None or (isinstance(value, str) and value.strip() == ""):
        result.add_error(field_name, f"{field_name}は必須です")
        return False
    return True


def validate_string_length(value: str, field_name: str, result: ValidationResult,
                           min_len: int = 0, max_len: int = 255):
    """文字列長チェック"""
    if value is None:
        return True
    length = len(str(value).strip())
    if length < min_len:
        result.add_error(field_name, f"{min_len}文字以上で入力してください")
        return False
    if length > max_len:
        result.add_error(field_name, f"{max_len}文字以内で入力してください")
        return False
    return True


def validate_range(value, field_name: str, result: ValidationResult,
                   min_val=None, max_val=None):
    """数値範囲チェック"""
    try:
        num = float(value)
    except (ValueError, TypeError):
        result.add_error(field_name, "数値を入力してください")
        return False
    if min_val is not None and num < min_val:
        result.add_error(field_name, f"{min_val}以上を入力してください")
        return False
    if max_val is not None and num > max_val:
        result.add_error(field_name, f"{max_val}以下を入力してください")
        return False
    return True


# ============================================================
# エンティティ固有バリデーション
# ============================================================

def validate_field(field_data: dict) -> ValidationResult:
    """ほ場データのバリデーション"""
    result = ValidationResult()
    validate_required(field_data.get('field_code'), 'ほ場コード', result)
    validate_required(field_data.get('name'), 'ほ場名', result)
    validate_string_length(field_data.get('name', ''), 'ほ場名', result, max_len=50)
    if field_data.get('area_ha') is not None:
        validate_range(field_data['area_ha'], '面積', result, min_val=0.01, max_val=1000)
    return result


def validate_crop(crop_data: dict) -> ValidationResult:
    """作物データのバリデーション"""
    result = ValidationResult()
    validate_required(crop_data.get('name'), '作物名', result)
    validate_string_length(crop_data.get('name', ''), '作物名', result, max_len=50)
    validate_required(crop_data.get('family'), '科名', result)
    validate_string_length(crop_data.get('family', ''), '科名', result, max_len=30)
    if crop_data.get('interval_years') is not None:
        validate_range(crop_data['interval_years'], '輪作間隔', result, min_val=1, max_val=10)
    return result


def validate_user(user_data: dict) -> ValidationResult:
    """ユーザーデータのバリデーション"""
    result = ValidationResult()
    validate_required(user_data.get('username'), 'ユーザー名', result)
    validate_string_length(user_data.get('username', ''), 'ユーザー名', result, min_len=3, max_len=30)
    validate_required(user_data.get('display_name'), '表示名', result)
    return result
