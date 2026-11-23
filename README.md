# MailHarvest

by Dr. Brent Allen Jensen

Your inbox is full of opportunities you never saw: journal calls for
papers, podcast invitations, grant deadlines, speaking requests, expert
network offers — buried under years of receipts and newsletters.

MailHarvest scans a mailbox over IMAP and pulls them out. A fast rules
engine scores every message against opportunity keyword lists
(publishing, podcast & media, grants & funding, speaking, expert
networks, deadlines), extracts any explicit calendar dates, and writes
a **Markdown report with a checklist** — one actionable item per
candidate, grouped by category. Optionally, a cloud chat model can
classify each candidate (category, deadline, next step); without one,
sensible per-category default actions are used.

## Strictly read-only

This matters, so it is engineered in, not promised: the mailbox is
opened with IMAP `readonly=True` and messages are fetched with
`BODY.PEEK`. Nothing is marked read, flagged, moved, or deleted. Your
mailbox is byte-identical after a run.

## Quickstart

```bash
# No dependencies — Python 3 standard library only.
export MAILHARVEST_HOST="imap.example.com"
export MAILHARVEST_USER="you@example.com"
export MAILHARVEST_PASSWORD="your-app-password"

python3 mailharvest.py --days 365 --limit 500 --out opportunities.md
```

Open `opportunities.md` and start checking boxes.

> Most providers require an **app password** for IMAP when two-factor
> authentication is on. Create one in your mail provider's security
> settings; never use your main password in a script.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `MAILHARVEST_HOST` | — (required) | IMAP server hostname |
| `MAILHARVEST_USER` | — (required) | Mailbox username |
| `MAILHARVEST_PASSWORD` | — (required) | Password / app password |
| `MAILHARVEST_MAILBOX` | `INBOX` | Mailbox to scan |
| `MAILHARVEST_PORT` | `993` | IMAP SSL port |
| `MAILHARVEST_API_BASE` | — | Optional classifier endpoint (OpenAI-compatible) |
| `MAILHARVEST_API_KEY` | — | Classifier API key |
| `MAILHARVEST_MODEL` | — | Classifier model (all three must be set to enable) |

Flags: `--days N` (how far back), `--limit N` (max messages, newest
first), `--out PATH`.

## How it works

1. IMAP `SINCE` search over the last `--days` days, newest first.
2. Each message's subject + body is scored against the keyword lists
   (`score_message()` in the source — import it and tune the lists to
   your world; a mechanic's opportunities differ from a writer's).
3. Explicit dates ("January 5, 2027", "2027-01-05") are pulled out as
   candidate deadlines.
4. The report groups candidates by their strongest category, each as a
   `- [ ]` checklist item with sender, date, deadline, next action, and
   a snippet.

## Requirements

- Python 3.10+ (standard library only)
- IMAP access to a mailbox

## Notes

- Keyword scoring is a net, not a judge: it will catch some newsletters
  and miss some oddly-worded gold. Skim the report; that's the job.
- Old opportunities expire. The report shows dates so you can triage
  ruthlessly — most of the value is in the recent, still-open items.
- The rules engine is a plain function (`score_message(subject, body)`)
  with its own keyword tables at the top of the file. Fork them freely.

## Support this work

If this tool saved you time or taught you something, donations keep the work going:

- BTC: 15McijPo79Zx58NGyEf2PvaPtGqGmpztWn
- ETH: 0x8C25164E9234E6A30b8E44485B79c5cE8419cF2B

## License

MIT — see [LICENSE](LICENSE).
