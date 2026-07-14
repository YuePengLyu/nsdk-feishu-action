#!/usr/bin/env python3
"""
Fetch nsdk.top fund valuation data and send to Feishu via interactive card.

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


def colored(pct, text):
    """Wrap text with font color tag: red for up, green for down (A股惯例)."""
    if pct > 0:
        return f"<font color='red'>{text}</font>"
    elif pct < 0:
        return f"<font color='green'>{text}</font>"
    return text


def build_card(data):
    """Build Feishu interactive card (JSON 2.0) with colored change values."""
    mode = data.get("mode", "")
    ts = data.get("timestamp", "")
    desc = data.get("description", "")

    mode_label = {"intraday": "盘中", "pre-market": "盘前", "last-intraday": "昨收"}.get(mode, mode)
    title = os.environ.get("NSDK_TITLE", "")
    if not title:
        title = f"纳指基金估值-{mode_label}"

    elements = []

    # Timestamp + divider
    elements.append({"tag": "markdown", "content": f"⏰ {ts}"})

    # Indexes section
    indexes = data.get("indexes", [])
    if indexes:
        md_lines = ["📈 **指数行情:**"]
        for idx in indexes:
            label = idx.get("label", "")
            pct = idx.get("changePercent", 0)
            val = idx.get("value", 0)

            if "期货" in label or "综合" in label:
                continue

            if "美元" in label:
                val_str = f"{val}"
            else:
                val_str = f"{val:,.2f}"

            pct_str = f"{pct:+.2f}%"
            arrow = "🔴" if pct >= 0 else "🟢"
            colored_pct = colored(pct, f"{arrow}{pct_str}")
            md_lines.append(f"  {label}: {val_str} ({colored_pct})")
        elements.append({"tag": "markdown", "content": "\n".join(md_lines)})

    # Funds section — single markdown block with name + colored percentage
    funds = data.get("funds", [])
    if funds:
        md_lines = ["💰 **基金估值:**"]
        for i, fund in enumerate(funds, 1):
            name = fund.get("name", "")
            change = fund.get("estimatedChange", 0)
            is_est = fund.get("isEstimatedValuation", False)
            est_tag = "测" if is_est else ""
            change_str = f"{change:+.2f}%{est_tag}"
            colored_change = colored(change, change_str)
            md_lines.append(f"  {i:>2}. {name} {colored_change}")
        elements.append({"tag": "markdown", "content": "\n".join(md_lines)})

    # Description and link
    desc_short = desc[:50] + "..." if len(desc) > 50 else desc
    elements.append({"tag": "markdown", "content": f"📅 {desc_short}"})
    elements.append({"tag": "markdown", "content": "[🔗 nsdk.top](https://nsdk.top/)"})

    # Build card
    card = {
        "schema": "2.0",
        "header": {
            "title": {
                "tag": "plain_text",
                "content": title,
            },
            "template": "blue",
        },
        "body": {"elements": elements},
    }

    return card


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


def send_feishu_card(token, open_id, card):
    """Send interactive card message to Feishu user."""
    body = json.dumps({
        "receive_id": open_id,
        "msg_type": "interactive",
        "content": json.dumps(card),
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

    # Build card
    card = build_card(data)
    print(f"Card body: {json.dumps(card, ensure_ascii=False)[:200]}")

    # Send to Feishu
    print("Getting Feishu token...")
    token = get_feishu_token(app_id, app_secret)

    print("Sending interactive card to Feishu...")
    send_feishu_card(token, open_id, card)


if __name__ == "__main__":
    main()
