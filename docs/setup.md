# Setup Guide — slack-expert

## Prerequisites

1. [Claude Code CLI](https://github.com/anthropics/claude-code) installed
2. A Slack workspace you have access to
3. A Slack MCP server configured (see below)

## Step 1: Run the Installer

```bash
./install.sh     # Unix/Mac/WSL
.\install.ps1    # Windows
```

This creates your data directory and copies template files.

## Step 2: Configure Slack MCP

Add the Slack MCP server to your project's `.mcp.json`:

```json
{
  "mcpServers": {
    "slack": {
      "type": "http",
      "url": "https://mcp.slack.com/mcp",
      "oauth": {
        "clientId": "1601185624273.8899143856786",
        "callbackPort": 3118
      }
    }
  }
}
```

This uses Slack's official MCP app — no custom Slack app required.

## Step 2.5: Authenticate for Download Mode (OAuth)

The `download` mode uses a separate user token for direct Slack Web API file access. Run the one-time OAuth setup:

```bash
# Default — uses the official Slack MCP app (no credentials needed)
python scripts/slack_oauth.py --company amira

# Custom Slack app (optional — only if you want your own app)
python scripts/slack_oauth.py --client-id YOUR_ID --client-secret YOUR_SECRET --company amira
```

This will:
1. Open your browser to Slack's authorization page
2. Request all scopes needed by x-slack (read, send, reply, search, download)
3. Save the token to `~/.claude/companies/{company}/data/slack/token.json`
4. Write a sourceable env file at `~/.claude/companies/{company}/data/slack/slack-env.sh`

**The download mode will automatically find and use the saved token** — no env var configuration needed.

> **Note**: The OAuth script uses port 3118, which is the same port as Claude Code's Slack MCP connection.
> If the MCP is connected when you run the script, you'll get a "port in use" error.
> Disconnect the Slack MCP in Claude Code first, run the script, then reconnect.

Optional — for tools outside Claude Code that need the token:
```bash
source ~/.claude/companies/amira/data/slack/slack-env.sh
```

Or add that line to your `~/.bashrc` / `~/.zprofile` for persistence.

## Step 3: Configure Your Data Files

### people.yml

```
~/.claude/companies/{company}/data/people.yml
```

Add your team members. Get their Slack IDs by running:
```
/x-slack users Alice
```

Then add to people.yml:
```yaml
alice_smith:
  name: Alice Smith
  slack_id: UXXXXXXXXXX      # From the users command output
  jira_id: null              # Fill in after running /x-jira find-user Alice
  roles: [developer]
  teams: [PROJ]
  topics: [auth, backend]
  comm_pref: slack_dm
```

### message-tracker.yml

```
~/.claude/companies/{company}/data/slack/message-tracker.yml
```

1. Set your `owner_slack_id` (run `/x-slack users <your name>`)
2. Add channels to monitor:
```yaml
channels:
  - id: C0XXXXXXXXX         # Get from /x-slack channels
    name: alerts-critical
    tier: CRITICAL
    slack_connect: false
    description: "Critical alerts"
```

### classification-rules.yml

```
~/.claude/companies/{company}/data/slack/classification-rules.yml
```

Configure your channel tiers and keyword rules for auto-classification.

## Step 4: Verify Installation

```
/x-slack help
```

Should list all 18 modes.

## Step 5: First Scan

```
/x-slack scan
```

This will scan all configured channels and populate `message-tracker.yml`.

## Jira Integration (Optional)

If you also have `jira-expert` installed, the shared `people.yml` file will be populated with Jira IDs during scan mode (lazy lookup via `atlassian-redacted`).

## Troubleshooting

**"mcp__slack__ not found"**: Verify your `.mcp.json` is in the project root and Claude Code has reloaded.

**"No channels configured"**: Edit `message-tracker.yml` and add at least one channel.

**Slack Connect write errors**: The skill automatically detects Slack Connect channels and will provide permalink + copyable text instead of attempting to send.
