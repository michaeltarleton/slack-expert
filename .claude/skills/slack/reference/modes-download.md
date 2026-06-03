# Slack — Download mode

> Part of the `slack` skill. Back to [SKILL.md](../SKILL.md).

## Mode: Download

Retrieve file content from a Slack message attachment. Downloads the file via Slack Web API, converts to markdown based on type, and caches the result for 72 hours.

**Use case**: Email-to-channel forwarded attachments where the actual content is in the file, not the message text. Used by `/new-product-mapping` to extract product details from forwarded emails.

### Input
| Form | Description |
|------|-------------|
| `download <slack_message_url>` | Parse channel + ts, find file in message |
| `download <file_id>` (F-prefixed) | Direct download by file ID |
| `download --channel <id> --latest` | Get most recent file from channel |
| `download <file_id> --invalidate` | Delete cached entry, force re-download |

### Algorithm

1. **Validate input** — match against `slack_url` or `file_id` pattern (see Critical Rules → Input Validation)

2. **Resolve metadata**
   - If URL: parse `channel_id` and `ts` from `/archives/{C}/p{ts_no_dot}`. Insert `.` before last 6 digits of ts. Call `mcp__slack__slack_read_channel` (or `slack_read_thread`) and find the file in the message's `files[]` array.
   - If file_id: skip metadata fetch — download script will call `files.info` directly.
   - If `--latest`: call `mcp__slack__slack_search_public` with `in:#channel` and content_types filter, sort by timestamp desc, take first.

3. **Opportunistic cache cleanup**
   ```bash
   python ~/.claude/skills/slack/scripts/cleanup_cache.py \
     --cache-dir ~/.claude/companies/{company}/data/slack/downloads/
   ```

4. **Cache check**
   - `CACHE_DIR=~/.claude/companies/{company}/data/slack/downloads`
   - If `{file_id}.md` and `{file_id}.meta.json` both exist: read meta, compare `expires_at` to now.
   - If valid AND `--invalidate` not passed: return cached content immediately.
   - If `--invalidate` passed: delete both files, continue to download.

5. **Download file**
   ```bash
   TMPFILE=$(mktemp /tmp/slack-dl-XXXXXX)
   python ~/.claude/skills/slack/scripts/download_slack_file.py \
     --file-id "{file_id}" \
     --output "$TMPFILE"
   ```
   If exit code != 0: STOP — return error in JSON envelope.

6. **Convert to markdown**
   ```bash
   python ~/.claude/skills/slack/scripts/convert_to_markdown.py \
     --input "$TMPFILE" \
     --mimetype "{mimetype}" \
     --output "$CACHE_DIR/{file_id}.md"
   ```

7. **Handle OCR** — if conversion output has `needs_ocr: true`:
   - Spawn Haiku agent with image path (see Image OCR block below).
   - Save agent output to `$CACHE_DIR/{file_id}.md`.
   - If output < 50 chars AND image size > 100 KB: retry with model: sonnet.
   - If both attempts produce < 20 chars: STOP, return error.

8. **Write meta sidecar** — write `{file_id}.meta.json`:
   ```json
   {
     "file_id": "F07XXXXXX",
     "filename": "...",
     "source_mimetype": "text/html",
     "conversion_method": "beautifulsoup4",
     "slack_message_ts": "1774472174.330539",
     "channel_id": "C07RP9AE5B7",
     "permalink": "https://...",
     "cached_at": "<ISO8601_UTC>",
     "expires_at": "<cached_at + 72h>",
     "char_count": 2340,
     "needs_ocr": false
   }
   ```

9. **Cleanup raw file**
   ```bash
   rm -f "$TMPFILE"
   ```

10. **Return content** — read `{file_id}.md` and return (human or JSON).

### Image OCR Spawn

When `needs_ocr: true`:
```
Use Agent tool with:
  subagent_type: general-purpose
  model: haiku
  description: Extract text from Slack image
  prompt: |
    Read the image at {raw_file_path}. Extract ALL text content visible.
    Format as markdown (tables → markdown tables, email → preserve headers/body/signature).
    Return ONLY extracted text. No commentary.
```
If output < 50 chars AND image size > 100 KB → retry with `model: sonnet`.

### Output (human)
```
Downloaded: New Product Created and Ready for Mapping.html
File ID: F07XXXXXX
Type: text/html → markdown (beautifulsoup4)
Cached: 72h
Chars: 2340

---

[markdown content here]
```

### Output (JSON)
```json
{
  "mode": "download",
  "ok": true,
  "count": 1,
  "results": [{
    "file_id": "F07XXXXXX",
    "filename": "New Product Created and Ready for Mapping.html",
    "mimetype": "text/html",
    "conversion_method": "beautifulsoup4",
    "char_count": 2340,
    "cached": true,
    "cache_path": "~/.claude/companies/amira/data/slack/downloads/F07XXXXXX.md",
    "expires_at": "2026-04-06T14:30:00Z",
    "permalink": "https://amiralearning.slack.com/archives/C07RP9AE5B7/p1774472174330539",
    "content": "[markdown content here]"
  }],
  "errors": []
}
```

### Error cases
| Error | Result |
|-------|--------|
| Invalid URL/file_id format | `ok: false`, `errors: ["Invalid input: ..."]` |
| Token missing | `ok: false`, `errors: ["Slack bot token not found. Set SLACK_BOT_TOKEN env var."]` |
| File not found (404) | `ok: false`, `errors: ["File F... not found or access denied"]` |
| File too large (>50MB) | `ok: false`, `errors: ["File exceeds 50 MB cap"]` |
| Unsupported mimetype | `ok: false`, `errors: ["Cannot convert {mimetype}. Paste content manually."]` |
| OCR failed (image) | `ok: false`, `errors: ["Image text extraction failed. Paste content manually."]` |
| Conversion script error | `ok: false`, `errors: ["Conversion failed: {stderr}"]` |

---
