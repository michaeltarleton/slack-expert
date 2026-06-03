# Slack — Triage & workflow modes

> Part of the `slack` skill. Back to [SKILL.md](../SKILL.md).

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

Output the full argument table from [Argument Parsing](../SKILL.md#argument-parsing) plus:
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
