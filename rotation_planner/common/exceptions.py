# rotation_planner/common/exceptions.py

class RotationPlannerError(Exception):
    """アプリケーション固有エラーの基底クラス"""
    def __init__(self, message: str, user_message: str = None):
        self.message = message
        self.user_message = user_message or message
        super().__init__(message)


# === DB関連 ===
class DatabaseError(RotationPlannerError):
    """DB操作エラーの基底クラス"""
    pass

class DatabaseConnectionError(DatabaseError):
    """DB接続エラー"""
    pass

class DuplicateKeyError(DatabaseError):
    """重複キーエラー"""
    pass

class NotNullViolationError(DatabaseError):
    """NOT NULL制約違反"""
    pass

class ForeignKeyViolationError(DatabaseError):
    """外部キー制約違反"""
    pass

class RecordNotFoundError(DatabaseError):
    """対象レコードなし"""
    pass


# === ファイル操作関連 ===
class FileOperationError(RotationPlannerError):
    """ファイル操作エラーの基底クラス"""
    def __init__(self, message: str, recoverable: bool = False):
        super().__init__(message)
        self.recoverable = recoverable

class CSVReadError(FileOperationError):
    """CSV読み込みエラー"""
    pass

class CSVWriteError(FileOperationError):
    """CSV書き出しエラー"""
    pass

class PDFGenerationError(FileOperationError):
    """PDF生成エラー"""
    pass


# === バリデーション関連 ===
class ValidationError(RotationPlannerError):
    """バリデーションエラー"""
    def __init__(self, field: str, message: str, value=None):
        self.field = field
        self.value = value
        super().__init__(message)
