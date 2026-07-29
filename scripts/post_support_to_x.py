#!/usr/bin/env python3
"""post_support_to_x.py

PURPOSE
-------
目的：熊本地震（令和8年）の災害支援テキストを、X（@waveblasttaiyo）へ自動投稿する。
背景：ここらプロモ用のリール投稿（post_to_x.py / post-jp・post-en ワークフロー）は一時停止し、
      同じリポ・同じXアカウント・同じ認証情報を再利用して、急性期の「役立つ情報」を1日8回配信する。
      旅リールは投稿しない。動画を使わないテキスト専用（画像・被災画像は一切添付しない）。
使い方：
    python scripts/post_support_to_x.py            # キューの次の1件を投稿
    python scripts/post_support_to_x.py --dry-run  # 投稿せず、次に出る本文だけ表示

必要な環境変数（GitHub Secrets に登録済み。@waveblasttaiyo で発行したもの）:
    X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET

データ:
    queue/support_queue.json : 投稿本文のキュー（day, time_jst, category, text）。順番に投稿する。
    queue/support_state.json : {"support_index": n, "posted": [...]} 次に出す位置と投稿履歴。

処理の流れ:
    1. support_queue.json を読み、support_state.json のインデックスで次の1件を選ぶ
    2. テキストのみでツイート作成（media なし）
    3. インデックスを1つ進め、履歴を追記（呼び出し側 workflow が commit）
    4. キュー末尾まで行ったら、それ以上は投稿しない（安全のため折り返さない）
       ※今週分を配信し切ったら止まる設計。延長したいときは support_queue.json に追記する。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import tweepy

ROOT = Path(__file__).resolve().parent.parent
QUEUE = ROOT / "queue" / "support_queue.json"
STATE = ROOT / "queue" / "support_state.json"
JST = timezone(timedelta(hours=9))


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def pick():
    """キューの次の1件と位置を返す。末尾を超えたら None（折り返さない）。"""
    queue = load_json(QUEUE)
    state = load_json(STATE) if STATE.exists() else {"support_index": 0, "posted": []}
    idx = int(state.get("support_index", 0))
    if idx >= len(queue):
        return None, idx, len(queue), state
    return queue[idx], idx, len(queue), state


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    item, idx, total, state = pick()
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M")

    if item is None:
        print(f"[{now} JST] キューを配信し切りました（{total}件）。追加投稿はしません。")
        return 0

    print(f"[{now} JST] {idx + 1}/{total} day={item['day']} slot={item['time_jst']} cat={item['category']}")
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

    resp = client.create_tweet(text=item["text"])  # テキストのみ・media なし
    tweet_id = resp.data.get("id") if resp and resp.data else None
    print(f"posted: https://x.com/waveblasttaiyo/status/{tweet_id}")

    # 位置を進めて履歴を残す（直近200件だけ保持）
    state["support_index"] = idx + 1
    posted = state.get("posted", [])
    posted.append({
        "at": now, "day": item["day"], "slot": item["time_jst"],
        "category": item["category"], "tweet_id": str(tweet_id),
    })
    state["posted"] = posted[-200:]
    save_json(STATE, state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
