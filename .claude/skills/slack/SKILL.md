---
name: slack
description: Unified Slack interface — send/read messages, manage channels/users, download file attachments, triage by priority tier, track responses, manage FAQ knowledge base, and suggest routing. Use for any Slack operation, triage, or when other skills need Slack context.
user_invocable: true
args: "[send|read|thread|channels|users|download|scan|status|archive|faq|faq add|reply|search|context|update|link|who|help] [args...] [--json --quiet]"
---

# Slack

Unified Slack interface: messaging, channel/user management, triage, response tracking, and institutional knowledge.

## Table of Contents

- [Argument Parsing](#argument-parsing)
- [Global Flags](#global-flags)
- [Data Files](#data-files)
- [Critical Rules](#critical-rules)
- [Messaging Modes](#messaging-modes)
- [Mode: Download](#mode-download)
- [Triage & Workflow Modes](#triage--workflow-modes)
- [Output Format](#output-format)
- [JSON Output Format](#json-output-format)
- [Triage Classification](#triage-classification)
- [FAQ Matching](#faq-matching)
- [Agent Spawning & Cross-Skill Integration](#agent-spawning--cross-skill-integration)

## Argument Parsing

### Messaging Modes

| Input | Mode | Agent-friendly |
|-------|------|----------------|
| `send <channel> <message>` | Send — post message to channel | Yes |
| `read <channel> [count]` | Read — fetch recent messages (default 10) | Yes |
| `thread <channel> <ts> [reply]` | Thread — read thread or reply to it | Yes |
| `channels [search]` | Channels — list/search channels | Yes |
| `users [name_or_id]` | Users — list/search users or view profile | Yes |
| `download <url\|file_id> [--invalidate]` | Download — fetch file content from message attachment | Yes |

### Triage Modes

| Input | Mode | Agent-friendly |
|-------|------|----------------|
| (empty) or `scan` | Scan — full channel sweep | |
| `status` | Status — show active tracker items | |
| `archive` | Archive — prompt for stale item decisions | |
| `faq <term>` | FAQ — search knowledge base | Yes |
| `faq add <topic> <question> <answer>` | FAQ Add — create new entry | Yes |
| `reply <msg-id> <text>` | Reply — respond to a tracked message | |
| `search <term>` | Search — find messages by keyword/ticket/person | Yes |
| `context <JIRA-KEY>` | Context — Jira ticket → Slack messages + FAQ | Yes |
| `update <msg-id> <field> <value>` | Update — change message field programmatically | Yes |
| `link <msg-id> <JIRA-KEY>` | Link — connect message to Jira ticket | Yes |
| `who <person>` | Who — pending items for/from a person | Yes |
| `help [mode]` | Help — list all modes with descriptions | Yes |

## Global Flags

### `--json --quiet`

When present, ALL output switches to machine-readable JSON. No markdown, no numbered lists, no prose.

**Detection**: Check if the raw input string contains `--json` or `--quiet`. Strip flags before parsing the mode argument.

**Behavior**:
- Suppress all human-friendly formatting (headers, bullets, FAQ match prose)
- Return a single JSON object to stdout
- Agents should ALWAYS pass `--json --quiet` when spawning this skill programmatically

**JSON envelope** (wraps every mode's output):
```json
{
  "mode": "search|context|status|...",
  "ok": true,
  "count": 3,
  "results": [ ... ],
  "errors": []
}
```

- `ok`: false if the mode encountered errors (missing msg-id, no matches, etc.)
- `count`: number of items in results
- `errors`: array of error strings (empty on success)
- `results`: mode-specific array (see JSON Output Format section)

## Data Files

Data files are company-scoped and live outside the skill directory for portability.

**Path**: `~/.claude/companies/{company}/data/`

**Company resolution**: Determined from the current working directory. See `CLAUDE.md` in this repo.

Slack-specific files: `~/.claude/companies/{company}/data/slack/`

**Shared** (`~/.claude/companies/{company}/data/`):

| File | Purpose |
|------|---------|
| `people.yml` | Unified identity directory — Slack/Jira ID mapping, per-person threads, directional status, follow-up dates |
| `faq.yml` | Q&A knowledge base with edge cases, relations, jira index |
| `categories.yml` | Shared category definitions used by both Slack and Jira triage |

**Slack-specific** (`~/.claude/companies/{company}/data/slack/`):

| File | Purpose |
|------|---------|
| `message-tracker.yml` | Active messages, channels, message metadata |
| `message-tracker-archive.yml` | Resolved/stale messages (append-only, grouped by month) |
| `classification-rules.yml` | Slack-specific triage rules (channel/keyword matching → category) |

**Loading strategy:**
- `message-tracker.yml` — every invocation (messages, channels)
- `classification-rules.yml` — scan mode (classifying new messages)
- `categories.yml` — scan mode (category definitions)
- `people.yml` — modes needing identity resolution (`who`, `search`, `scan`, `reply`)
- `faq.yml` — knowledge lookups (`faq`, `search`, `context`, `faq add`)

**First-run bootstrap**: If the data directory doesn't exist, create it and scaffold empty templates with the correct schema. Prompt the user to configure their channel tiers and people.

## Critical Rules

These are non-negotiable. Violating them causes incorrect results.

### Input Validation

Validate before processing. Reject with `ok: false` and descriptive error.

| Input type | Pattern | Max length |
|-----------|---------|------------|
| `msg-id` | `^msg-\d{3,6}$` | 10 |
| `JIRA-KEY` | `^[a-zA-Z]{2,12}-\d{1,7}$` (normalize to uppercase) | 20 |
| `search/faq/who term` | Free text | 200 |
| `reply text` | Free text | 4000 |
| `faq add` topic / question / answer | Free text | 100 / 500 / 2000 |
| `follow_up_reason` | Free text | 500 |
| `file_id` | `^F[A-Z0-9]{8,12}$` | 15 |
| `slack_url` | `^https://[\w.-]+\.slack\.com/archives/[CDG][A-Z0-9]+/p\d{16}` | 200 |

Jira key extraction from answer text: use `\b[a-zA-Z]{2,12}-\d{1,7}\b` (anchored), normalize to uppercase. Only index keys matching project prefixes configured in your company's `classification-rules.yml`. Flag unknown prefixes for user confirmation.

### Response Checking
For EVERY message, run BOTH checks IN PARALLEL before marking response status:
1. `mcp__slack__slack_read_thread` — check thread replies
2. `mcp__slack__slack_read_channel` — check channel messages around the timestamp

NEVER mark a message as unresponded based on thread check alone. DMs and group DMs typically use channel-level replies, not threads.

**Why**: Repeatedly missed replies posted as channel messages rather than thread replies. This caused false unresponded reports 3 times.

### Slack Connect Channels
Before attempting ANY write operation, check the channel's `slack_connect` field in `message-tracker.yml` or the channel node.

If `slack_connect: true`:
- Do NOT attempt `mcp__slack__slack_send_message`
- Instead, provide: permalink + copyable message text
- Error if attempted: `mcp_externally_shared_channel_restricted`

### Scan Order
Always process: CRITICAL → IMPORTANT → NORMAL. Never skip tiers.

### Numbered Output
Every item in every list MUST have a sequential number for user tagging.

## Messaging Modes

These are direct Slack operations — no triage logic, no tracker updates.

### Mode: Send

Post a message to a channel.

**Input**: `send <channel> <message>` — channel is name (strip `#`) or ID
1. If channel doesn't start with `C`, resolve name to ID via `mcp__slack__slack_search_channels`
2. Check `slack_connect` — if true, provide permalink + copyable message instead (see Critical Rules)
3. Call `mcp__slack__slack_send_message` with channel_id and text
4. Build permalink: `https://{workspace}.slack.com/archives/{channel_id}/p{ts_no_dot}` where `ts_no_dot` = timestamp with `.` removed (e.g., `1776114430.309819` → `p1776114430309819`). Workspace = `amiralearning` for this company.
5. Report: channel name, message timestamp, and full permalink as a clickable link

### Mode: Read

Fetch recent messages from a channel or DM.

**Input**: `read <channel> [count]` — count defaults to 10, max 200
1. Resolve channel name to ID if needed
2. Call `mcp__slack__slack_read_channel` with channel_id and limit
3. Display each message: timestamp, author, text, thread reply count
4. If threads exist, suggest `thread` mode to drill in

### Mode: Thread

Read a thread's replies or post a reply.

**Input**: `thread <channel> <thread_ts> [reply_text]`
1. Resolve channel name to ID if needed
2. Call `mcp__slack__slack_read_thread` with channel_id and thread_ts
3. Display parent + all replies with timestamps and authors
4. If reply_text provided: check `slack_connect`, then call `mcp__slack__slack_send_message` with channel_id, thread_ts, text
5. Build permalink: `https://amiralearning.slack.com/archives/{channel_id}/p{ts_no_dot}` (ts with `.` removed)
6. Confirm reply with timestamp and permalink

### Mode: Channels

List or search Slack channels.

**Input**: `channels [search_term]`
1. Call `mcp__slack__slack_search_channels` with query (or list all)
2. If search term provided, filter by case-insensitive name match
3. Display table: channel name, ID, member count, purpose (truncated)

### Mode: Users

List users or view a profile.

**Input**: `users [name_or_id]`
1. If arg starts with `U`, call `mcp__slack__slack_read_user_profile` with user_id. Display name, title, status, timezone
2. Otherwise, call `mcp__slack__slack_search_users` with query
3. Display table: display name, user ID, title, status
4. If a person is found, check `people.yml` for their entry and show Jira ID if available

## Mode: Download

Downloads Slack file attachments (incl. image OCR + JSON/human outputs and
error cases). Full algorithm and outputs: see
[reference/modes-download.md](reference/modes-download.md).

## Triage & Workflow Modes

Scan, Status, Archive, FAQ, Reply, Search, Context, Update, Link, Who, FAQ Add.
Full per-mode algorithms, output (human + JSON), and error cases: see
[reference/modes-triage.md](reference/modes-triage.md).

## Output Format

All output follows this structure:

```
### TIER_NAME

N. **From** — Summary — [link](permalink)
   Category: X | Suggested: Y | Status: Z
   [FAQ match: faq-NNN (strength: 0.X) — "previous answer summary"]
```

Requirements:
- Sequential numbers across all tiers (1, 2, 3... not restarting per tier)
- Every item has: from, summary, permalink
- Category and suggested_owner from triage classification
- FAQ matches shown inline when strength >= 0.4
- Jira tickets shown when linked

## JSON Output Format

When `--json --quiet` is active, every mode returns the standard envelope. Mode-specific `results` schemas:

| Mode | results type | Key fields |
|------|-------------|------------|
| `scan` | `array<message>` | id, from, channel, summary, status, priority, category, faq_matches |
| `status` | `array<message>` | id, from, summary, status, priority, category |
| `archive` | `array<{id, action}>` | id, action (archived/follow_up) |
| `faq` | `array<faq_entry>` | id, topic, question, answer, edge_cases, related_to, jira_tickets |
| `faq add` | `array<{id, topic, related_to}>` | id, topic, question, related_to |
| `reply` | `array<{msg_id, channel, sent}>` | msg_id, channel_id, sent (bool), permalink |
| `search` | `array<message\|faq_entry>` | type (message/faq), id, plus type-specific fields |
| `context` | `{messages, faq_direct, faq_related}` | Grouped by source type |
| `update` | `array<{id, field, old_value, new_value}>` | Single updated field |
| `link` | `array<{msg_id, jira_key, already_linked}>` | Link result |
| `who` | `{threads, messages}` | person identity + threads (directional status, follow-up) + messages |
| `download` | `array<{file_id, filename, mimetype, char_count, content, ...}>` | file_id, filename, mimetype, conversion_method, char_count, cache_path, expires_at, permalink, content |
| `help` | `array<mode_info>` | mode, usage, description, agent_friendly, args |

Agents consuming JSON should check `ok` first, then iterate `results`. Error messages in `errors` array are human-readable strings.

## Triage Classification

When classifying a new message:

1. **Category match**: Compare message content against `categories` descriptions in tracker
2. **Rule match**: Walk `triage_rules` list — first matching rule sets `suggested_owner`
3. **Priority**: Inherit from channel tier unless content overrides:
   - P0 in any channel → `urgent`
   - Direct @mention in CRITICAL → `critical`
   - IMPORTANT channel → `medium`
   - NORMAL channel → `low`
4. **Confidence**: Set based on rule match quality (high/medium/low)

After user acts on a message (archive, follow-up, delegate), update triage_rules if the action reveals a new pattern. Add with `confidence: low` initially; promote after 3 confirmations.

## FAQ Matching

When a new question is found:

1. Tokenize the question into keywords
2. Match against `faq.yml` entries: question, context, edge_cases, topic
3. Score: keyword overlap + topic match + related_to chain
4. Surface matches with strength >= 0.4
5. If strength >= 0.8, suggest: "You answered this before (faq-NNN)"

When the user answers a question:

1. Create new FAQ entry with: topic, question, answer, context, asked_by, date, source
2. Add edge_cases from investigation findings
3. Compute `related_to` links against existing entries:
   - 1.0 = same root cause / duplicate
   - 0.8 = same system, closely related symptom
   - 0.6 = same domain, different mechanism
   - 0.4 = tangentially related (shared component/table)
   - 0.2 = loosely related (same team/area)
4. Add jira_tickets if any referenced
5. Update jira_index in faq.yml
6. Increment `times_asked` if duplicate question

## Agent Spawning & Cross-Skill Integration

Channel-scanner / FAQ-matcher agent specs, direct mode calls, and auto-routing
to `/new-product-mapping` and `/review-pr`: see
[reference/cross-skill.md](reference/cross-skill.md).
