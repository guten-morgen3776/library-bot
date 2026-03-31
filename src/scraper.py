import requests
from bs4 import BeautifulSoup

KOMABA_URL = "https://www.lib.u-tokyo.ac.jp/ja/library/komaba"


def get_komaba_opening_hours() -> str | None:
    """
    駒場図書館のページから本日の開館時間を取得する。
    取得できた場合は時間文字列（例: "8:30-20:00"）を返す。
    取得できなかった場合は None を返す。
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }

    response = requests.get(KOMABA_URL, headers=headers, timeout=10)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    # dl.opening-hour.library-color__komaba 内の dt/dd を探す
    dl = soup.find("dl", class_=lambda c: c and "library-color__komaba" in c)
    if dl is None:
        return None

    dt = dl.find("dt")
    dd = dl.find("dd")

    if dt is None or dd is None:
        return None

    label = dt.get_text(strip=True)
    if label != "本日の開館時間":
        return None

    return dd.get_text(strip=True)


if __name__ == "__main__":
    hours = get_komaba_opening_hours()
    if hours:
        print(f"本日の開館時間: {hours}")
    else:
        print("開館時間を取得できませんでした（休館日または取得エラー）")
