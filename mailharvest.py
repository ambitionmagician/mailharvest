#!/usr/bin/env python3
"""mailharvest: scan an inbox for opportunities and get a checklist.

Connects to a mailbox over IMAP (strictly read-only: the mailbox is
opened readonly and messages are fetched with BODY.PEEK, so nothing is
marked read or changed), scores messages against opportunity keyword
rules — publishers, podcasts, grants, speaking invitations, expert
networks, deadlines — and writes a Markdown report with one checklist
item per candidate. Optionally, an OpenAI-compatible chat endpoint can
classify each candidate (category, deadline, next action); without one,
sensible per-category default actions are used.

Configuration (environment variables):
    MAILHARVEST_HOST      IMAP server hostname (required)
    MAILHARVEST_USER      mailbox username (required)
    MAILHARVEST_PASSWORD  mailbox password / app password (required)
    MAILHARVEST_MAILBOX   mailbox to scan (default: INBOX)
    MAILHARVEST_PORT      IMAP SSL port (default: 993)
    MAILHARVEST_API_BASE / MAILHARVEST_API_KEY / MAILHARVEST_MODEL
                          optional classifier endpoint (all three to enable)
"""
import argparse
import email
import imaplib
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from email.header import decode_header
from email.utils import parsedate_to_datetime

KEYWORDS = {
    "publishing": ["manuscript", "submission", "call for papers", "journal",
                   "publisher", "publishing", "book proposal", "submit your",
                   "now accepting", "anthology", "magazine"],
    "podcast & media": ["podcast", "interview request", "radio", "documentary",
                        "media request", "be a guest", "our show", "youtube channel"],
    "grants & funding": ["grant", "fellowship", "funding opportunity", "award",
                         "application is open", "request for proposals", "rfp", "stipend"],
    "speaking": ["speaker", "keynote", "conference", "panel", "talk at",
                 "present at", "summit", "webinar"],
    "expert networks": ["expert network", "paid consultation", "advisory",
                        "consultation request", "your expertise", "expert call"],
    "deadlines": ["deadline", "due by", "closes on", "last chance", "final reminder",
                  "expires", "closing soon", "respond by"],
}

DEFAULT_ACTIONS = {
    "publishing": "Read the guidelines; if it fits your work, prepare a submission.",
    "podcast & media": "Reply and offer times if you want the appearance.",
    "grants & funding": "Check eligibility and the deadline; start the application early.",
    "speaking": "Reply to accept or decline; ask about format, audience, and expenses.",
    "expert networks": "Check the rate and topic fit; reply to join or pass.",
    "deadlines": "Act before the stated deadline or consciously let it lapse.",
}

MONTHS = ("January|February|March|April|May|June|July|August|September|"
          "October|November|December")
DATE_PATTERNS = [
    re.compile(rf"\b(?:{MONTHS})\s+\d{{1,2}},\s+\d{{4}}\b"),
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(rf"\b\d{{1,2}}\s+(?:{MONTHS})\s+\d{{4}}\b"),
]


def score_message(subject: str, body: str) -> dict:
    """Return {category: hit_count} for every category with at least one hit."""
    haystack = (subject + "\n" + body).lower()
    scores = {}
    for category, words in KEYWORDS.items():
        hits = sum(haystack.count(w) for w in words)
        if hits:
            scores[category] = hits
    return scores


def extract_deadline(text: str):
    """Return the first explicit calendar date found in text, else None."""
    for pattern in DATE_PATTERNS:
        m = pattern.search(text)
        if m:
            return m.group(0)
    return None


def decode_mime(value):
    if value is None:
        return ""
    parts = []
    for raw, charset in decode_header(value):
        if isinstance(raw, bytes):
            parts.append(raw.decode(charset or "utf-8", errors="replace"))
        else:
            parts.append(raw)
    return "".join(parts).strip()


