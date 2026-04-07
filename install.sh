#!/usr/bin/env bash
# slack-expert install script (Unix/Mac/WSL)
set -e

SKILL_NAME="x-slack"
SKILL_DIR="$HOME/.claude/skills/$SKILL_NAME"

echo "=== slack-expert installer ==="
echo ""

# 1. Check prerequisites
if ! command -v claude &>/dev/null; then
  echo "ERROR: Claude Code CLI not found. Install it first: https://github.com/anthropics/claude-code"
  exit 1
fi
echo "✓ Claude Code CLI found"

# 2. Prompt for company name
read -rp "Enter company name (used for data directory, e.g. acme): " COMPANY
COMPANY="${COMPANY:-mycompany}"
echo "Company: $COMPANY"

DATA_DIR="$HOME/.claude/companies/$COMPANY/data"
SLACK_DATA_DIR="$DATA_DIR/slack"

# 3. Create data directories if missing
mkdir -p "$SLACK_DATA_DIR"
echo "✓ Data directory: $SLACK_DATA_DIR"

# 4. Copy shared template files (never overwrite existing)
for f in templates/data/*.template; do
  target="$DATA_DIR/$(basename "$f" .template)"
  if [ ! -f "$target" ]; then
    cp "$f" "$target"
    echo "  Created: $target"
  else
    echo "  Skipped (exists): $target"
  fi
done

# 5. Copy slack-specific template files
for f in templates/data/slack/*.template; do
  target="$SLACK_DATA_DIR/$(basename "$f" .template)"
  if [ ! -f "$target" ]; then
    cp "$f" "$target"
    echo "  Created: $target"
  else
    echo "  Skipped (exists): $target"
  fi
done

# 6. Install skill (remove-and-recopy for clean updates)
rm -rf "$SKILL_DIR"
mkdir -p "$SKILL_DIR"
cp .claude/skills/$SKILL_NAME/* "$SKILL_DIR/"
echo "✓ Skill installed: $SKILL_DIR"

# 7. Copy scripts directory
SCRIPTS_DIR="$HOME/.claude/skills/$SKILL_NAME/scripts"
rm -rf "$SCRIPTS_DIR"
cp -r scripts "$SCRIPTS_DIR"
echo "✓ Scripts installed: $SCRIPTS_DIR"

# 8. Create download cache directory
DOWNLOADS_DIR="$SLACK_DATA_DIR/downloads"
mkdir -p "$DOWNLOADS_DIR"
chmod 700 "$DOWNLOADS_DIR"
echo "✓ Download cache: $DOWNLOADS_DIR"

echo ""
echo "=== Installation complete ==="
echo ""
echo "Next steps:"
echo "  1. Configure Slack MCP OAuth — see docs/setup.md"
echo "  2. Run OAuth setup for download mode:"
echo "     python $SCRIPTS_DIR/slack_oauth.py --client-id YOUR_ID --client-secret YOUR_SECRET --company $COMPANY"
echo "  3. Edit $DATA_DIR/people.yml with your team"
echo "  4. Edit $SLACK_DATA_DIR/message-tracker.yml with your channels"
echo "  5. Run: /x-slack help"
