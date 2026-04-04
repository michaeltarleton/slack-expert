---
name: x-slack
description: Unified Slack interface — send/read messages, manage channels/users, triage by priority tier, track responses, manage FAQ knowledge base, and suggest routing. Use for any Slack operation, triage, or when other skills need Slack context.
user_invocable: true
args: "[send|read|thread|channels|users|scan|status|archive|faq|faq add|reply|search|context|update|link|who|help] [args...] [--json --quiet]"
---

# Slack

Unified Slack interface: messaging, channel/user management, triage, response tracking, and institutional knowledge.

## Table of Contents
- [Argument Parsing](#argument-parsing)
- [Global Flags](#global-flags)
- [Data Files](#data-files)
- [Critical Rules](#critical-rules)
- [Messaging Modes](#messaging-modes)
- [Mode: Scan](#mode-scan)
- [Mode: Status](#mode-status)
- [Mode: Archive](#mode-archive)
- [Mode: FAQ](#mode-faq)
- [Mode: FAQ Add](#mode-faq-add)
- [Mode: Reply](#mode-reply)
- [Mode: Search](#mode-search)
- [Mode: Context](#mode-context)
- [Mode: Update](#mode-update)
- [Mode: Link](#mode-link)
- [Mode: Who](#mode-who)
- [Mode: Help](#mode-help)
- [Output Format](#output-format)
- [JSON Output Format](#json-output-format)
- [Triage Classification](#triage-classification)
- [FAQ Matching](#faq-matching)
- [Agent Spawning](#agent-spawning)
- [Cross-Skill Integration](#cross-skill-integration)

## Argument Parsing

### Messaging Modes

| Input | Mode | Agent-friendly |
|-------|------|----------------|
| `send <channel> <message>` | Send — post message to channel | Yes |
| `read <channel> [count]` | Read — fetch recent messages (default 10) | Yes |
| `thread <channel> <ts> [reply]` | Thread — read thread or reply to it | Yes |
| `channels [search]` | Channels — list/search channels | Yes |
| `users [name_or_id]` | Users — list/search users or view profile | Yes |

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
4. Report: channel name + message timestamp

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
5. Confirm reply with timestamp

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

## Mode: Scan

Full channel sweep across all priority tiers.

### Phase 1: Load Config
1. Read `message-tracker.yml` — load channels, people, triage_rules, categories
2. Read priority hierarchy from `classification-rules.yml`
3. Note `meta.last_search_window` for incremental scanning

### Phase 2: Scan Channels (spawn parallel agents)

Spawn Agent tool with `subagent_type: general-purpose` for parallel scanning:

**CRITICAL tier** (scan first, all in parallel):
- `mcp__slack__slack_read_channel` for each CRITICAL channel

**IMPORTANT tier** (scan second, all in parallel):
- `mcp__slack__slack_read_channel` for team channels + alerts
- `mcp__slack__slack_search_public_and_private` for `<@OWNER_ID>` mentions since last scan

**NORMAL tier** (scan last):
- `mcp__slack__slack_read_channel` for remaining channels

For DMs of key people: use `mcp__slack__slack_read_channel` with user_id as channel_id.

### Phase 3: Classify
For each new message found:
1. Match against `categories` in tracker — assign best-fit category
2. Apply `triage_rules` — determine `suggested_owner`
3. Set priority from channel tier (CRITICAL→urgent, IMPORTANT→medium, NORMAL→low)
4. Check FAQ for similar questions — surface matches with strength >= 0.4

### Phase 4: Response Check
For every message that mentions the owner or needs a response:
- Run BOTH thread AND channel checks in parallel (see Critical Rules)
- Mark status: `pending`, `resolved`, `follow_up`, or `stale`

### Phase 5: Update & Present
1. Update `message-tracker.yml` with new messages
2. Update `people.yml`:
   - For each new message, find or create a thread under the sender's people entry
   - Set thread status based on response check: `awaiting_me` if no response from owner, `awaiting_them` if owner responded, `resolved` if conversation concluded
   - Populate `jira_id` lazily: if a person's `jira_id` is null and we need it, look up via `mcp__atlassian-redacted__lookup_jira_account_id` and save
3. Update `meta.last_updated` and `meta.last_search_window` in both files
4. Present results using Output Format (numbered, grouped by tier)

## Mode: Status

Show current state from `message-tracker.yml` without scanning Slack.

1. Read `message-tracker.yml`
2. Filter messages by status: `pending` → `follow_up` → `action_needed`
3. Present using Output Format (numbered)
4. Show counts: pending / follow_up / resolved / stale

## Mode: Archive

Manage lifecycle of resolved/stale messages older than 7 days.

1. Read `message-tracker.yml`
2. Find resolved/stale messages where `date` is older than 7 days
3. For EACH message, present and ask:
   - "Archive or change to follow-up?"
4. Move archived items to `message-tracker-archive.yml` (append under current month)
5. **Verify archive write succeeded** — re-read archive file and confirm the entry is present before proceeding. If write failed, abort and report error. Never delete from the active file unless the archive write is verified.
6. Remove archived items from `message-tracker.yml`
7. Items changed to follow-up: update status to `follow_up`, ask for `follow_up_reason`

## Mode: FAQ

Search the knowledge base.

| Input | Behavior |
|-------|----------|
| `faq` | Show all topics with entry counts |
| `faq <term>` | Search entries by keyword across question, answer, context, edge_cases |
| `faq <topic>` | Show all entries for a topic |

For each match, display:
- FAQ ID, question, answer (or "UNANSWERED")
- Edge cases (bulleted)
- Related entries with strength scores
- Linked Jira tickets
- Source permalink

## Mode: Reply

Respond to a tracked message.

1. Validate `<msg-id>` format and lookup in `message-tracker.yml` — reject if not found
2. Validate `<text>` length (max 4000 chars)
3. Resolve channel and thread_ts
4. **Preview before sending**: Show the channel name, thread context, and full message text. Ask for confirmation before sending. In `--json --quiet` mode, return the preview as a dry-run result with `"sent": false` — the calling agent must make a second call with `reply <msg-id> --confirm <text>` to actually send
5. Check `slack_connect` on the channel:
   - If `true`: provide permalink + copyable message (see Critical Rules)
   - If `false`: call `mcp__slack__slack_send_message` with channel_id, thread_ts, text
6. Update message status to `resolved` with `resolved_by` noting the reply
7. Update `people.yml`: find the thread containing this msg-id, set status to `awaiting_them` (or `resolved` if the reply closes the topic)
8. Check if the reply answers a question — if so, run faq add dedup check before appending to `faq.yml`

## Mode: Search

Find tracked messages by keyword, Jira ticket key, or person name.

**Input**: `search <term>` where term is free-text (e.g., `search PROJ-9939`, `search login bug`, `search Alice`)

### Algorithm
1. Read `message-tracker.yml`
2. Search across these fields in each message: `summary`, `from`, `category`, `jira_tickets`, `channel`
3. Also search `faq.yml` entries: `question`, `answer`, `context`, `edge_cases`, `topic`, `jira_tickets`
4. Return combined results, messages first then FAQ hits

### Output (human)
```
### Messages (N matches)
1. **msg-007** — From: Alice — "login fails after password reset" — #triage
   Status: pending | Category: bug_triage | Jira: PROJ-9939

### FAQ (N matches)
2. **faq-003** — Topic: auth — "Why does login fail after reset?"
   Strength: 0.8 to faq-001 | Jira: PROJ-9939
```

### Output (JSON)
```json
{
  "mode": "search",
  "ok": true,
  "count": 2,
  "results": [
    { "type": "message", "id": "msg-007", "from": "Alice", "summary": "...", "channel": "triage", "status": "pending", "category": "bug_triage", "jira_tickets": ["PROJ-9939"] },
    { "type": "faq", "id": "faq-003", "topic": "auth", "question": "...", "strength": 0.8, "related_to": "faq-001", "jira_tickets": ["PROJ-9939"] }
  ],
  "errors": []
}
```

## Mode: Context

Reverse lookup: given a Jira ticket key, find ALL related Slack messages and FAQ entries.

**Input**: `context <JIRA-KEY>` (e.g., `context PROJ-9939`)

### Algorithm
1. Read `message-tracker.yml` — scan `messages[].jira_tickets` for the key
2. Read `faq.yml` — scan `jira_index` for the key, then load matching FAQ entries
3. Also search `faq.yml` entries where `jira_tickets` contains the key
4. Follow `related_to` links from matched FAQ entries (one hop, strength >= 0.4)
5. Return combined context

### Output (human)
```
### PROJ-9939 — Slack Context

**Messages (2)**
1. **msg-007** — From: Alice — #triage — Status: pending
   "login fails after password reset"
2. **msg-012** — From: Bob — #critical — Status: resolved
   "users locked out after deploy"

**FAQ (1 direct, 1 related)**
3. **faq-003** — "Why does login fail after reset?" — ANSWERED
4. **faq-001** — (related, strength 0.8) — "Auth pipeline overview"
```

### Output (JSON)
```json
{
  "mode": "context",
  "ok": true,
  "jira_key": "PROJ-9939",
  "count": 4,
  "results": {
    "messages": [ { "id": "msg-007", "from": "Alice", "channel": "triage", "status": "pending", "summary": "..." } ],
    "faq_direct": [ { "id": "faq-003", "topic": "auth", "question": "...", "answered": true } ],
    "faq_related": [ { "id": "faq-001", "strength": 0.8, "topic": "auth", "question": "..." } ]
  },
  "errors": []
}
```

## Mode: Update

Programmatic field update on a tracked message. No interactive prompts — designed for agent use.

**Input**: `update <msg-id> <field> <value>`

### Supported Fields

| Field | Allowed Values | Notes |
|-------|---------------|-------|
| `status` | `pending`, `resolved`, `follow_up`, `action_needed`, `stale` | Most common update |
| `priority` | `urgent`, `critical`, `medium`, `low` | Override channel-derived priority |
| `category` | Any key from `categories` in tracker | Reclassify |
| `suggested_owner` | Any key from `people` in tracker | Reroute |
| `follow_up_reason` | Free text | Required when status → follow_up |

### Algorithm
1. Read `message-tracker.yml`
2. Find message by `id` — error if not found
3. Validate field name and value against allowed list
4. Update the field in-place
5. Set `meta.last_updated` to now
6. Write back to `message-tracker.yml`

### Output (human)
```
Updated msg-007: status → resolved
```

### Output (JSON)
```json
{
  "mode": "update",
  "ok": true,
  "count": 1,
  "results": [{ "id": "msg-007", "field": "status", "old_value": "pending", "new_value": "resolved" }],
  "errors": []
}
```

### Error cases
- `ok: false` if msg-id not found, field not in allowed list, or value not valid for field

## Mode: Link

Connect a tracked message to a Jira ticket. Bidirectional: updates both message and `jira_tickets` node.

**Input**: `link <msg-id> <JIRA-KEY>` (e.g., `link msg-007 PROJ-9939`)

### Algorithm
1. Read `message-tracker.yml`
2. Find message by `id` — error if not found
3. Append `JIRA-KEY` to message's `jira_tickets` array (dedup)
4. Add/update entry in top-level `jira_tickets` node: `{ key: JIRA-KEY, messages: [msg-id], faq_entries: [...] }`
5. Check `faq.yml` — if any entries reference this Jira key, update `jira_index`
6. Write both files

### Output (human)
```
Linked msg-007 ↔ PROJ-9939
```

### Output (JSON)
```json
{
  "mode": "link",
  "ok": true,
  "count": 1,
  "results": [{ "msg_id": "msg-007", "jira_key": "PROJ-9939", "already_linked": false }],
  "errors": []
}
```

## Mode: Who

Show all pending/active items for or from a specific person, including conversation threads and directional status.

**Input**: `who <person>` — matches against `people.yml` keys, `name`, and `alias` fields (case-insensitive, partial match)

### Algorithm
1. Read `people.yml` — resolve person identity
   - If multiple candidates match, do NOT auto-select. Return all candidates and ask the caller to disambiguate using the exact key
   - In `--json --quiet` mode: return `ok: false` with a `candidates` array listing each match's key and name
2. Read `message-tracker.yml` — find messages where:
   - `from` matches the person's slack_id, OR
   - `suggested_owner` matches the person's slack_id, OR
   - `mentioned` includes the person's slack_id
3. Filter messages to non-archived statuses: `pending`, `follow_up`, `action_needed`
4. Load person's `threads` from `people.yml` — filter to non-resolved statuses
5. Merge: messages + threads, deduped by msg-id
6. Sort by: `awaiting_me` first, then priority (urgent → low), then date descending

### Output (human)
```
### Alice Smith (alice_smith) — 2 threads, 2 messages

Slack: UXXXXXXXXXX | Jira: 712020:xxx-xxx | Pref: slack_dm
Topics: engineering

**Threads awaiting me:**
1. login_reset_bug — "Login fails after password reset"
   Status: awaiting_me | Since: 2026-01-15 | Messages: msg-007

**Messages:**
2. **msg-007** — Login fails after password reset — #triage
   Priority: medium | Status: pending | Category: bug_triage
```

### Output (JSON)
```json
{
  "mode": "who",
  "ok": true,
  "person": { "key": "alice_smith", "name": "Alice Smith", "slack_id": "UXXXXXXXXXX", "jira_id": "712020:xxx-xxx", "comm_pref": "slack_dm", "topics": ["engineering"] },
  "count": 2,
  "results": {
    "threads": [
      { "topic": "login_reset_bug", "status": "awaiting_me", "msg_ids": ["msg-007"], "faq_ids": [], "last_contact": "2026-01-15", "next_followup": null, "note": "..." }
    ],
    "messages": [
      { "id": "msg-007", "summary": "...", "priority": "medium", "status": "pending", "category": "bug_triage", "role": "from" }
    ]
  },
  "errors": []
}
```

## Mode: FAQ Add

Programmatically create a new FAQ entry. Used by agents after answering a question.

**Input**: `faq add <topic> <question> <answer>`

Arguments are positional, separated by the first space after each segment. For multi-word values, the parser splits on the first 3 unquoted segments. If ambiguous, wrap in quotes: `faq add "auth" "Why does login fail after reset?" "The session token expires after password change"`

### Algorithm
1. Read `faq.yml`
2. **Dedup check** (before creating anything):
   - Normalize incoming question to lowercase, remove stop words
   - Compare against ALL existing entries on: `question`, `topic`, `context`
   - If same `topic` AND word overlap > 60% → near-duplicate
   - If any entry scores strength >= 0.9 → reject with error showing the existing entry's id, question, and answer so the caller can merge instead
   - If strength 0.7–0.89 → warn but allow (show the similar entry for awareness)
3. Generate next faq-id (e.g., `faq-008`) — re-read `faq.yml` immediately before to avoid ID collisions from concurrent adds
4. Create entry:
   - `topic`, `question`, `answer`, `date: now`, `times_asked: 1`
   - `confidence: 0.7` if added interactively, `confidence: 0.5` if added by an agent
   - `source_type: human` or `agent` — tracks provenance
5. Compute `related_to` links: tokenize question + topic, match against existing entries
   - Score by keyword overlap + topic match
   - Include links with strength >= 0.4
6. Append entry to `faq.yml`
7. If answer references Jira tickets (pattern: `\b[A-Z]{2,12}-\d{1,7}\b`), update `jira_index` — only for project prefixes configured in `classification-rules.yml`

### Output (human)
```
Created faq-008: [auth] "Why does login fail after password reset?"
Related: faq-002 (strength: 0.6), faq-005 (strength: 0.4)
```

### Output (JSON)
```json
{
  "mode": "faq_add",
  "ok": true,
  "count": 1,
  "results": [{ "id": "faq-008", "topic": "auth", "question": "...", "related_to": [{ "id": "faq-002", "strength": 0.6 }] }],
  "errors": []
}
```

### Near-duplicate rejection
If strength >= 0.9 or (same topic AND word overlap > 60%):
```json
{
  "mode": "faq_add",
  "ok": false,
  "count": 0,
  "results": [],
  "errors": ["Near-duplicate of faq-002 (strength: 0.95) — 'Why does login fail after reset?' — answer: 'Session token expires after password change...'. Update the existing entry instead of creating a new one."]
}
```

## Mode: Help

List all available modes with descriptions, arguments, and agent-friendliness. Designed for both humans and agent discovery.

**Input**: `help` or `help <mode>`

### `help` (no args) — Overview

Output the full argument table from [Argument Parsing](#argument-parsing) plus:
- Data directory path
- Global flags available (`--json --quiet`)
- Quick examples for each mode

### `help <mode>` — Detail

Output for a specific mode:
- Description (1-2 sentences)
- Full input syntax with examples
- Supported fields/values (for `update`, `link`, etc.)
- JSON output schema
- Agent usage example

### Output (JSON)
```json
{
  "mode": "help",
  "ok": true,
  "count": 12,
  "results": [
    { "mode": "scan", "usage": "scan", "description": "Full channel sweep across all priority tiers", "agent_friendly": false, "args": [] },
    { "mode": "search", "usage": "search <term>", "description": "Find messages by keyword/ticket/person", "agent_friendly": true, "args": ["term"] }
  ],
  "errors": []
}
```

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

## Agent Spawning

The skill spawns agents for parallel work:

### Channel Scanner Agent
```
Spawn: Agent tool, subagent_type: general-purpose
Task: Read channels [list] using mcp__slack__slack_read_channel.
      For each message mentioning owner, also run mcp__slack__slack_read_thread
      AND mcp__slack__slack_read_channel to check for responses.
      Return: list of {message_ts, channel_id, from, text, has_response, response_text}
```

### FAQ Matcher Agent
```
Spawn: Agent tool, subagent_type: general-purpose
Task: Given question text, search faq.yml for matching entries.
      Score by keyword overlap + topic + related_to chain.
      Return: list of {faq_id, strength, answer_summary, edge_cases}
```

## Cross-Skill Integration

Other skills can use the agent-friendly modes directly or spawn the slack-triage agent for more complex work.

### Preferred: Direct Mode Calls

Agents should call modes directly with `--json --quiet` for structured results:

#### /x-bug-fix investigating PROJ-9939
```
1. /x-slack context PROJ-9939 --json --quiet
   → Get all Slack messages + FAQ entries about this ticket
2. /x-slack search "login fails" --json --quiet
   → Find related discussions by symptom keywords
3. /x-slack who Alice --json --quiet
   → Check what Alice has pending (she reported the bug)
4. After fixing: /x-slack update msg-007 status resolved --json --quiet
5. If new knowledge: /x-slack faq add "auth" "Why does login fail?" "Session token expires..." --json --quiet
6. Link ticket: /x-slack link msg-007 PROJ-9939 --json --quiet
```

### Advanced: Agent Spawn

For complex work requiring live Slack scanning (not just tracker queries), spawn the full agent:

Prompt template: see [agent-prompt.md](agent-prompt.md)

### Spawn Pattern
```markdown
Use Agent tool with subagent_type: general-purpose
Prompt: [contents of agent-prompt.md with variables filled in]
```

### Agent Discovery

Other agents can call `/x-slack help --json --quiet` to discover all available modes and their arguments at runtime. This enables dynamic integration without hardcoding mode knowledge.
