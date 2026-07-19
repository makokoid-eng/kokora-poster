#!/usr/bin/env python3
"""post_to_x.py

PURPOSE
-------
目的：地図アプリ「ここら」のリール動画を、X（@waveblasttaiyo）へ自動投稿する。
背景：ここらの宣伝を1日6投稿（日本語3・英語3）で回す。動画30本 × 本文3パターン＝90案を
      言語ごとに順番にローテーションし、同じ動画でも文面が変わるようにする。
使い方：
    python scripts/post_to_x.py --lang ja           # 日本語を1件投稿
    python scripts/post_to_x.py --lang en           # 英語を1件投稿
    python scripts/post_to_x.py --lang ja --dry-run # 投稿せず内容だけ表示

必要な環境変数（GitHub Secrets に登録）:
    X_API_KEY, X_API_SECRET            : X Developer App の API Key / Secret
    X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET
        : ※必ず @waveblasttaiyo でログインして発行したトークンを使うこと。
          他アカウントのトークンだとそちらへ投稿されてしまう。

データ:
    queue/patterns.json : 90案（reel, lang, variant, video, text）
    queue/state.json    : {"ja_index":n, "en_index":n, "posted":[...]} 次に出す位置と履歴
    assets/reels/*.mp4  : 投稿する縦型リール動画（30本）

処理の流れ:
    1. patterns.json から指定言語の案を読み、state.json のインデックスで次の1件を選ぶ
    2. 動画を X にアップロード（チャンク送信・処理完了を待機）
    3. 本文＋動画でツイート作成
    4. state.json のインデックスを1つ進め、投稿履歴を追記（呼び出し側の workflow が commit）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import tweepy

ROOT = Path(__file__).resolve().parent.parent
PATTERNS = ROOT / "queue" / "patterns.json"
STATE = ROOT / "queue" / "state.json"
REELS = ROOT / "assets" / "reels"
JST = timezone(timedelta(hours=9))


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def pick(lang: str):
    """指定言語の次の1件と、その位置を返す。末尾まで行ったら先頭へ戻る。"""
    patterns = [p for p in load_json(PATTERNS) if p["lang"] == lang]
    if not patterns:
        raise RuntimeError(f"no patterns for lang={lang}")
    state = load_json(STATE)
    key = f"{lang}_index"
    idx = int(state.get(key, 0)) % len(patterns)
    return patterns[idx], idx, len(patterns), state, key


def upload_video(api: tweepy.API, path: Path) -> str:
    """動画をチャンクアップロードし、X側の変換完了まで待って media_id を返す。"""
    media = api.media_upload(filename=str(path), chunked=True, media_category="tweet_video")
    # 変換待ち（最大約3分）
    for _ in range(60):
        info = getattr(media, "processing_info", None)
        if not info or info.get("state") == "succeeded":
            return media.media_id_string
        if info.get("state") == "failed":
            raise RuntimeError(f"media processing failed: {info}")
        time.sleep(max(int(info.get("check_after_secs", 3)), 3))
        media = api.get_media_upload_status(media.media_id)  # type: ignore[attr-defined]
    raise RuntimeError("media processing timed out")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", required=True, choices=["ja", "en"])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    item, idx, total, state, key = pick(args.lang)
    video = REELS / item["video"]
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M")

    print(f"[{now} JST] lang={args.lang} {idx + 1}/{total} reel={item['reel']} variant={item['variant']}")
    print(f"--- 本文 ---\n{item['text']}\n--- 動画 ---\n{video.name}")

    if args.dry_run:
        print("dry-run のため投稿しません。")
        return 0

    if not video.exists():
        raise FileNotFoundError(f"video not found: {video}")

    ck = os.environ["X_API_KEY"]
    cs = os.environ["X_API_SECRET"]
    at = os.environ["X_ACCESS_TOKEN"]
    ats = os.environ["X_ACCESS_TOKEN_SECRET"]

    api = tweepy.API(tweepy.OAuth1UserHandler(ck, cs, at, ats))
    client = tweepy.Client(
        consumer_key=ck, consumer_secret=cs,
        access_token=at, access_token_secret=ats,
    )

    media_id = upload_video(api, video)
    resp = client.create_tweet(text=item["text"], media_ids=[media_id])
    tweet_id = resp.data.get("id") if resp and resp.data else None
    print(f"posted: https://x.com/waveblasttaiyo/status/{tweet_id}")

    # 位置を進めて履歴を残す（履歴は直近200件だけ保持）
    state[key] = (idx + 1) % total
    posted = state.get("posted", [])
    posted.append({
        "at": now, "lang": args.lang, "reel": item["reel"],
        "variant": item["variant"], "tweet_id": str(tweet_id),
    })
    state["posted"] = posted[-200:]
    save_json(STATE, state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
