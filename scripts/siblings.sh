#!/usr/bin/env bash
set -euo pipefail

clone() {
  local sibling=$1 branch=$2 url="https://github.com/rfnry/$1.git" ref=main status=2
  if [ -n "$branch" ]; then
    status=0
    git ls-remote --exit-code "$url" "refs/heads/$branch" >/dev/null || status=$?
  fi
  case "$status" in
    0) ref=$branch ;;
    2) ;;
    *)
      echo "siblings: the branches of rfnry/$sibling cannot be read" >&2
      return 1
      ;;
  esac
  git clone -q --depth 1 --branch "$ref" "$url" "../$sibling" || {
    echo "siblings: rfnry/$sibling cannot be cloned at $ref" >&2
    return 1
  }
}

siblings() {
  local branch=$1 sibling seen=" " number=0
  [ -f .github/reads ] || return 0
  while IFS= read -r sibling || [ -n "$sibling" ]; do
    number=$((number + 1))
    if ! [[ $sibling =~ ^[a-z][a-z0-9-]*$ ]]; then
      echo "siblings: .github/reads line $number names ${sibling@Q}, which is not a repository of rfnry" >&2
      return 1
    fi
    if [[ $seen == *" $sibling "* ]]; then
      echo "siblings: .github/reads names $sibling twice" >&2
      return 1
    fi
    seen+="$sibling "
    clone "$sibling" "$branch" || return 1
  done <.github/reads
}

remote() {
  local repo="$scratch/remote/$1.git" branch
  git init -q -b main "$repo"
  git -C "$repo" -c user.name=self-test -c user.email=self-test@rfnry commit -q --allow-empty -m main
  for branch in "${@:2}"; do
    git -C "$repo" checkout -q -b "$branch"
    git -C "$repo" -c user.name=self-test -c user.email=self-test@rfnry commit -q --allow-empty -m "$branch"
    git -C "$repo" checkout -q main
  done
}

run() {
  local reads=$1 branch=$2
  rm -rf "$scratch/work"
  mkdir -p "$scratch/work/repo/.github"
  [ "$reads" = absent ] || printf "$reads" >"$scratch/work/repo/.github/reads"
  (cd "$scratch/work/repo" && siblings "$branch") 2>"$scratch/err"
}

at() {
  git -C "$scratch/work/$1" log -1 --format=%s 2>/dev/null || echo absent
}

cloned() {
  local name=$1 reads=$2 branch=$3 expected=$4 sibling found=""
  if run "$reads" "$branch"; then
    for sibling in $(ls "$scratch/work"); do
      [ "$sibling" = repo ] || found+="$sibling:$(at "$sibling") "
    done
  else
    found="refused: $(cat "$scratch/err")"
  fi
  if [ "$found" != "$expected" ]; then
    echo "siblings: the self-test's $name cloned '$found', not '$expected'"
    failed=1
  fi
}

refused() {
  local name=$1 reads=$2 branch=$3 expected=$4
  if run "$reads" "$branch" || [[ $(cat "$scratch/err") != *"$expected"* ]]; then
    echo "siblings: the self-test planted $name and the clone passed"
    failed=1
  fi
}

self_test() {
  scratch=$(mktemp -d)
  trap 'rm -rf "$scratch"' EXIT
  failed=0
  remote engine track
  remote memory feature/track
  remote thread
  export GIT_CONFIG_COUNT=1
  export GIT_CONFIG_KEY_0="url.file://$scratch/remote/.insteadOf"
  export GIT_CONFIG_VALUE_0=https://github.com/rfnry/

  cloned "siblings on a branch only engine has" 'engine\nmemory\nthread\n' track "engine:track memory:main thread:main "
  cloned "siblings on no branch" 'engine\nmemory\n' "" "engine:main memory:main "
  cloned "siblings on a branch none has" 'engine\n' other "engine:main "
  cloned "repository without .github/reads" absent track ""
  cloned "empty .github/reads" "" track ""
  cloned "last sibling without a newline" 'memory\nthread' "" "memory:main thread:main "

  local planted=0
  while IFS='|' read -r name reads branch expected; do
    planted=$((planted + 1))
    refused "$name" "$reads" "$branch" "$expected"
  done <<'EOF'
a path for a sibling|../engine\n||which is not a repository of rfnry
a URL for a sibling|https://example.com/x\n||which is not a repository of rfnry
a blank line|engine\n\nthread\n||line 2 names ''
a sibling twice|engine\nengine\n||names engine twice
a sibling whose branches cannot be read|missing\n|track|the branches of rfnry/missing cannot be read
a sibling that cannot be cloned|missing\n||rfnry/missing cannot be cloned at main
EOF
  [ "$failed" = 0 ] && echo "siblings: the self-test fails all $planted planted problems"
  return "$failed"
}

if [ "${1:-}" = --self-test ]; then
  self_test
  exit
fi
cd "$(git rev-parse --show-toplevel)"
siblings "${GITHUB_HEAD_REF:-${GITHUB_REF_NAME:-}}"
