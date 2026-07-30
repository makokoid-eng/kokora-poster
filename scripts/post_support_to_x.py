#!/usr/bin/env python3
"""post_support_to_x.py

PURPOSE
-------
目的：熊本地震（令和8年）の災害支援テキストを、X（@waveblasttaiyo）へ自動投稿する。
      投稿内容を「JSTの時間帯（band）」で出し分ける。
背景：ここらプロモ用のリール投稿は停止し、同じリポ・同じXアカウント・同じ認証を再利用。
      夜〜早朝は「車中泊OK/ペット同伴可の避難所・夜間も使える充電・夜間避難情報」を優先、
      日中は「給水・炊き出し・GS営業・営業再開店」を優先する。動画なしのテキストのみ。
使い方：
    python scripts/post_support_to_x.py            # 現在の時間帯に合った次の1件を投稿
    python scripts/post_support_to_x.py --dry-run  # 投稿せず、選ばれる本文だけ表示

必要な環境変数（GitHub Secrets）:
    X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET

データ:
    queue/support_queue.json : 各投稿に "band"（"day"|"night"|"any"）を付与
    queue/support_state.json : {"day_index":n, "night_index":m, "posted":[...]}

時間帯（band）判定（JST）:
    night = 18:00〜翌06:59（夜〜早朝） / day = 07:00〜17:59（日中）
    ※現行cronは 08〜22時の8枠。実際の夜枠は 18/20/22時、日中枠は 08/10/12/14/16時。

処理の流れ:
    1. 現在のJST時刻から band を決定
    2. queue から band 一致（＝その band か "any"）の候補だけを抽出
    3. state の band別インデックスで候補内の次の1件を選ぶ（末尾まで行ったら先頭へ巡回）
    4. テキストのみでツイート作成（media なし）
    5. その band のインデックスを1つ進め、履歴を追記（呼び出し側 workflow が commit）
       ※災害が続く間まわし続けられるよう、band内で巡回する（掲載中の常設情報が中心のため）
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


def current_band(now: datetime | None = None) -> str:
    """JSTの時刻から band を返す。night=18:00〜翌06:59 / day=07:00〜17:59。"""
    h = (now or datetime.now(JST)).hour
    return "night" if (h >= 18 or h < 7) else "day"


def pick():
    """現在の band に合う候補（band一致 or 'any'）から、band別インデックスで次の1件を返す。"""
    queue = load_json(QUEUE)
    band = current_band()
    cands = [it for it in queue if it.get("band", "any") in (band, "any")]
    if not cands:  # 保険：該当なしなら全件から
        cands = queue
    state = load_json(STATE) if STATE.exists() else {}
    key = f"{band}_index"
    idx = int(state.get(key, 0)) % len(cands)
    return cands[idx], band, key, idx, len(cands), state


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    item, band, key, idx, total, state = pick()
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M")

    print(f"[{now} JST] band={band} {idx + 1}/{total}(band内) cat={item.get('category')}")
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
        print(f"::error::投稿失敗（support）: {msg}{hint}")
        raise
    tweet_id = resp.data.get("id") if resp and resp.data else None
    print(f"posted: https://x.com/waveblasttaiyo/status/{tweet_id}")

    # band内インデックスを進めて履歴を残す（直近200件だけ保持）
    state[key] = (idx + 1) % total
    posted = state.get("posted", [])
    posted.append({
        "at": now, "band": band, "category": item.get("category"),
        "tweet_id": str(tweet_id),
    })
    state["posted"] = posted[-200:]
    save_json(STATE, state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
