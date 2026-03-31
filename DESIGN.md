# 東大図書館開館チェッカー Bot — 設計書

> Google Cloud Associate Cloud Engineer (ACE) 試験対策プロジェクト

---

## 概要

東京大学の図書館の開館情報をスクレイピングし、毎朝 LINE に通知する Bot。
GCP の主要サービスを横断的に使うことで ACE 試験の頻出トピックを実践的に習得する。

---

## システム構成図

```
Cloud Scheduler (毎日 06:00)
        │
        ▼ メッセージ publish
  Pub/Sub Topic [library-check-topic]
        │
        ▼ サブスクリプション → Job 起動
  Cloud Run Job [library-checker-job]
        │
        ├─── Secret Manager から LINE トークン取得
        │
        ├─── 東大図書館サイト スクレイピング
        │
        ├─── LINE Messaging API で通知送信
        │
        └─── Cloud Logging にログ出力

  Artifact Registry
  └─ [asia-northeast1-docker.pkg.dev/<PROJECT>/library-bot/checker:latest]
        ↑
  ローカル Docker Build & Push
```

---

## 1. ローカル開発・Docker 化（CI/CD の基礎）

### 1-1. ディレクトリ構成

```
library-bot/
├── DESIGN.md              # 本ファイル
├── Dockerfile
├── requirements.txt
├── src/
│   ├── main.py            # エントリポイント
│   ├── scraper.py         # スクレイピングロジック
│   └── notifier.py        # LINE 通知ロジック
└── .dockerignore
```

### 1-2. スクレイピング方針

| 方式 | ライブラリ | 用途 |
|------|-----------|------|
| 静的 HTML 解析 | `requests` + `BeautifulSoup4` | 東大図書館の開館カレンダー（JavaScript 不要な場合） |
| 動的レンダリング対応 | `selenium` + `chromedriver` | JS レンダリングが必要な場合（Dockerfile に Chrome を含める） |

> 方針: まず BeautifulSoup で試み、取得できなければ Selenium に切り替える。

### 1-3. Dockerfile（BeautifulSoup 版）

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

CMD ["python", "src/main.py"]
```

### 1-4. requirements.txt

```
requests==2.32.3
beautifulsoup4==4.12.3
line-bot-sdk==3.12.0
google-cloud-secret-manager==2.20.0
```

### 1-5. Artifact Registry へのプッシュ手順（ACE コマンド習得）

```bash
# リポジトリ作成
gcloud artifacts repositories create library-bot \
  --repository-format=docker \
  --location=asia-northeast1 \
  --description="Library checker bot images"

# Docker 認証設定
gcloud auth configure-docker asia-northeast1-docker.pkg.dev

# ビルド & タグ付け
docker build -t asia-northeast1-docker.pkg.dev/<PROJECT_ID>/library-bot/checker:latest .

# プッシュ
docker push asia-northeast1-docker.pkg.dev/<PROJECT_ID>/library-bot/checker:latest
```

**ACE 学習ポイント:**
- `gcloud auth configure-docker` による認証の仕組み
- イメージの **タグ付け規則**（リージョン/プロジェクト/リポジトリ/イメージ名:タグ）
- Artifact Registry と旧 Container Registry の違い

---

## 2. 実行基盤：Cloud Run Jobs（サーバーレス・バッチ）

### 2-1. サービス vs ジョブの使い分け

| | Cloud Run **Service** | Cloud Run **Job** |
|--|----------------------|-------------------|
| 用途 | HTTP リクエストを待ち受ける常時稼働型 | 処理して終了するバッチ型 |
| 課金 | リクエスト処理時間のみ | 実行時間のみ |
| 本 Bot の適合性 | × （待ち受け不要） | ◎ |

### 2-2. Job 作成コマンド

```bash
gcloud run jobs create library-checker-job \
  --image=asia-northeast1-docker.pkg.dev/<PROJECT_ID>/library-bot/checker:latest \
  --region=asia-northeast1 \
  --service-account=library-checker-sa@<PROJECT_ID>.iam.gserviceaccount.com \
  --set-secrets=LINE_CHANNEL_ACCESS_TOKEN=line-channel-token:latest \
  --memory=512Mi \
  --cpu=1 \
  --max-retries=3 \
  --task-timeout=300s
