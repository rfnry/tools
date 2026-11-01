#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "protect: usage: protect.sh <repository>, as rfnry/<name>" >&2
  exit 2
fi
repository=$1

ruleset=$(cat <<'EOF'
{
  "name": "main",
  "target": "branch",
  "enforcement": "active",
  "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
  "rules": [
    {"type": "deletion"},
    {"type": "non_fast_forward"},
    {
      "type": "required_status_checks",
      "parameters": {
        "strict_required_status_checks_policy": false,
        "required_status_checks": [{"context": "ci / gate"}]
      }
    }
  ]
}
EOF
)

existing=$(gh api "repos/$repository/rulesets" --jq '.[] | select(.name == "main") | .id')
if [ -n "$existing" ]; then
  gh api --method PUT "repos/$repository/rulesets/$existing" --input - <<<"$ruleset" >/dev/null
  echo "protect: $repository's main ruleset is updated"
else
  gh api --method POST "repos/$repository/rulesets" --input - <<<"$ruleset" >/dev/null
  echo "protect: $repository's main ruleset is created"
fi
