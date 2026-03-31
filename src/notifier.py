import os
from pathlib import Path

import requests
from dotenv import load_dotenv

# .env はプロジェクトルート（src/ の一つ上）に置く
load_dotenv(Path(__file__).parent.parent / ".env")

LINE_API_URL = "https://api.line.me/v2/bot/message/broadcast"


def get_line_token() -> str:
    """
    LINE チャネルアクセストークンを取得する。
    - ローカル開発: プロジェクトルートの .env ファイルから取得
    - GCP 上: Cloud Run Job の --set-secrets で環境変数に注入された値を取得
    """
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    if not token:
        raise EnvironmentError(
            "LINE_CHANNEL_ACCESS_TOKEN が .env または環境変数に設定されていません。"
        )
    return token


def send_broadcast(message: str) -> None:
    """
    LINE Broadcast でフォロワー全員にテキストメッセージを送信する。
    失敗した場合は例外を送出する。
    """
    token = get_line_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messages": [
            {
                "type": "text",
                "text": message,
            }
        ]
    }

    response = requests.post(LINE_API_URL, headers=headers, json=payload, timeout=10)
    response.raise_for_status()


def build_message(hours: str | None) -> str:
    """
    開館時間から送信メッセージを組み立てる。
    """
    if hours is None:
        return "📚 駒場図書館\n本日は休館日または開館情報を取得できませんでした。"
    return f"📚 駒場図書館\n本日の開館時間: {hours}"


if __name__ == "__main__":
    # 動作確認用: テストメッセージを送信
    test_message = build_message("8:30-20:00")
    print(f"送信メッセージ:\n{test_message}\n")

    send_broadcast(test_message)
    print("LINE 送信完了")
