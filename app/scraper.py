# scraper.py
import os
from typing import Dict, List, Tuple
import requests

def fetch_recent_student_intros(
    bearer: str,
    user_id: str,
    max_results: int,
    prefix: str,
) -> List[Dict]:
    url = f"https://api.x.com/2/users/{user_id}/tweets"
    params = {
        "max_results": str(min(max(max_results, 5), 100)),
        "exclude": "replies",
        "tweet.fields": "created_at",
        "expansions": "attachments.media_keys",
        "media.fields": "url,preview_image_url,type",
    }
    r = requests.get(url, headers={"Authorization": f"Bearer {bearer}"}, params=params, timeout=30)
    r.raise_for_status()
    j = r.json()

    media_map: Dict[str, str] = {}
    for m in (j.get("includes", {}) or {}).get("media", []) or []:
        mk = m.get("media_key")
        if mk:
            media_map[mk] = m.get("url") or m.get("preview_image_url") or ""

    tweets: List[Dict] = []
    for t in j.get("data", []) or []:
        text = (t.get("text") or "").strip()
        if not text.startswith(prefix):
            continue

        mk_list = ((t.get("attachments") or {}).get("media_keys") or [])
        media_urls = [media_map.get(mk, "") for mk in mk_list]
        media_urls = [u for u in media_urls if u]

        tweets.append({
            "id": t["id"],
            "created_at": t.get("created_at"),
            "text": text,
            "media_urls": media_urls,
        })

    # oldest-first
    return list(reversed(tweets))

def download_images(urls: List[str]) -> List[Tuple[str, bytes]]:
    files: List[Tuple[str, bytes]] = []
    for i, u in enumerate(urls):
        try:
            r = requests.get(u, timeout=10)  # 👈 reduced from 60
            r.raise_for_status()
            ext = ".png" if "image/png" in (r.headers.get("Content-Type") or "") else ".jpg"
            files.append((f"image_{i+1}{ext}", r.content))
        except Exception as e:
            print(f"[scraper] Failed to download image {u}: {e}")
            continue  # 👈 skip failed images instead of crashing
    return files

def fetch_gacha_notices(
    bearer: str,
    user_id: str,
    max_results: int,
    prefixes: list[str],
) -> List[Dict]:
    url = f"https://api.x.com/2/users/{user_id}/tweets"
    params = {
        "max_results": str(min(max(max_results, 5), 100)),
        "exclude": "replies",
        "tweet.fields": "created_at",
        "expansions": "attachments.media_keys",
        "media.fields": "url,preview_image_url,type",
    }
    r = requests.get(url, headers={"Authorization": f"Bearer {bearer}"}, params=params, timeout=30)
    r.raise_for_status()
    j = r.json()

    media_map: Dict[str, str] = {}
    for m in (j.get("includes", {}) or {}).get("media", []) or []:
        mk = m.get("media_key")
        if mk:
            media_map[mk] = m.get("url") or m.get("preview_image_url") or ""

    tweets: List[Dict] = []
    for t in j.get("data", []) or []:
        text = (t.get("text") or "").strip()
        if not any(text.startswith(p) for p in prefixes):
            continue

        mk_list = ((t.get("attachments") or {}).get("media_keys") or [])
        media_urls = [media_map.get(mk, "") for mk in mk_list]
        media_urls = [u for u in media_urls if u]

        tweets.append({
            "id": t["id"],
            "created_at": t.get("created_at"),
            "text": text,
            "media_urls": media_urls,
        })

    return list(reversed(tweets))  # oldest-first