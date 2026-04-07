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
        "clientId": "<YOUR_SLACK_APP_CLIENT_ID>",
        "callbackPort": 3118
      }
    }
  }
}
```

To get a Slack App Client ID:
1. Go to [api.slack.com/apps](https://api.slack.com/apps)
2. Create a new app (or use an existing one)
3. Configure OAuth scopes: `channels:read`, `channels:history`, `groups:read`, `groups:history`, `im:read`, `im:history`, `mpim:read`, `mpim:history`, `users:read`, `search:read`, `chat:write`, `files:read`
4. Copy the Client ID

## Step 2.5: Authenticate for Download Mode (OAuth)

The `download` mode requires direct Slack Web API access for file downloads. Run the one-time OAuth setup:

```bash
python scripts/slack_oauth.py \
  --client-id YOUR_SLACK_APP_CLIENT_ID \
  --client-secret YOUR_SLACK_APP_CLIENT_SECRET \
  --company amira
```

This will:
1. Open your browser to Slack's authorization page
2. Request all scopes needed by x-slack (read, send, reply, search, download)
3. Save the token to `~/.claude/companies/amira/data/slack/token.json`
4. Write a sourceable env file at `~/.claude/companies/amira/data/slack/slack-env.sh`

**The download mode will automatically find and use the saved token** — no env var configuration needed.

Optional — for tools outside Claude Code that need the token:
```bash
source ~/.claude/companies/amira/data/slack/slack-env.sh
```

Or add that line to your `~/.bashrc` / `~/.zprofile` for persistence.

**Slack app requirements**: Use the same app as Step 2. Ensure `files:read` scope is included (added to Step 2 scope list above). The app redirect URI must include `http://localhost:3119/callback`.

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