```

### 2-3. リソース設定指針

| パラメータ | 設定値 | 理由 |
|-----------|--------|------|
| `--memory` | 512Mi | スクレイピング + HTTP 通信で十分 |
| `--cpu` | 1 | 単一タスクのバッチ処理 |
| `--max-retries` | 3 | 一時的なネットワークエラーへの耐性 |
| `--task-timeout` | 300s | スクレイピングのタイムアウト余裕を持たせる |

**ACE 学習ポイント:**
- Job の **タスク並列数**（`--tasks`）と **並列実行数**（`--parallelism`）の概念
- 失敗時のリトライポリシー
- リージョン選定（レイテンシ・コスト・データ主権）

---

## 3. トリガー：Cloud Scheduler + Pub/Sub（疎結合なイベント駆動）

### 3-1. アーキテクチャの意図

```
Scheduler ──直接→ Cloud Run Job   # シンプルだが密結合
Scheduler ──→ Pub/Sub ──→ Job    # 疎結合・スケーラブル（本設計）
```

Pub/Sub を挟む利点:
- **疎結合**: Scheduler と Job が直接依存しない
- **バッファリング**: Job が一時的に起動できなくてもメッセージが保持される
- **拡張性**: 同じトピックから別のサブスクライバー（例: BigQuery へのログ保存）を追加できる

### 3-2. 構築手順

```bash
# Pub/Sub トピック作成
gcloud pubsub topics create library-check-topic

# サブスクリプション作成（push 型で Cloud Run Job を起動）
gcloud pubsub subscriptions create library-check-sub \
  --topic=library-check-topic \
  --push-endpoint=https://<CLOUD_RUN_JOB_TRIGGER_URL> \
  --ack-deadline=600

# Cloud Scheduler ジョブ作成
gcloud scheduler jobs create pubsub library-check-schedule \
  --schedule="0 6 * * *" \
  --time-zone="Asia/Tokyo" \
  --topic=library-check-topic \
  --message-body='{"trigger":"daily-check"}' \
  --location=asia-northeast1
```

### 3-3. Cron 式の読み方

```
0 6 * * *
│ │ │ │ └── 曜日（* = 毎日）
│ │ │ └──── 月（* = 毎月）
│ │ └────── 日（* = 毎日）
│ └──────── 時（6 = 6時）
└────────── 分（0 = 0分）
```

**ACE 学習ポイント:**
- Pub/Sub の **push 型** vs **pull 型** サブスクリプションの違い
- メッセージの **at-least-once 配信** 保証と冪等性の設計
- Scheduler のタイムゾーン設定（試験頻出: デフォルトは UTC）

---

## 4. セキュリティ：Secret Manager + IAM（権限管理の真髄）

### 4-1. Secret Manager の設定

```bash
# Secret の作成（LINE チャネルアクセストークンを保存）
echo -n "<YOUR_LINE_TOKEN>" | gcloud secrets create line-channel-token \
  --data-file=- \
  --replication-policy=automatic
```

### 4-2. サービスアカウントと IAM 設定（最小権限の原則）

```bash
# Cloud Run Job 専用サービスアカウントを作成
gcloud iam service-accounts create library-checker-sa \
  --display-name="Library Checker Bot Service Account"

# Secret へのアクセス権限のみを付与
gcloud secrets add-iam-policy-binding line-channel-token \
  --member="serviceAccount:library-checker-sa@<PROJECT_ID>.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

# Cloud Run Job 起動権限（Pub/Sub サブスクリプション用）
gcloud projects add-iam-policy-binding <PROJECT_ID> \
  --member="serviceAccount:library-checker-sa@<PROJECT_ID>.iam.gserviceaccount.com" \
  --role="roles/run.invoker"
```

### 4-3. IAM 権限マトリックス

| サービスアカウント | 付与ロール | 理由 |
|-------------------|-----------|------|
| `library-checker-sa` | `roles/secretmanager.secretAccessor` | LINE トークン読み取り |
| `library-checker-sa` | `roles/run.invoker` | Job の自己起動 |
| `library-checker-sa` | `roles/logging.logWriter` | Cloud Logging への書き込み |

> 与えない権限の例: `roles/editor`, `roles/owner`, `roles/secretmanager.admin`

### 4-4. コード内での Secret 取得

```python
# src/main.py
from google.cloud import secretmanager

