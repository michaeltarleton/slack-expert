# Modes Reference — x-slack

All 17 modes with descriptions, syntax, and examples.

## Quick Reference

| Mode | Usage | Interactive | Agent-friendly |
|------|-------|-------------|----------------|
| `send` | `/x-slack send <channel> <message>` | No | Yes |
| `read` | `/x-slack read <channel> [count]` | No | Yes |
| `thread` | `/x-slack thread <channel> <ts> [reply]` | No | Yes |
| `channels` | `/x-slack channels [search]` | No | Yes |
| `users` | `/x-slack users [name_or_id]` | No | Yes |
| `scan` | `/x-slack scan` | Yes | No |
| `status` | `/x-slack status` | No | No |
| `archive` | `/x-slack archive` | Yes | No |
| `faq` | `/x-slack faq [term]` | No | Yes |
| `faq add` | `/x-slack faq add <topic> <q> <a>` | No | Yes |
| `reply` | `/x-slack reply <msg-id> <text>` | Yes | No |
| `search` | `/x-slack search <term>` | No | Yes |
| `context` | `/x-slack context <JIRA-KEY>` | No | Yes |
| `update` | `/x-slack update <msg-id> <field> <value>` | No | Yes |
| `link` | `/x-slack link <msg-id> <JIRA-KEY>` | No | Yes |
| `who` | `/x-slack who <person>` | No | Yes |
| `help` | `/x-slack help [mode]` | No | Yes |

---

## Messaging Modes

### send

Post a message to a channel.

```
/x-slack send #general "Hello team, deploying at 3pm"
/x-slack send general "Hello team"        # # is optional
/x-slack send C0XXXXXXXXX "Hello team"    # channel ID also works
```

**Slack Connect**: If the channel is Slack Connect, provides permalink + copyable text instead of sending.

---

### read

Fetch recent messages from a channel or DM.

```
/x-slack read #alerts-critical            # Last 10 messages
/x-slack read #team-general 50           # Last 50 messages
/x-slack read UXXXXXXXXXX                # DM with this user
```

---

### thread

Read a thread or post a reply to one.

```
/x-slack thread #general 1234567890.123456           # Read thread
/x-slack thread #general 1234567890.123456 "Reply"   # Reply to thread
```

---

### channels

List or search channels.

```
/x-slack channels               # List all accessible channels
/x-slack channels alerts        # Search for channels matching "alerts"
```

---

### users

Look up Slack users.

```
/x-slack users                  # List users
/x-slack users Alice            # Search for Alice
/x-slack users UXXXXXXXXXX      # Profile for specific user ID
```

---

## Triage Modes

### scan

Full channel sweep across all priority tiers. This is the main triage workflow.

```
/x-slack scan
```

1. Loads `message-tracker.yml` + `classification-rules.yml`
2. Scans CRITICAL → IMPORTANT → NORMAL channels in parallel
3. Classifies new messages
4. Checks response status (thread + channel, parallel)
5. Updates `message-tracker.yml` and `people.yml`
6. Presents numbered results grouped by tier

---

### status

Show active tracker items without scanning Slack.

```
/x-slack status
```

Shows counts: pending / follow_up / action_needed / stale

---

### archive

Manage lifecycle of resolved/stale messages older than 7 days.

```
/x-slack archive
```

Interactive: for each eligible message, prompts "Archive or follow-up?". Writes to `message-tracker-archive.yml` and verifies before removing from active tracker.

---

### faq

Search or browse the FAQ knowledge base.

```
/x-slack faq                    # Show all topics with counts
/x-slack faq auth               # All entries in "auth" topic
/x-slack faq "login fails"      # Search by keywords
```

---

### faq add

Add a new FAQ entry.

```
/x-slack faq add auth "Why does login fail?" "Session token expires after password change"
/x-slack faq add "onboarding" "How do I get access?" "Submit form at /access-request"
```

Includes dedup check: rejects if strength >= 0.9, warns if 0.7-0.89.

---

### reply

Respond to a tracked message.

```
/x-slack reply msg-007 "Thanks, looking into it now"
```

Shows preview before sending. Updates message status to `resolved`.

---

### search

Find tracked messages and FAQ entries by keyword, Jira key, or person name.

```
/x-slack search PROJ-9939       # Find by Jira ticket
/x-slack search "login bug"     # Find by keyword
/x-slack search Alice           # Find by person name
```

---

### context

Given a Jira ticket key, find all related Slack messages and FAQ entries.

```
/x-slack context PROJ-9939
```

Returns: direct messages, FAQ entries, related FAQ (one hop, strength >= 0.4).

---

### update

Programmatically update a field on a tracked message. Designed for agent use.

```
/x-slack update msg-007 status resolved
/x-slack update msg-007 priority urgent
/x-slack update msg-007 category bug_triage
/x-slack update msg-007 follow_up_reason "Waiting for Alice to confirm"
```

Supported fields: `status`, `priority`, `category`, `suggested_owner`, `follow_up_reason`

---

### link

Connect a tracked message to a Jira ticket (bidirectional).

```
/x-slack link msg-007 PROJ-9939
```

---

### who

Show all pending/active items for or from a specific person.

```
/x-slack who Alice              # By name (partial match)
/x-slack who alice_smith        # By people.yml key
```

Output: directional thread status (awaiting_me / awaiting_them), pending messages, sorted by priority.

---

### help

List all modes or get detail on a specific mode.

```
/x-slack help                   # Overview of all modes
/x-slack help scan              # Detail on scan mode
/x-slack help --json --quiet    # Machine-readable mode discovery
```

---

## Global Flags

### `--json --quiet`

Switch ALL output to machine-readable JSON. No prose, no markdown.

```
/x-slack search PROJ-9939 --json --quiet
/x-slack who Alice --json --quiet
/x-slack context PROJ-9939 --json --quiet
```

Agents should ALWAYS use `--json --quiet` when calling skill modes programmatically.

JSON envelope:
```json
{
  "mode": "search",
  "ok": true,
  "count": 2,
  "results": [...],
  "errors": []
}
```
