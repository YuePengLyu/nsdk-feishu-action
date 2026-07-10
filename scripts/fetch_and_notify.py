#!/usr/bin/env python3
"""
Fetch nsdk.top fund valuation data and send to Feishu.

Environment variables:
  FEISHU_APP_ID     - Feishu app ID
  FEISHU_APP_SECRET - Feishu app secret
  FEISHU_OPEN_ID    - Target user open_id
"""

import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta


NSDK_API = "https://nsdk.top/api/pre-market"
FEISHU_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
FEISHU_MSG_URL = "https://open.feishu.cn/open-apis/im/v1/messages"


def fetch_nsdk_data():
    """Fetch valuation data from nsdk.top API."""
    # Try pre-market first, then last-intraday as fallback
    for endpoint in [NSDK_API, "https://nsdk.top/api/last-intraday"]:
        try:
            req = urllib.request.Request(endpoint, headers={"User-Agent": "nsdk-feishu-action/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
                if data.get("funds"):
                    return data
        except Exception:
            continue
    return None


def format_message(data):
    """Format nsdk data into a readable text message."""
    tz_cn = timezone(timedelta(hours=8))
    now = datetime.now(tz_cn).strftime("%Y-%m-%d %H:%M")

    mode = data.get("mode", "")
    ts = data.get("timestamp", "")
    desc = data.get("description", "")

    # Mode label
    mode_label = {"intraday": "盘中", "pre-market": "盘前", "last-intraday": "昨收基准"}.get(mode, mode)

    lines = [f"📊 纳指基金估值 | {mode_label}", f"⏰ {ts}", ""]

    # Indexes
    indexes = data.get("indexes", [])
    if indexes:
        lines.append("📈 指数行情:")
        for idx in indexes:
            label = idx.get("label", "")
            pct = idx.get("changePercent", 0)
            val = idx.get("value", 0)
            arrow = "🟢" if pct >= 0 else "🔴"
            # Only show main indexes
            if "美元" in label:
                lines.append(f"  {label}: {val} ({arrow}{pct:+.2f}%)")
            elif "期货" not in label and "综合" not in label:
                lines.append(f"  {label}: {val:,.2f} ({arrow}{pct:+.2f}%)")
        lines.append("")

    # Funds
    funds = data.get("funds", [])
    if funds:
        lines.append("💰 基金估值:")
        for i, fund in enumerate(funds, 1):
            name = fund.get("name", "")
            change = fund.get("estimatedChange", 0)
            label = fund.get("label", "")
            is_est = fund.get("isEstimatedValuation", False)
            est_tag = "测" if is_est else ""
            arrow = "🔺" if change >= 0 else "🔻"
            lines.append(f"  {i:>2}. {name} {arrow}{change:+.2f}%{est_tag}")

    lines.append("")
    lines.append(f"📅 {desc[:50]}..." if len(desc) > 50 else f"📅 {desc}")
    lines.append(f"🔗 https://nsdk.top/")

    return "\n".join(lines)


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


def send_feishu_message(token, open_id, text):
    """Send text message to Feishu user."""
    body = json.dumps({
        "receive_id": open_id,
        "msg_type": "text",
        "content": json.dumps({"text": text}),
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

    # Format message
    text = format_message(data)
    print(f"Message length: {len(text)} chars")

    # Send to Feishu
    print("Getting Feishu token...")
    token = get_feishu_token(app_id, app_secret)

    print("Sending message to Feishu...")
    send_feishu_message(token, open_id, text)


if __name__ == "__main__":
    main()
