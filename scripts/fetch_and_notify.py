#!/usr/bin/env python3
"""
Fetch nsdk.top fund valuation data and send to Feishu.

Environment variables:
  FEISHU_APP_ID     - Feishu app ID
  FEISHU_APP_SECRET - Feishu app secret
  FEISHU_OPEN_ID    - Target user open_id
  NSDK_API_MODE     - "pre-market" or "last-intraday"
  NSDK_TITLE        - Override message title
"""

import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta


NSDK_API = "https://nsdk.top/api/pre-market"
NSDK_API_LAST = "https://nsdk.top/api/last-intraday"
FEISHU_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
FEISHU_MSG_URL = "https://open.feishu.cn/open-apis/im/v1/messages"

# Colors: red for up (A股惯例), green for down
COLOR_RED = "red"
COLOR_GREEN = "green"
COLOR_DEFAULT = "black"

# Arrows matching colors
ARROW_UP = "🔴"    # red circle = 涨
ARROW_DOWN = "🟢"  # green circle = 跌


def fetch_nsdk_data():
    """Fetch valuation data from nsdk.top API."""
    mode = os.environ.get("NSDK_API_MODE", "pre-market")
    if mode == "last-intraday":
        endpoints = [NSDK_API_LAST, NSDK_API]
    else:
        endpoints = [NSDK_API, NSDK_API_LAST]
    for endpoint in endpoints:
        try:
            req = urllib.request.Request(endpoint, headers={"User-Agent": "nsdk-feishu-action/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
                if data.get("funds"):
                    return data
        except Exception:
            continue
    return None


def change_color(pct):
    """Return color based on change percent: red for up, green for down (A股惯例)."""
    if pct > 0:
        return COLOR_RED
    elif pct < 0:
        return COLOR_GREEN
    return COLOR_DEFAULT


def change_arrow(pct):
    """Return arrow emoji matching the color convention."""
    if pct > 0:
        return ARROW_UP
    elif pct < 0:
        return ARROW_DOWN
    return ""


def build_post_content(data):
    """Build Feishu post (rich text) content with colored change values."""
    mode = data.get("mode", "")
    ts = data.get("timestamp", "")
    desc = data.get("description", "")

    mode_label = {"intraday": "盘中", "pre-market": "盘前", "last-intraday": "昨收"}.get(mode, mode)
    title = os.environ.get("NSDK_TITLE", "")
    if not title:
        title = f"纳指基金估值-{mode_label}"

    # Post content: list of content lines, each line is a list of elements
    content = []

    # Title line
    content.append([
        {"tag": "text", "text": f"📊 {title}"},
    ])

    # Timestamp
    content.append([
        {"tag": "text", "text": f"⏰ {ts}"},
    ])

    # Blank line
    content.append([{"tag": "text", "text": ""}])

    # Indexes section
    indexes = data.get("indexes", [])
    if indexes:
        content.append([
            {"tag": "text", "text": "📈 指数行情:"},
        ])
        for idx in indexes:
            label = idx.get("label", "")
            pct = idx.get("changePercent", 0)
            val = idx.get("value", 0)
            color = change_color(pct)
            arrow = change_arrow(pct)

            # Only show main indexes (skip futures and composite)
            if "期货" in label or "综合" in label:
                continue

            if "美元" in label:
                val_str = f"{val}"
            else:
                val_str = f"{val:,.2f}"

            pct_str = f"{pct:+.2f}%"
            line_text = f"  {label}: {val_str} ("
            line_elements = [
                {"tag": "text", "text": line_text},
                {"tag": "text", "text": f"{arrow}{pct_str})", "style": [color]},
            ]
            content.append(line_elements)

        content.append([{"tag": "text", "text": ""}])

    # Funds section
    funds = data.get("funds", [])
    if funds:
        content.append([
            {"tag": "text", "text": "💰 基金估值:"},
        ])
        for i, fund in enumerate(funds, 1):
            name = fund.get("name", "")
            change = fund.get("estimatedChange", 0)
            is_est = fund.get("isEstimatedValuation", False)
            est_tag = "测" if is_est else ""
            color = change_color(change)
            arrow = change_arrow(change)

            change_str = f"{change:+.2f}%{est_tag}"
            line_elements = [
                {"tag": "text", "text": f"  {i:>2}. {name} "},
                {"tag": "text", "text": f"{arrow}{change_str}", "style": [color]},
            ]
            content.append(line_elements)

    content.append([{"tag": "text", "text": ""}])

    # Description
    desc_short = desc[:50] + "..." if len(desc) > 50 else desc
    content.append([
        {"tag": "text", "text": f"📅 {desc_short}"},
    ])
    content.append([
        {"tag": "a", "text": "🔗 nsdk.top", "href": "https://nsdk.top/"},
    ])

    return content


def format_message(data):
    """Build the full Feishu post message body."""
    title_env = os.environ.get("NSDK_TITLE", "")
    if not title_env:
        mode = data.get("mode", "")
        mode_label = {"intraday": "盘中", "pre-market": "盘前", "last-intraday": "昨收"}.get(mode, mode)
        title_env = f"纳指基金估值-{mode_label}"

    content = build_post_content(data)

    post_body = {
        "zh_cn": {
            "title": title_env,
            "content": content,
        }
    }
    return post_body


def get_feishu_token(app_id, app_secret):
    """Get Feishu tenant access token."""
    body = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode()
    req = urllib.request.Request(
        FEISHU_TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        result = json.loads(resp.read())
    token = result.get("tenant_access_token")
    if not token:
        print(f"Failed to get token: {result}", file=sys.stderr)
        sys.exit(1)
    return token


def send_feishu_post(token, open_id, post_body):
    """Send post (rich text) message to Feishu user."""
    body = json.dumps({
        "receive_id": open_id,
        "msg_type": "post",
        "content": json.dumps(post_body),
    }).encode()
    req = urllib.request.Request(
        FEISHU_MSG_URL + "?receive_id_type=open_id",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        result = json.loads(resp.read())
    if result.get("code") != 0:
        print(f"Failed to send message: {result}", file=sys.stderr)
        sys.exit(1)
    print("Message sent successfully!")


def main():
    app_id = os.environ.get("FEISHU_APP_ID")
    app_secret = os.environ.get("FEISHU_APP_SECRET")
    open_id = os.environ.get("FEISHU_OPEN_ID")

    if not all([app_id, app_secret, open_id]):
        print("Missing required env vars: FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_OPEN_ID", file=sys.stderr)
        sys.exit(1)

    # Fetch data
    print("Fetching nsdk.top data...")
    data = fetch_nsdk_data()
    if not data:
        print("Failed to fetch data from nsdk.top", file=sys.stderr)
        sys.exit(1)

    print(f"Got {len(data.get('funds', []))} funds, mode={data.get('mode')}")

    # Format post message
    post_body = format_message(data)
    print(f"Post body: {json.dumps(post_body, ensure_ascii=False)[:200]}")

    # Send to Feishu
    print("Getting Feishu token...")
    token = get_feishu_token(app_id, app_secret)

    print("Sending post message to Feishu...")
    send_feishu_post(token, open_id, post_body)


if __name__ == "__main__":
    main()
