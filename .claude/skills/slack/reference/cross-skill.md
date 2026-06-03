# Slack — Agent spawning & cross-skill integration

> Part of the `slack` skill. Back to [SKILL.md](../SKILL.md).

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

#### /bug-fix investigating PROJ-9939
```
1. /slack context PROJ-9939 --json --quiet
   → Get all Slack messages + FAQ entries about this ticket
2. /slack search "login fails" --json --quiet
   → Find related discussions by symptom keywords
3. /slack who Alice --json --quiet
   → Check what Alice has pending (she reported the bug)
4. After fixing: /slack update msg-007 status resolved --json --quiet
5. If new knowledge: /slack faq add "auth" "Why does login fail?" "Session token expires..." --json --quiet
6. Link ticket: /slack link msg-007 PROJ-9939 --json --quiet
```

### From /new-product-mapping

When a Slack message contains a file attachment (email-to-channel forwarding):

```
1. /slack download <slack_message_url> --json --quiet
   → Returns markdown text content of the email attachment

2. Pipe content to product mapping parser:
   /new-product-mapping <markdown_content>
```

The download mode handles caching, conversion, and OCR automatically. Requires `SLACK_BOT_TOKEN` env var with `files:read` scope.

### To /new-product-mapping (auto-routing during triage)

**When triaging messages, auto-detect the "New Product Created" pattern and suggest
routing to `/new-product-mapping`.**

**Detection pattern** (matches the rule in `classification-rules.yml`):
- Channel: `#the-syndicate-team` (C07RP9AE5B7)
- From: `USLACKBOT` (Slackbot — because the email is forwarded into the channel)
- Message contains keywords: `"New Product Created"` or `"Ready for Mapping"`
- Has a file attachment (the actual email body as `text/html`)

**What to do when you find one:**

1. **Check the processed cache first** — the mapping skill keeps its own audit log:
   ```bash
   printf '%s\n' "<slack_message_url>" | \
     python ~/.claude/skills/new-product-mapping/scripts/check_processed.py --json
   ```
   If the URL already has a `submitted` or `nothing-to-do` entry, **skip** — it's already
   been mapped. No action needed.

2. **If unprocessed**, classify the message as `category: product_config`,
   `suggested_owner: U02GX89Q3LP`, `suggested_skill: /new-product-mapping`, and
   surface it in the triage output with a routing hint like:
   ```
   msg-NNN — #the-syndicate-team — New Product Created — unprocessed
     Category: product_config | Suggested skill: /new-product-mapping
     Next step: download attachment → parse → resolve components → map via map_product.py
   ```

3. **Never auto-execute the mapping itself** — it requires manual SSO login to
   SForceSync and user confirmation at the Submit gate. The triage agent's job is to
   SURFACE the work, not do it.

4. **After the user runs the mapping**, `map_product.py --notify-slack` handles the
   thread reply automatically. No follow-up action from slack is needed.

**Why this rule has `auto_handler: true`**: the handler skill is fully automated
end-to-end (parse → resolve → browser automation → audit log → Slack reply), so the
only thing a human needs to do is run one command. Much cheaper than manual mapping.

See: `~/.claude/skills/new-product-mapping/SKILL.md` for the full workflow.

### To /review-pr (auto-spawn PR reviews during triage)

**When triaging messages, auto-detect GitHub PR links and spawn `/review-pr` asynchronously.**

**Detection pattern** (matches the rule in `classification-rules.yml`):
- Channel: `#the-syndicate-team` (C07RP9AE5B7)
- Message text contains a `github.com/*/pull/\d+` URL
- Sender: any human user (NOT a bot — `bot_id` is absent)

**Self-PR check** — before spawning:
1. Extract the PR URL from the message text
2. Run: `gh pr view <url> --json author --jq '.author.login'`
3. Compare with: `gh api user --jq '.login'`
4. If same → track the message with `action_needed: false`, `action_reason: self-pr`. Do NOT spawn a review.

**For non-self PRs:**

1. **Track the message** in `message-tracker.yml` with `category: code_review`,
   `suggested_skill: /review-pr`, `status: pending`.

2. **Spawn `/review-pr` as a background agent:**
   ```
   Agent tool, subagent_type: general-purpose, run_in_background: true
   Prompt: "Run /review-pr <PR_URL> in PEER-REVIEW mode.
   After the review completes, post results to Slack:
   1. Add :approved_stamp: reaction to the original message
      (channel: C07RP9AE5B7, ts: <message_ts>).
      If :approved_stamp: fails, fall back to :white_check_mark:.
   2. Post a threaded reply (channel: C07RP9AE5B7, thread_ts: <message_ts>)
      using the new-product-mapping `chat:write` token (created by
      notify_slack_auth.py; see skills/new-product-mapping/scripts/notify_slack.py
      for its exact path).

   Reply template:
   - No changes requested: 'Reviewed — no requested changes.'
   - Changes requested: 'Reviewed — found some things for you to take a look at.'
     Then add 1-2 HUMAN sentences of context:
     - If nitpicks only: 'These are mostly small nitpicks — nothing blocking.'
     - If good code: 'Nice approach on the [specific thing].'
     - If security issue: 'There is a [brief description] that should be addressed before merge.'
     NEVER use emojis in the reply text. NEVER list blockers/major/minor counts.
     Just natural sentences, 1-3 max.

   The review uses /review-pr's built-in agent model (4 always-on + up to 4
   conditional by file type). Engineering-skills enrichments (pr-review-expert,
   tdd-guide, senior-qa) are loaded automatically per Phase 2.1 of /review-pr."
   ```

3. **The agent runs asynchronously** — triage returns immediately. The background
   agent handles the review, GitHub comments, Slack reaction, and thread reply.

4. **Update message-tracker.yml** when the agent completes:
   `status: resolved`, `resolved_by: /review-pr`, `resolved_at: <timestamp>`.

**Triage watermark:**
- Use `meta.last_search_window` as the starting point for each scan.
- For unresolved PR messages: re-fetch and check for edits, new thread comments.
- Auto-resolve informational-only messages (CI pass/fail bots, deployment notices).

**Testing the watermark (manual integration test):**

There is no automated way to test the watermark — the first real `/slack scan` after
classification-rules changes IS the test. Use this checklist:

1. Before scanning: read `meta.last_search_window` from `message-tracker.yml` and note the value.
2. Run `/slack scan` against `#the-syndicate-team`.
3. Verify `meta.last_search_window` advanced to a newer timestamp.
4. Verify any new PR messages (containing `github.com/*/pull/\d+`) were classified as
   `code_review` with `suggested_skill: /review-pr`.
5. Verify PR messages where you are the author were tracked with `action_needed: false`
   and `action_reason: self-pr`.
6. Verify the `/review-pr` agent was spawned (or queued) for non-self PR messages.

See: `~/.claude/skills/review-pr/SKILL.md` for the full review workflow.

### Advanced: Agent Spawn

For complex work requiring live Slack scanning (not just tracker queries), spawn the full agent:

Prompt template: see [agent-prompt.md](../agent-prompt.md)

### Spawn Pattern
```markdown
Use Agent tool with subagent_type: general-purpose
Prompt: [contents of agent-prompt.md with variables filled in]
```

### Agent Discovery

Other agents can call `/slack help --json --quiet` to discover all available modes and their arguments at runtime. This enables dynamic integration without hardcoding mode knowledge.
