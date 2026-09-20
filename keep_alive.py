"""
Ping the health endpoint so a free Render web service does not spin down
after 15 minutes of idle time.
"""

import os
import sys
import urllib.error
import urllib.request

url = os.environ.get("KEEP_ALIVE_URL") or os.environ.get("RENDER_EXTERNAL_URL")
if not url:
    print("KEEP_ALIVE_URL is not set", file=sys.stderr)
    sys.exit(1)

if not url.startswith("http"):
    url = f"https://{url}"

health_url = url.rstrip("/") + "/"

try:
    with urllib.request.urlopen(health_url, timeout=60) as resp:
        if resp.status != 200:
            print(f"Keep-alive failed: HTTP {resp.status}", file=sys.stderr)
            sys.exit(1)
        print(f"Keep-alive ok: {health_url}")
except urllib.error.URLError as exc:
    print(f"Keep-alive failed: {exc}", file=sys.stderr)
    sys.exit(1)
