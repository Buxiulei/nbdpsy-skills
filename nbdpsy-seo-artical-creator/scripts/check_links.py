#!/usr/bin/env python3
"""外链可达性初筛：404/5xx/网络失败=死链(exit 1)；401/403/429=疑似反爬仅告警。对齐已退役的 shell 版同名脚本。"""
import argparse, json, re, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import requests

UA = {"User-Agent": "Mozilla/5.0 (compatible; nbdpsy-linkcheck/1.0)"}

def extract_urls(text: str):
    urls = re.findall(r"https?://[^\s)\]>\"'，。；]+", text)
    seen, out = set(), []
    for u in urls:
        u = u.rstrip(".,;")
        if u not in seen:
            seen.add(u); out.append(u)
    return out

def probe(url: str, timeout: int):
    try:
        r = requests.head(url, timeout=timeout, headers=UA, allow_redirects=True)
        if r.status_code in (405, 501):
            r_get = requests.get(url, timeout=timeout, headers=UA, stream=True)
            try:
                return r_get.status_code
            finally:
                r_get.close()
        return r.status_code
    except requests.RequestException:
        return None

def classify(status):
    if status is None or status == 404 or (status and status >= 500):
        return "dead"
    if status in (401, 403, 429):
        return "suspect"
    return "ok"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file"); ap.add_argument("--timeout", type=int, default=10)
    a = ap.parse_args()
    try:
        text = Path(a.file).read_text(encoding="utf-8")
    except (FileNotFoundError, IOError, OSError) as e:
        print(json.dumps({"error": f"文件不存在: {a.file}"}, ensure_ascii=False))
        sys.stderr.write(f"Error: {e}\n")
        sys.exit(2)
    urls = extract_urls(text)
    dead, suspect = [], []
    with ThreadPoolExecutor(max_workers=8) as ex:
        for url, status in zip(urls, ex.map(lambda u: probe(u, a.timeout), urls)):
            c = classify(status)
            print(f"  {c:7s} {status} {url}", file=sys.stderr)
            if c == "dead":
                dead.append({"url": url, "status": status})
            elif c == "suspect":
                suspect.append({"url": url, "status": status})
    ok = not dead
    print(json.dumps({"total": len(urls), "dead": dead, "suspect": suspect, "ok": ok}, ensure_ascii=False))
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
