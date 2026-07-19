# kokora-poster（ここら配信くん）

地図アプリ **ここら** のリール動画を、X **@waveblasttaiyo** へ自動投稿するシステム。

- **1日6投稿**：日本語3回（JST 08:00 / 12:30 / 20:00）＋ 英語3回（JST 07:00 / 15:00 / 23:00）
- 動画 **30本**（和15・英15）× 本文 **3パターン** ＝ **90案** を言語ごとに順番にローテーション
- 同じ動画でも文面が変わるので、繰り返しても“同じ投稿”に見えない
- 1周すると先頭に戻る（和45案 ÷ 3投稿/日 ＝ 15日で一巡）

---

## セットアップ（この順番で）

### 1. リポジトリは「Public」で作る ★重要
公開リポジトリなら **GitHub Actions が無料・無制限**。
（privateだと無料枠2,000分を消費し、枠切れで停止する。現に他リポジトリはそれで止まっている）
コードが公開されてもトークンは Secrets に隠れるので安全。

### 2. X APIの認証情報を用意する ★ここが唯一の前提
**必ず @waveblasttaiyo でログインした状態で発行すること。**
他アカウント（例：@makochinta1）のトークンを使うと、そちらへ投稿されてしまう。

1. https://developer.x.com/ にアクセス（@waveblasttaiyo でログイン）
2. App を作成（既存Appを使う場合も、**Access Token は @waveblasttaiyo で再発行**）
3. App の権限を **Read and Write** にする（Readのみだと投稿できない）
4. 以下4つを控える
   - API Key / API Key Secret
   - Access Token / Access Token Secret

### 3. GitHub Secrets に登録
リポジトリ → Settings → Secrets and variables → Actions → New repository secret

| Secret 名 | 中身 |
|---|---|
| `X_API_KEY` | API Key |
| `X_API_SECRET` | API Key Secret |
| `X_ACCESS_TOKEN` | Access Token（@waveblasttaiyo で発行） |
| `X_ACCESS_TOKEN_SECRET` | Access Token Secret |

### 4. まず dry-run で確認
Actions → `Post kokora reel (JA)` → Run workflow → `dry_run` に `true`
→ 投稿せずに「次に出る本文と動画」だけログに出る。英語版も同様。

### 5. 本番稼働
dry-run が問題なければ、そのまま cron で自動投稿が始まる。

---

## 構成

```
scripts/post_to_x.py        投稿本体（動画アップロード→ツイート→位置を進める）
queue/patterns.json         90案（reel / lang / variant / video / text）
queue/state.json            次に出す位置と投稿履歴（Actionsが自動更新）
assets/reels/*.mp4          縦型リール動画30本
.github/workflows/post-jp.yml   日本語 1日3回
.github/workflows/post-en.yml   英語 1日3回
```

## 運用メモ

- **文面を直したい**：`queue/patterns.json` の該当 `text` を編集してコミットするだけ。
- **順番を変えたい / 先頭に戻したい**：`queue/state.json` の `ja_index` / `en_index` を書き換える。
- **一時停止したい**：Actions → 該当ワークフロー → `Disable workflow`。
- **BGM**：動画は無音。Xでは音源を後付けできないため、必要なら動画側に入れて差し替える。
- **投稿頻度の判断**：1日6投稿は小規模アカウントにはやや多め。伸びが悪い／反応が薄いと感じたら
  cron を減らす（例：和2＋英2）。数字を見て決めること。

## 分析（どの投稿がアプリ流入を生んだか）

App Store への誘導は、akarilab-site の中継リンク `/r/x-kokora-<reel>` 経由にすると、
GA4 の `redirect_click` イベントで **リール別のクリック数**が取れる（週次レポートに自動集計）。
中継リンクを使う場合は `queue/patterns.json` の各 `text` 内のURLを差し替える。
