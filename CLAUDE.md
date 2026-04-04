# slack-expert — Claude Code Instructions

## Data Directory

Skill data is company-scoped:

```
~/.claude/companies/{company}/data/
├── people.yml                        # Shared: team identity
├── faq.yml                           # Shared: knowledge base
├── categories.yml                    # Shared: triage categories
└── slack/
    ├── message-tracker.yml           # Active messages + channel config
    ├── message-tracker-archive.yml   # Resolved messages
    └── classification-rules.yml      # Triage rules
```

## Company Resolution

Company name is determined from the user's current working directory.
Match the cwd against a `companies/` entry in your global CLAUDE.md:

```markdown
# In your global ~/.claude/CLAUDE.md:
# If working directory is under ~/repos/mycompany/, apply: company = mycompany
```

If company cannot be resolved from cwd, prompt the user:
```
Which company context? (e.g., type "acme")
```

## MCP Dependencies

**Required:**
- `mcp__slack__*` — Slack MCP server for all messaging operations

**Optional (recommended):**
- `mcp__atlassian-redacted__lookup_jira_account_id` — PII-safe Jira user lookup used in scan mode to populate `jira_id` in `people.yml`

## Install

```bash
./install.sh   # Unix/Mac/WSL
.\install.ps1  # Windows
```

## Skill Location

After install, the skill lives at:
```
~/.claude/skills/x-slack/SKILL.md
~/.claude/skills/x-slack/agent-prompt.md
```

## First-Run Bootstrap

If `message-tracker.yml` doesn't exist, the skill creates it from the schema and prompts the user to configure their channel tiers and people.