def message_text(msg):
    """Best-effort plain-text body of an email.message.Message."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode(part.get_content_charset() or "utf-8",
                                          errors="replace")
        return ""
    payload = msg.get_payload(decode=True)
    if payload:
        return payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
    return str(msg.get_payload() or "")


def classify(subject, snippet, cfg):
    """Optional cloud classification; returns dict or None on any failure."""
    prompt = (
        "Classify this email as an opportunity. Reply with ONLY a JSON object: "
        '{"category": one of [publishing, "podcast & media", "grants & funding", '
        'speaking, "expert networks", deadlines, other], "deadline": a date string '
        'or null, "action": one short next step}.\n\n'
        f"Subject: {subject}\n\n{snippet}"
    )
    payload = {
        "model": cfg["model"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
    }
    req = urllib.request.Request(
        cfg["api_base"].rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {cfg['api_key']}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"].strip()
        content = content.strip("`")
        if content.startswith("json"):
            content = content[4:].strip()
        result = json.loads(content)
        if isinstance(result, dict) and "category" in result:
            return result
    except Exception:
        return None
    return None


def fetch_candidates(cfg, days, limit):
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%d-%b-%Y")
    conn = imaplib.IMAP4_SSL(cfg["host"], cfg["port"])
    try:
        conn.login(cfg["user"], cfg["password"])
        typ, _ = conn.select(cfg["mailbox"], readonly=True)
        if typ != "OK":
            raise RuntimeError(f"could not open mailbox {cfg['mailbox']}")
        typ, data = conn.search(None, f'SINCE "{since}"')
        if typ != "OK":
            raise RuntimeError("IMAP search failed")
        ids = data[0].split()
        ids = list(reversed(ids))[:limit]  # newest first
        print(f"scanning {len(ids)} message(s) from the last {days} day(s)...")
        candidates = []
        for i, mid in enumerate(ids, 1):
            typ, fetched = conn.fetch(mid, "(BODY.PEEK[])")
            if typ != "OK" or not fetched or not isinstance(fetched[0], tuple):
                continue
            msg = email.message_from_bytes(fetched[0][1])
            subject = decode_mime(msg.get("Subject"))
            sender = decode_mime(msg.get("From"))
            body = message_text(msg)[:4000]
            scores = score_message(subject, body)
            if not scores:
                continue
            date_str = ""
            try:
                dt = parsedate_to_datetime(msg.get("Date"))
                if dt:
                    date_str = dt.strftime("%b %d, %Y")
            except (TypeError, ValueError):
                pass
            snippet = " ".join(body.split())[:200]
            candidates.append({
                "subject": subject or "(no subject)",
                "from": sender,
                "date": date_str,
                "scores": scores,
                "deadline": extract_deadline(subject + " " + body),
                "snippet": snippet,
                "body": body,
            })
            if i % 50 == 0:
                print(f"  ...{i}/{len(ids)} scanned, {len(candidates)} candidates so far")
        return candidates
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def write_report(candidates, out_path, days, classifier_cfg):
    by_category = {}
    for cand in candidates:
        category = max(cand["scores"], key=cand["scores"].get)
        action = DEFAULT_ACTIONS.get(category, "Review and decide.")
        deadline = cand["deadline"]
        if classifier_cfg:
            result = classify(cand["subject"], cand["snippet"], classifier_cfg)
            if result:
                category = str(result.get("category") or category)
                action = str(result.get("action") or action)
                deadline = result.get("deadline") or deadline
        cand["category"] = category
        cand["action"] = action
        cand["deadline"] = deadline
        by_category.setdefault(category, []).append(cand)

    lines = [
        f"# Opportunity Harvest — {datetime.now().strftime('%B %d, %Y')}",
        "",
        f"Scanned the last {days} day(s); {len(candidates)} candidate(s) "
        f"across {len(by_category)} categor(ies).",
        "",
    ]
    for category in sorted(by_category):
        lines.append(f"## {category.title()}")
        lines.append("")
        for cand in by_category[category]:
            lines.append(f"- [ ] **{cand['subject']}** — {cand['from']}"
                         + (f", {cand['date']}" if cand["date"] else ""))
            detail = f"  Action: {cand['action']}"
            if cand["deadline"]:
                detail += f" Deadline mentioned: {cand['deadline']}."
            lines.append(detail)
            if cand["snippet"]:
                lines.append(f"  > {cand['snippet']}")
        lines.append("")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return by_category


def main():
    parser = argparse.ArgumentParser(
        description="Scan an IMAP inbox (read-only) for opportunities; write a Markdown checklist."
    )
    parser.add_argument("--days", type=int, default=365, help="how far back to scan (default: 365)")
    parser.add_argument("--limit", type=int, default=500, help="max messages to scan (default: 500)")
    parser.add_argument("--out", default="opportunities.md", help="report path (default: opportunities.md)")
    args = parser.parse_args()

    cfg = {
        "host": os.environ.get("MAILHARVEST_HOST", ""),
        "user": os.environ.get("MAILHARVEST_USER", ""),
        "password": os.environ.get("MAILHARVEST_PASSWORD", ""),
        "mailbox": os.environ.get("MAILHARVEST_MAILBOX", "INBOX"),
        "port": int(os.environ.get("MAILHARVEST_PORT", "993")),
    }
    missing = [k for k in ("host", "user", "password") if not cfg[k]]
    if missing:
        print(f"error: set MAILHARVEST_{', MAILHARVEST_'.join(m.upper() for m in missing)}",
              file=sys.stderr)
        return 2

    classifier_cfg = None
    base = os.environ.get("MAILHARVEST_API_BASE", "")
    key = os.environ.get("MAILHARVEST_API_KEY", "")
    model = os.environ.get("MAILHARVEST_MODEL", "")
    if base and key and model:
        classifier_cfg = {"api_base": base, "api_key": key, "model": model}
        print("cloud classification: enabled")
    else:
        print("cloud classification: off (rules only)")

    candidates = fetch_candidates(cfg, args.days, args.limit)
    by_category = write_report(candidates, args.out, args.days, classifier_cfg)
    counts = ", ".join(f"{c}: {len(v)}" for c, v in sorted(by_category.items())) or "none"
    print(f"done: {len(candidates)} candidate(s) -> {args.out} ({counts})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
