#!/usr/bin/env python3
"""post_announce_to_x.py

PURPOSE
-------
目的：ここら(アプリ)のリリース告知（iOS＋Android両対応）を X（@waveblasttaiyo）へ投稿する。
背景：災害支援投稿を停止し、その枠をここらのリリース告知に置き換える。テキストのみ（動画なし）。
      告知期間（〜2026-08-21）は毎枠投稿。以降は decay（頻度を落として通常ローテへ）。
使い方：
    python scripts/post_announce_to_x.py            # 告知を1件投稿（重み付き）
    python scripts/post_announce_to_x.py --dry-run  # 投稿せず選ばれる本文だけ表示

必要な環境変数（GitHub Secrets）:
    X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET

データ:
    queue/announce_queue.json : 告知案（id, lang, weight, pin, text）
    queue/announce_state.json : {"posted":[...]} 投稿履歴

選択ロジック:
    - まだ一度も投稿していなければ pin=True の案（JA-1）を最初に投稿（ピン留め用に先頭固定）。
    - それ以降は weight による重み付きランダム（JA-1が最頻）。
    - 告知期間終了（2026-08-21）以降は decay：3回に1回程度だけ投稿し、通常ここらローテに主役を譲る。
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import tweepy

ROOT = Path(__file__).resolve().parent.parent
QUEUE = ROOT / "queue" / "announce_queue.json"
STATE = ROOT / "queue" / "announce_state.json"
JST = timezone(timedelta(hours=9))
DECAY_DATE = datetime(2026, 8, 21, tzinfo=JST)  # この日を過ぎたら頻度を落とす


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

    print(f"[{now} JST] announce id={item['id']} lang={item['lang']} pin={item.get('pin', False)}")
    print(f"--- 本文 ---\n{item['text']}")

    if args.dry_run:
        print("dry-run のため投稿しません。")
        return 0

    ck = os.environ["X_API_KEY"]
    cs = os.environ["X_API_SECRET"]
    at = os.environ["X_ACCESS_TOKEN"]
    ats = os.environ["X_ACCESS_TOKEN_SECRET"]
    client = tweepy.Client(
        consumer_key=ck, consumer_secret=cs,
        access_token=at, access_token_secret=ats,
    )

    try:
        resp = client.create_tweet(text=item["text"])  # テキストのみ・media なし
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
    posted.append({"at": now, "id": item["id"], "lang": item["lang"], "tweet_id": str(tweet_id)})
    state["posted"] = posted[-200:]
    save_json(STATE, state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
