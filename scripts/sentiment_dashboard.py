#!/usr/bin/env python3
"""
Nasdaq 100 Sentiment Dashboard - Fetch VXN, PE, FGI and send to Feishu.

Environment variables:
  FEISHU_APP_ID     - Feishu app ID
  FEISHU_APP_SECRET - Feishu app secret
  FEISHU_OPEN_ID    - Target user open_id
"""

import json
import os
import re
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta


FEISHU_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
FEISHU_MSG_URL = "https://open.feishu.cn/open-apis/im/v1/messages"

# Data source URLs
CNBC_QUOTE_URL = "https://quote.cnbc.com/quote-html-webservice/quote.htm?symbols={symbol}&requestMethod=it&noform=1"
FGI_API_URL = "https://api.alternative.me/fng/?limit=1"
FRED_VXN_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=VXNCLS&cosd={date}"


def fetch_vxn():
    """Fetch VXN from CNBC XML API, fallback to FRED CSV."""
    # Primary: CNBC
    try:
        req = urllib.request.Request(
            CNBC_QUOTE_URL.format(symbol="VXN"),
            headers={"User-Agent": "nsdk-sentiment/1.0"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            text = resp.read().decode()
        last_match = re.search(r"<last>([\d.]+)</last>", text)
        if last_match:
            return float(last_match.group(1)), "CNBC"
    except Exception:
        pass

    # Fallback: FRED CSV
    try:
        from datetime import date, timedelta
        start = (date.today() - timedelta(days=10)).strftime("%Y-%m-%d")
        req = urllib.request.Request(
            FRED_VXN_CSV_URL.format(date=start),
            headers={"User-Agent": "nsdk-sentiment/1.0"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            lines = resp.read().decode().strip().split("\n")
        for line in reversed(lines):
            parts = line.split(",")
            if len(parts) >= 2 and parts[1].strip() not in ("", "."):
                return float(parts[1].strip()), f"FRED ({parts[0]})"
    except Exception:
        pass

    return None, None


def fetch_pe():
    """Fetch PE ratio. Try multpl.com (S&P 500 PE), fallback to GuruFocus (NDX PE)."""
    # Primary: multpl.com S&P 500 PE Ratio
    try:
        req = urllib.request.Request(
            "https://www.multpl.com/s-p-500-pe-ratio",
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            text = resp.read().decode()
        # Pattern: "Current S&P 500 PE Ratio is XX.XX"
        match = re.search(r"Current S&P 500 PE Ratio is ([\d.]+)", text, re.IGNORECASE)
        if match:
            return float(match.group(1)), "multpl"
    except Exception:
        pass

    # Fallback: GuruFocus NDX PE
    try:
        req = urllib.request.Request(
            "https://www.gurufocus.com/term/PE-ratio/NDX/Nasdaq-100-PE-Ratio",
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            },
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            text = resp.read().decode()
        for pattern in [
            r'"peRatio"\s*:\s*"([\d.]+)"',
            r'PE\s+Ratio[^<]{0,200}?<strong[^>]*>\s*([\d.]+)\s*</strong>',
            r'PE\s+Ratio[^<]{0,200}?<span[^>]*>\s*([\d.]+)\s*</span>',
            r'Nasdaq 100 PE Ratio[^<]{0,200}?([\d.]+)',
        ]:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                return float(match.group(1)), "GuruFocus"
    except Exception:
        pass

    return None, None


def fetch_fgi():
    """Fetch Fear & Greed Index from alternative.me."""
    try:
        req = urllib.request.Request(FGI_API_URL)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        return int(data["data"][0]["value"]), data["data"][0]["value_classification"]
    except Exception:
        return None, None


def compute_score(vxn, pe, fgi):
    """Compute composite sentiment score (0-100, higher = more overvalued)."""
    # PE Score
    if pe is not None:
        if pe < 20:
            pe_score = 100 - (pe - 10) * 2.5
        elif pe <= 28:
            pe_score = 80 - (pe - 20) * 5
        elif pe <= 35:
            pe_score = 40 - (pe - 28) * 5.7
        elif pe <= 40:
            pe_score = 10 - (pe - 35) * 2
        else:
            pe_score = 0
        pe_score = max(0, min(100, pe_score))
    else:
        pe_score = 50  # neutral if unavailable

    # FGI Score (low FGI = fear = buy signal = high score)
    if fgi is not None:
        if fgi < 25:
            fgi_score = 90 + (25 - fgi) * 0.4
        elif fgi <= 40:
            fgi_score = 70 + (40 - fgi) * 1.3
        elif fgi <= 55:
            fgi_score = 50 + (55 - fgi) * 1.3
        elif fgi <= 75:
            fgi_score = 30 + (75 - fgi) * 1
        else:
            fgi_score = 10 + (100 - fgi) * 0.67
        fgi_score = max(0, min(100, fgi_score))
    else:
        fgi_score = 50

    # VXN Score (high VXN = fear = buy signal = high score)
    if vxn is not None:
        if vxn > 35:
            vxn_score = 95
        elif vxn > 28:
            vxn_score = 70 + (35 - vxn) * 3.57
        elif vxn > 22:
            vxn_score = 50 + (28 - vxn) * 3.33
        elif vxn > 18:
            vxn_score = 30 + (22 - vxn) * 5
        else:
            vxn_score = 10 + (18 - vxn) * 5
        vxn_score = max(0, min(100, vxn_score))
    else:
        vxn_score = 50

    # Composite: weighted average
    total = vxn_score * 0.30 + pe_score * 0.35 + fgi_score * 0.35
    return total, vxn_score, pe_score, fgi_score


def get_status_and_multiple(total):
    """Determine market status and DCA multiple from composite score."""
    if total < 20:
        return "极度低估 · 重仓", "3.0x"
    elif total < 35:
        return "显著低估 · 倍投", "2.0x"
    elif total < 50:
        return "合理偏低 · 加仓", "1.5x"
    elif total < 65:
        return "常规定投 · 维持", "1.0x"
    elif total < 75:
        return "合理偏高 · 减量", "0.8x"
    elif total < 85:
        return "高估 · 低量", "0.5x"
    else:
        return "极度高估 · 暂停", "0x"


def get_vxn_status(vxn):
    if vxn is None:
        return "N/A"
    if vxn > 35:
        return "极度恐慌"
    elif vxn > 28:
        return "恐慌偏高"
    elif vxn > 22:
        return "温和波动"
    elif vxn > 18:
        return "偏低偏稳"
    else:
        return "极度平静"


def get_pe_status(pe):
    if pe is None:
        return "N/A"
    if pe > 35:
        return "显著高估"
    elif pe > 28:
        return "偏高"
    elif pe > 22:
        return "合理"
    else:
        return "低估"


def get_fgi_status(fgi):
    if fgi is None:
        return "N/A"
    if fgi < 25:
        return "极度恐惧"
    elif fgi < 40:
        return "恐惧"
    elif fgi < 55:
        return "中性"
    elif fgi < 75:
        return "贪婪"
    else:
        return "极度贪婪"


def format_message(vxn, vxn_src, pe, pe_src, fgi, fgi_class):
    """Format sentiment dashboard into text message."""
    tz_cn = timezone(timedelta(hours=8))
    today = datetime.now(tz_cn).strftime("%Y-%m-%d")

    total, vxn_s, pe_s, fgi_s = compute_score(vxn, pe, fgi)
    status, multiple = get_status_and_multiple(total)

    lines = [
        f"📊 纳指情绪仪表盘 | {today}",
        "━━━━━━━━━━━━━━━━━",
        f"📉 VXN恐慌指数: {vxn:.2f} ({get_vxn_status(vxn)})" if vxn else "📉 VXN恐慌指数: N/A",
        f"💰 PE市盈率: {pe:.2f} ({get_pe_status(pe)}) [{pe_src}]" if pe else "💰 PE市盈率: N/A",
        f"😰 FGI恐惧贪婪: {fgi} ({get_fgi_status(fgi)})" if fgi else "😰 FGI恐惧贪婪: N/A",
        "━━━━━━━━━━━━━━━━━",
        f"综合评分: {total:.1f}/100",
        f"市场状态: {status}",
        f"建议定投倍数: {multiple}",
    ]

    # Add source info
    sources = []
    if vxn_src:
        sources.append(f"VXN={vxn_src}")
    if pe_src:
        sources.append(f"PE={pe_src}")
    if sources:
        lines.append(f"数据来源: {', '.join(sources)}")

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
    print("Fetching VXN...")
    vxn, vxn_src = fetch_vxn()
    print(f"  VXN: {vxn} ({vxn_src})")

    print("Fetching PE...")
    pe, pe_src = fetch_pe()
    print(f"  PE: {pe} ({pe_src})")

    print("Fetching FGI...")
    fgi, fgi_class = fetch_fgi()
    print(f"  FGI: {fgi} ({fgi_class})")

    if all(v is None for v in [vxn, pe, fgi]):
        print("All data sources failed!", file=sys.stderr)
        sys.exit(1)

    # Format message
    text = format_message(vxn, vxn_src, pe, pe_src, fgi, fgi_class)
    print(f"Message:\n{text}\n")

    # Send to Feishu
    print("Getting Feishu token...")
    token = get_feishu_token(app_id, app_secret)

    print("Sending message to Feishu...")
    send_feishu_message(token, open_id, text)


if __name__ == "__main__":
    main()
