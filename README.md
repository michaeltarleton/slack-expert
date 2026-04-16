# slack-expert

Unified Slack interface for Claude Code — messaging, channel/user management, triage, response tracking, and institutional knowledge.

## Features

- **18 modes**: send, read, thread, channels, users, download, scan, status, archive, faq, faq add, reply, search, context, update, link, who, help
- **File download**: fetch Slack file attachments, convert to markdown, 72h cache — HTML, PDF, Excel, CSV, images (OCR)
- **Priority-tier scanning**: CRITICAL → IMPORTANT → NORMAL
- **Response tracking**: message-tracker with archive lifecycle
- **FAQ knowledge base**: dedup, relation scoring, Jira cross-reference
- **Agent-friendly**: `--json --quiet` for structured output
- **Shared data**: integrates with jira-expert via `people.yml`, `faq.yml`, `categories.yml`

## Prerequisites

- [Claude Code CLI](https://github.com/anthropics/claude-code) installed
- Slack MCP server configured (see [docs/setup.md](docs/setup.md))

## Install

### Unix / Mac / WSL

```bash
git clone https://github.com/YOUR_ORG/slack-expert.git
cd slack-expert
./install.sh
```

### Windows (PowerShell)

```powershell
git clone https://github.com/YOUR_ORG/slack-expert.git
cd slack-expert
.\install.ps1
```

The installer will:
1. Prompt for your company name
2. Create `~/.claude/companies/{company}/data/slack/`
3. Copy template data files (never overwrites existing data)
4. Install the skill to `~/.claude/skills/slack/`

## Quick Start

```
/slack scan              # Full channel sweep
/slack status            # Show active tracker items
/slack read #general     # Read recent messages
/slack send #general "Hello team"
/slack faq onboarding    # Search FAQ
/slack help              # All modes
```

## Configuration

After install, edit your data files:

| File | Purpose |
|------|---------|
| `~/.claude/companies/{company}/data/people.yml` | Team members (Slack + Jira IDs) |
| `~/.claude/companies/{company}/data/slack/classification-rules.yml` | Triage rules |
| `~/.claude/companies/{company}/data/slack/message-tracker.yml` | Channel config and active messages |

See [docs/setup.md](docs/setup.md) for detailed configuration.

## Shared Data

`people.yml`, `faq.yml`, and `categories.yml` are **shared with jira-expert**. If you install both, the templates are identical — only copy them once.

## Docs

- [Setup Guide](docs/setup.md) — includes OAuth setup for download mode
- [All Modes](docs/modes.md)
- [Agent Integration](docs/agent-integration.md)

## Data Directory

```
~/.claude/companies/{company}/data/
├── people.yml                        # Shared: identity + Jira/Slack IDs
├── faq.yml                           # Shared: Q&A knowledge base
├── categories.yml                    # Shared: triage category definitions
└── slack/
    ├── message-tracker.yml           # Active messages, channels, triage rules
    ├── message-tracker-archive.yml   # Resolved messages (append-only)
    ├── classification-rules.yml      # Slack triage rules
    ├── token.json                    # OAuth token (written by slack_oauth.py)
    ├── slack-env.sh                  # Sourceable env file (written by slack_oauth.py)
    └── downloads/                    # File download cache (72h TTL)
        ├── F07XXXXXX.md              # Converted markdown content
        └── F07XXXXXX.meta.json       # Cache metadata + expiry
```
