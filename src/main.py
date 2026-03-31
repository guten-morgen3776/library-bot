import json
import sys
import traceback

from scraper import get_komaba_opening_hours
from notifier import build_message, send_broadcast


def log(severity: str, message: str, **kwargs) -> None:
    """
    Cloud Logging が構造化ログとして認識する JSON 形式で標準出力に書き出す。
    ローカルでも同じコードで動作する。
    """
    entry = {"severity": severity, "message": message, **kwargs}
    print(json.dumps(entry, ensure_ascii=False), flush=True)


def main() -> None:
    log("INFO", "処理開始")

    # 1. スクレイピング
    try:
        hours = get_komaba_opening_hours()
        log("INFO", "開館情報取得成功", hours=hours)
    except Exception as e:
        log("ERROR", "スクレイピング失敗", error=str(e), traceback=traceback.format_exc())
        sys.exit(1)

    # 2. LINE 通知
    try:
        message = build_message(hours)
        send_broadcast(message)
        log("INFO", "LINE 送信完了", line_message=message)
    except Exception as e:
        log("ERROR", "LINE 送信失敗", error=str(e), traceback=traceback.format_exc())
        sys.exit(1)

    log("INFO", "処理完了")


if __name__ == "__main__":
    main()
