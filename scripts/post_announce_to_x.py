#!/usr/bin/env python3
"""post_announce_to_x.py

PURPOSE
-------
目的：ここら(アプリ)のリリース告知（iOS＋Android両対応）を X（@waveblasttaiyo）へ投稿する。
      各告知にメディア（画像 or 動画）を添付できる。media 未指定ならテキストのみで投稿（後方互換）。
背景：災害支援投稿を停止し、その枠をここらのリリース告知に置き換えた。当初はテキストのみだったが、
      Android告知にも画像/動画を付けたい要望を受けてメディア添付に対応（2026-08-01）。
      告知期間（〜2026-08-21）は毎枠投稿。以降は decay（頻度を落として通常ローテへ）。
使い方：
      python scripts/post_announce_to_x.py            # 告知を1件投稿（重み付き・media あれば添付）
      python scripts/post_announce_to_x.py --dry-run  # 投稿せず、選ばれる本文と添付メディアだけ表示

必要な環境変数（GitHub Secrets）:
      X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET

データ:
      queue/announce_queue.json : 告知案（id, lang, weight, pin, media?, text）
                                  media は assets/ からの相対パス（例 "reels/jp09_sodateru.mp4"）。任意。
      queue/announce_state.json : {"posted":[...]} 投稿履歴

選択ロジック:
      - まだ一度も投稿していなければ pin=True の案（JA-1）を最初に投稿（ピン留め用に先頭固定）。
      - それ以降は weight による重み付きランダム（JA-1が最頻）。
      - 告知期間終了（2026-08-21）以降は decay：3回に1回程度だけ投稿し、通常ここらローテに主役を譲る。

メディア添付:
      - item["media"] があり、assets/ 配下に実ファイルが存在する場合のみ添付。
      - 拡張子で判定：.mp4/.mov → 動画（チャンク送信＋変換完了待ち）、
        .png/.jpg/.jpeg/.gif/.webp → 画像（単純アップロード）。
      - media 未指定 or ファイル不在 or 未対応拡張子 → テキストのみで投稿（失敗させず告知は止めない）。
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import tweepy

ROOT = Path(__file__).resolve().parent.parent
QUEUE = ROOT / "queue" / "announce_queue.json"
STATE = ROOT / "queue" / "announce_state.json"
ASSETS = ROOT / "assets"                      # media は assets/ からの相対パスで指定
JST = timezone(timedelta(hours=9))
DECAY_DATE = datetime(2026, 8, 21, tzinfo=JST)  # この日を過ぎたら頻度を落とす

VIDEO_EXT = {".mp4", ".mov"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def pick(items, state):
    """最初の1本は pin=True（JA-1）。以降は weight 重み付きランダム。"""
    if not state.get("posted"):
        pinned = [p for p in items if p.get("pin")]
        if pinned:
            return pinned[0]
    weights = [max(int(p.get("weight", 1)), 1) for p in items]
    return random.choices(items, weights=weights, k=1)[0]


def resolve_media(item) -> Path | None:
    """item["media"]（assets/ からの相対パス）を絶対パスに解決する。
    未指定・ファイル不在なら None を返す（＝テキストのみ投稿にフォールバック）。"""
    rel = item.get("media")
    if not rel:
        return None
    path = (ASSETS / rel).resolve()
    if not path.exists():
        print(f"::warning::media 指定あり but ファイル不在のためテキストのみで投稿: {rel}")
        return None
    return path


def upload_media(api: tweepy.API, path: Path) -> str | None:
    """画像/動画を X にアップロードして media_id を返す。
    引数 : api  = tweepy.API(OAuth1)。path = 添付するメディアの絶対パス。
    出力 : media_id 文字列。未対応拡張子なら None（＝添付せずテキストのみ）。"""
    ext = path.suffix.lower()
    if ext in VIDEO_EXT:
        # 動画：チャンク送信し、X側の変換完了まで待って media_id を返す（最大約3分）
        media = api.media_upload(filename=str(path), chunked=True, media_category="tweet_video")
        for _ in range(60):
            info = getattr(media, "processing_info", None)
            if not info or info.get("state") == "succeeded":
                return media.media_id_string
            if info.get("state") == "failed":
                raise RuntimeError(f"media processing failed: {info}")
            time.sleep(max(int(info.get("check_after_secs", 3)), 3))
            media = api.get_media_upload_status(media.media_id)  # type: ignore[attr-defined]
        raise RuntimeError("media processing timed out")
    if ext in IMAGE_EXT:
        # 画像：単純アップロード（変換待ち不要）
        media = api.media_upload(filename=str(path))
        return media.media_id_string
    print(f"::warning::未対応のメディア拡張子（{ext}）のためテキストのみで投稿: {path.name}")
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    now_dt = datetime.now(JST)
    now = now_dt.strftime("%Y-%m-%d %H:%M")

    # 告知期間後の decay：3回に1回程度だけ投稿（意図的スキップ＝失敗ではない）
    if now_dt > DECAY_DATE and (now_dt.timetuple().tm_yday % 3 != 0):
        print(f"[{now} JST] decay期間（{DECAY_DATE.date()}以降）につき今回はスキップ。通常ローテを主役に。")
        return 0

    items = load_json(QUEUE)
    state = load_json(STATE) if STATE.exists() else {"posted": []}
    item = pick(items, state)
    media_path = resolve_media(item)

    print(f"[{now} JST] announce id={item['id']} lang={item['lang']} pin={item.get('pin', False)}")
    print(f"--- 本文 ---\n{item['text']}")
    print(f"--- メディア ---\n{media_path.name if media_path else '(なし・テキストのみ)'}")

    if args.dry_run:
        print("dry-run のため投稿しません。")
        return 0

    ck = os.environ["X_API_KEY"]
    cs = os.environ["X_API_SECRET"]
    at = os.environ["X_ACCESS_TOKEN"]
    ats = os.environ["X_ACCESS_TOKEN_SECRET"]
    api = tweepy.API(tweepy.OAuth1UserHandler(ck, cs, at, ats))  # media_upload に必要
    client = tweepy.Client(
        consumer_key=ck, consumer_secret=cs,
        access_token=at, access_token_secret=ats,
    )

    try:
        media_id = upload_media(api, media_path) if media_path else None
        if media_id:
            resp = client.create_tweet(text=item["text"], media_ids=[media_id])
        else:
            resp = client.create_tweet(text=item["text"])  # メディアなし・テキストのみ
    except Exception as e:
        # 静かに死なせない：支出上限/権限などの失敗は GitHub Actions のエラー注釈＋非ゼロ終了で必ず目立たせる
        msg = str(e)
        hint = ""
        if "spend cap" in msg.lower() or "403" in msg or "429" in msg.lower():
            hint = " ← X APIの支出上限/レート/権限の可能性。コンソールでクレジット残高と支出上限を確認。"
        print(f"::error::投稿失敗（announce {item['id']}）: {msg}{hint}")
        raise

    tweet_id = resp.data.get("id") if resp and resp.data else None
    url = f"https://x.com/waveblasttaiyo/status/{tweet_id}"
    print(f"posted: {url}")
    if item.get("pin"):
        print(f"::notice::ピン留め候補（JA-1）を投稿しました。プロフィールで手動ピン留め推奨: {url}")

    posted = state.get("posted", [])
    posted.append({
        "at": now, "id": item["id"], "lang": item["lang"],
        "media": item.get("media"), "tweet_id": str(tweet_id),
    })
    state["posted"] = posted[-200:]
    save_json(STATE, state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
