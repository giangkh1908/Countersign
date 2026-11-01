"""Tải các luật trong selection.json từ vbpl.vn và tách theo Điều.

    uv run --with beautifulsoup4 python -m data.vbpl [--out data/raw/vbpl]

HTML đã tải thì dùng lại (không tải lại). Nghỉ 3 s giữa các request. Đầu ra: <slug>.html,
<slug>.json (danh sách Điều) và manifest.json (sha256 của JSON Điều, ổn định hơn HTML vì trang động).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.request
from pathlib import Path

from .extract import articles

HERE = Path(__file__).parent
USER_AGENT = "Mozilla/5.0 (academic research; AI_EXAMPLE)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/raw/vbpl")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    manifest, failed = [], 0
    for item in json.loads((HERE / "selection.json").read_text(encoding="utf-8")):
        slug = item["doc_num"].replace("/", "-").lower()
        html_path = out / f"{slug}.html"
        if not html_path.exists():
            req = urllib.request.Request(item["url"], headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=60) as resp:
                html_path.write_bytes(resp.read())
            time.sleep(3)
        arts = articles(html_path.read_text(encoding="utf-8"))
        body = json.dumps(arts, ensure_ascii=False, indent=1)
        (out / f"{slug}.json").write_text(body, encoding="utf-8")
        if not arts:
            failed += 1
        manifest.append(
            {
                **item,
                "articles": len(arts),
                "chars": sum(len(" ".join(a["paragraphs"])) for a in arts),
                "articles_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            }
        )
        print(f"{item['group']:8} {item['doc_num']:15} {len(arts):4} điều")
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"tổng {len(manifest)} văn bản, {sum(m['articles'] for m in manifest)} điều")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
