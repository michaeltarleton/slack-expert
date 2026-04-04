# Agent Integration — x-slack

How other skills and agents can use x-slack programmatically.

## Preferred: Direct Mode Calls

For most use cases, call modes directly with `--json --quiet`. This is faster and simpler than spawning a full agent.

```
/x-slack <mode> [args] --json --quiet
```

The JSON envelope is consistent across all modes:
```json
{
  "mode": "search",
  "ok": true,
  "count": N,
  "results": [...],
  "errors": []
}
```

Always check `ok` first. If `false`, read `errors` for the reason.

## Common Integration Patterns

### From /x-bug-fix

```
# 1. Find Slack context for the bug
/x-slack context PROJ-9939 --json --quiet
→ messages + FAQ related to this ticket

# 2. Search by symptom keywords
/x-slack search "login fails after reset" --json --quiet
→ related discussions + FAQ entries

# 3. Check who reported the bug
/x-slack who Alice --json --quiet
→ Alice's pending items and threads

# 4. After fixing: update message status
/x-slack update msg-007 status resolved --json --quiet

# 5. Add new knowledge from investigation
/x-slack faq add "auth" "Why does login fail after reset?" "Session token expires on pw change" --json --quiet

# 6. Link message to ticket
/x-slack link msg-007 PROJ-9939 --json --quiet
```

### From /x-feature

```
# Check for ongoing discussions about the feature
/x-slack search "Spanish component" --json --quiet

# Search FAQ for domain knowledge
/x-slack faq "onboarding" --json --quiet
```

### From /x-done (closing out work)

```
# Find remaining Slack threads to update
/x-slack search PROJ-9939 --json --quiet

# Update message status
/x-slack update msg-007 status resolved --json --quiet
```

## Mode Discovery

Agents can discover all available modes at runtime:

```
/x-slack help --json --quiet
```

Returns:
```json
{
  "mode": "help",
  "ok": true,
  "count": 17,
  "results": [
    { "mode": "scan", "usage": "scan", "description": "...", "agent_friendly": false, "args": [] },
    { "mode": "search", "usage": "search <term>", "description": "...", "agent_friendly": true, "args": ["term"] }
    ...
  ],
  "errors": []
}
```

## Advanced: Spawning the Full Agent

Only spawn the full agent when you need **live Slack scanning** — fresh data from channels not yet in the tracker.

```markdown
Use Agent tool with subagent_type: general-purpose
Prompt: [load contents of .claude/skills/x-slack/agent-prompt.md]

Fill in:
- TASK: what to accomplish
- OWNER_USER_ID: Slack user ID
- CHANNEL_LIST: channels from message-tracker.yml
- LAST_SEARCH_WINDOW: ISO timestamp of last scan
- ADDITIONAL_CONTEXT: any extra constraints
```

See `.claude/skills/x-slack/agent-prompt.md` for the full template and examples.

## Input Validation

When constructing programmatic calls, follow these constraints:

| Input | Pattern | Max length |
|-------|---------|------------|
| `msg-id` | `msg-\d{3,6}` | 10 chars |
| `JIRA-KEY` | `[A-Z]{2,12}-\d{1,7}` (uppercase) | 20 chars |
| Search terms | Free text | 200 chars |
| Reply text | Free text | 4000 chars |
| FAQ answer | Free text | 2000 chars |

## Error Handling

```json
{ "ok": false, "errors": ["msg-id not found: msg-999"] }
{ "ok": false, "errors": ["Near-duplicate of faq-002 (strength: 0.95)..."] }
{ "ok": false, "errors": ["Slack Connect channel — cannot write. Use permalink instead."] }
```

When `ok: false`, do NOT retry blindly. Read the error and adjust.

## Shared Data Files

x-slack shares `people.yml` and `faq.yml` with x-jira. If both skills are installed:
- `people.yml` entries populated by x-slack scan are available to x-jira (and vice versa)
- `faq.yml` entries from x-slack investigations show up in x-jira FAQ lookups
- Both skills update the same files — no sync required
