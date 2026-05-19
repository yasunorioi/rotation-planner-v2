"""
ファイル操作ユーティリティ
CSV読み書きの安全なラッパー関数
"""
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import List, Tuple, Optional
from datetime import datetime

import pandas as pd

from rotation_planner.common.exceptions import CSVReadError, CSVWriteError

logger = logging.getLogger(__name__)


def read_csv_safe(
    file_path,
    required_columns: Optional[List[str]] = None,
    optional_columns: Optional[List[str]] = None
) -> Tuple[pd.DataFrame, List[str]]:
    """
    CSV読み込みの安全なラッパー

    Args:
        file_path: ファイルパス（str, Path, または Gradio ファイルオブジェクト）
        required_columns: 必須カラムのリスト（存在しない場合はエラー）
        optional_columns: オプションカラムのリスト（存在しない場合は警告）

    Returns:
        (DataFrame, warnings_list): 読み込んだDataFrameと警告メッセージのリスト

    Raises:
        CSVReadError: 読み込みエラー（ファイル不在、権限なし、パースエラー等）
    """
    warnings = []

    # Gradio ファイルオブジェクト対応
    if hasattr(file_path, 'name'):
        file_path = file_path.name

    path = Path(file_path)

    # ファイル存在チェック
    if not path.exists():
        raise CSVReadError(f"ファイルが見つかりません: {path}")

    # 読み取り権限チェック
    if not os.access(path, os.R_OK):
        raise CSVReadError(f"ファイルの読み取り権限がありません: {path}")

    # 空ファイルチェック
    if path.stat().st_size == 0:
        raise CSVReadError(f"ファイルが空です: {path}")

    # エンコーディング自動検出で読み込み
    encodings = ['utf-8-sig', 'utf-8', 'shift-jis', 'cp932']
    df = None
    last_error = None

    for encoding in encodings:
        try:
            df = pd.read_csv(path, encoding=encoding)
            logger.debug(f"CSV読み込み成功（エンコーディング: {encoding}）")
            break
        except (UnicodeDecodeError, pd.errors.ParserError) as e:
            last_error = e
            continue
        except pd.errors.EmptyDataError as e:
            raise CSVReadError(f"CSVデータが空です: {path}") from e

    if df is None:
        raise CSVReadError(
            f"CSVの読み込みに失敗しました: {path}（全エンコーディングで失敗）"
        ) from last_error

    # 必須カラムチェック
    if required_columns:
        missing_cols = [col for col in required_columns if col not in df.columns]
        if missing_cols:
            raise CSVReadError(
                f"必須カラムが不足しています: {', '.join(missing_cols)}"
            )

    # オプションカラム警告
    if optional_columns:
        missing_optional = [col for col in optional_columns if col not in df.columns]
        if missing_optional:
            warning_msg = f"オプションカラムが見つかりません: {', '.join(missing_optional)}"
            warnings.append(warning_msg)
            logger.warning(warning_msg)

    logger.info(f"CSV読み込み成功: {len(df)}行")

    return df, warnings


def write_csv_safe(
    df: pd.DataFrame,
    output_dir: str = "/tmp",
    filename: Optional[str] = None,
    encoding: str = "utf-8-sig"
) -> Tuple[str, str]:
    """
    CSV書き込みの安全なラッパー

    Args:
        df: 書き込むDataFrame
        output_dir: 出力ディレクトリ
        filename: ファイル名（Noneの場合は自動生成）
        encoding: 文字エンコーディング

    Returns:
        (filepath, message): 書き込んだファイルパスと成功メッセージ

    Raises:
        CSVWriteError: 書き込みエラー（権限なし、容量不足等）
    """
    # データ存在チェック
    if df is None or df.empty:
        raise CSVWriteError("書き込むデータが空です")

    # 出力ディレクトリ作成
    output_path = Path(output_dir)
    try:
        output_path.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise CSVWriteError(f"出力ディレクトリの作成に失敗しました: {output_dir}") from e

    # 書き込み権限チェック
    if not os.access(output_path, os.W_OK):
        raise CSVWriteError(f"出力ディレクトリへの書き込み権限がありません: {output_dir}")

    # ディスク容量チェック
    # 推定サイズ: 各セルを平均20文字と仮定し、2倍のマージンを取る
    estimated_size = len(df) * len(df.columns) * 20 * 2
    disk_usage = shutil.disk_usage(output_path)
    if disk_usage.free < estimated_size:
        raise CSVWriteError(
            f"ディスク容量が不足しています（必要: {estimated_size // 1024}KB、空き: {disk_usage.free // 1024}KB）"
        )

    # ファイル名自動生成
    if filename is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}.csv"

    filepath = output_path / filename

    # アトミック書き込み（tempfile + shutil.move）
    try:
        with tempfile.NamedTemporaryFile(
            mode='w',
            delete=False,
            dir=output_path,
            suffix='.tmp',
            encoding=encoding
        ) as tmp_file:
            df.to_csv(tmp_file.name, index=False, encoding=encoding)
            tmp_path = tmp_file.name

        # 一時ファイルを目的のファイル名に移動
        shutil.move(tmp_path, filepath)

        success_msg = f"✅ {len(df)}件を出力しました: {filename}"
        logger.info(f"CSV書き込み成功: {filepath} ({len(df)}行)")

        return str(filepath), success_msg

    except PermissionError as e:
        # 一時ファイルのクリーンアップ
        if 'tmp_path' in locals() and Path(tmp_path).exists():
            Path(tmp_path).unlink()
        raise CSVWriteError("ファイルが使用中です") from e

    except OSError as e:
        # 一時ファイルのクリーンアップ
        if 'tmp_path' in locals() and Path(tmp_path).exists():
            Path(tmp_path).unlink()

        # ディスク容量不足の可能性
        if e.errno == 28:  # ENOSPC
            raise CSVWriteError("ディスク容量が不足しています") from e

        logger.error(f"CSV書き込み失敗: {e}")
        raise CSVWriteError(f"CSV書き込みに失敗しました: {e}") from e

    except Exception as e:
        # 一時ファイルのクリーンアップ
        if 'tmp_path' in locals() and Path(tmp_path).exists():
            Path(tmp_path).unlink()

        logger.error(f"CSV書き込み失敗（予期しないエラー）: {e}")
        raise CSVWriteError(f"CSV書き込みに失敗しました: {e}") from e