def get_secret(secret_id: str, project_id: str) -> str:
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")
```

**ACE 学習ポイント:**
- **最小権限の原則 (Principle of Least Privilege)**: 必要最低限のロールのみ付与
- リソースレベル IAM（Secret 単位）vs プロジェクトレベル IAM の違い
- サービスアカウントキーを使わず **Workload Identity** で認証する考え方

---

## 5. 運用監視：Cloud Logging（トラブルシューティング）

### 5-1. 構造化ログの出力

```python
# src/main.py
import json
import sys

def log(severity: str, message: str, **kwargs):
    entry = {
        "severity": severity,   # INFO / WARNING / ERROR / CRITICAL
        "message": message,
        **kwargs
    }
    print(json.dumps(entry, ensure_ascii=False), flush=True)

# 使用例
log("INFO", "スクレイピング開始", url="https://lib.u-tokyo.ac.jp/")
log("INFO", "開館情報取得成功", library="総合図書館", status="開館", hours="9:00-22:00")
log("INFO", "LINE 送信完了", recipient_count=1)
log("ERROR", "スクレイピング失敗", error=str(e), traceback=traceback.format_exc())
```

### 5-2. Cloud Console でのログ確認

```
# ログエクスプローラーでのフィルタ例
resource.type="cloud_run_job"
resource.labels.job_name="library-checker-job"
severity>=ERROR

# 特定メッセージを検索
jsonPayload.message="LINE 送信完了"
```

### 5-3. アラート設定（発展）

```bash
# エラーログが出たときにメール通知するアラートポリシーを作成
gcloud alpha monitoring policies create \
  --policy-from-file=alert-policy.json
```

**ACE 学習ポイント:**
- **ログシンク**: Cloud Logging から BigQuery や Cloud Storage にログをエクスポート
- **ログベースのメトリクス**: エラー数をグラフ化してモニタリング
- 構造化ログ（JSON）の利点: フィールド単位でフィルタリング可能

---

## コスト試算（月額）

| サービス | 使用量 | 月額概算 |
|---------|--------|---------|
| Cloud Run Jobs | 30回/月 × 5秒 | 無料枠内（$0） |
| Cloud Scheduler | 1ジョブ | 無料枠内（3ジョブまで無料） |
| Pub/Sub | 30メッセージ/月 | 無料枠内（$0） |
| Secret Manager | 1 Secret, 30アクセス/月 | 無料枠内（$0） |
| Artifact Registry | 〜500MB | 〜$0.05 |
| Cloud Logging | 〜1MB/月 | 無料枠内（$0） |
| **合計** | | **〜$0.05/月** |

---

## 実装ロードマップ

```
Phase 1: ローカル開発
  └─ スクレイピングコード作成・動作確認
  └─ LINE 通知コード作成・動作確認
  └─ Docker ビルド・ローカル実行確認

Phase 2: GCP 基盤構築
  └─ Artifact Registry リポジトリ作成
  └─ イメージ push
  └─ Secret Manager に LINE トークン登録
  └─ サービスアカウント + IAM 設定
  └─ Cloud Run Job 作成・手動実行テスト

Phase 3: 自動化
  └─ Pub/Sub トピック + サブスクリプション作成
  └─ Cloud Scheduler 設定
  └─ エンドツーエンドテスト（Scheduler → Pub/Sub → Job → LINE）

Phase 4: 運用
  └─ Cloud Logging でログ確認
  └─ エラーアラート設定
  └─ コスト確認
```

---

## ACE 試験対策マッピング

| 試験ドメイン | 本プロジェクトでの実践内容 |
|------------|------------------------|
| デプロイとインフラ管理 | Cloud Run Jobs の作成・設定、Artifact Registry |
| ストレージとデータベース | Secret Manager（シークレット管理） |
| ネットワーキング | Pub/Sub のメッセージ配信モデル |
| セキュリティとコンプライアンス | IAM・最小権限の原則・サービスアカウント |
| 運用 | Cloud Logging・ログフィルタリング・アラート |
| スケーリングと可用性 | Cloud Run の自動スケーリング・リトライポリシー |
