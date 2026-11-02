#!/usr/bin/env bash
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

pin() {
  local repo=$1 tools=$2 commit uses head
  if [ ! -f "$repo/tools/versions" ]; then
    echo "pin: tools/versions is missing" >&2
    return 1
  fi
  commit=$(sed -n 's/^TOOLS_COMMIT=//p' "$repo/tools/versions")
  if ! [[ $commit =~ ^[0-9a-f]{40}$ ]]; then
    echo "pin: tools/versions must pin TOOLS_COMMIT=<40-hex commit> once, not '$commit'" >&2
    return 1
  fi
  if [ ! -f "$repo/.github/workflows/ci.yml" ]; then
    echo "pin: .github/workflows/ci.yml is missing" >&2
    return 1
  fi
  uses=$(grep -o 'rfnry/tools/\.github/workflows/gate\.yml@[^[:space:]]*' "$repo/.github/workflows/ci.yml" || true)
  if [ "$uses" != "rfnry/tools/.github/workflows/gate.yml@$commit" ]; then
    echo "pin: ci.yml must call rfnry/tools/.github/workflows/gate.yml once, at $commit, the commit tools/versions pins" >&2
    return 1
  fi
  head=$(git -C "$tools" rev-parse HEAD)
  if [ "$head" != "$commit" ]; then
    echo "pin: the tools beside the repository are at $head, not $commit" >&2
    return 1
  fi
}

planted() {
  local name=$1 versions=$2 ci=$3 at=$4 repo
  repo="$scratch/$((++cases))"
  mkdir -p "$repo/tools" "$repo/.github/workflows"
  [ "$versions" = absent ] || printf '%s\n' "$versions" >"$repo/tools/versions"
  [ "$ci" = absent ] || printf '%s\n' "$ci" >"$repo/.github/workflows/ci.yml"
  git -C "$scratch/tools" checkout -q "$at"
  pin "$repo" "$scratch/tools" 2>"$scratch/err"
}

refused() {
  local name=$1 expected=$2
  shift 2
  if planted "$name" "$@" || [[ $(cat "$scratch/err") != *"$expected"* ]]; then
    echo "pin: the self-test planted $name and the pin passed"
    failed=1
  fi
}

self_test() {
  scratch=$(mktemp -d)
  trap 'rm -rf "$scratch"' EXIT
  cases=0
  failed=0
  git init -q "$scratch/tools"
  git -C "$scratch/tools" -c user.name=self-test -c user.email=self-test@rfnry commit -q --allow-empty -m one
  local one two versions call
  one=$(git -C "$scratch/tools" rev-parse HEAD)
  git -C "$scratch/tools" -c user.name=self-test -c user.email=self-test@rfnry commit -q --allow-empty -m two
  two=$(git -C "$scratch/tools" rev-parse HEAD)
  versions="# renovate: datasource=git-refs depName=https://github.com/rfnry/tools branch=main
TOOLS_COMMIT=$one"
  call="    uses: rfnry/tools/.github/workflows/gate.yml@$one"

  if ! planted "the pinned commit" "$versions" "$call" "$one"; then
    echo "pin: the self-test's pinned commit failed: $(cat "$scratch/err")"
    failed=1
  fi
  refused "no tools/versions" "tools/versions is missing" absent "$call" "$one"
  refused "an empty commit" "not ''" "TOOLS_COMMIT=" "$call" "$one"
  refused "a branch for the commit" "not 'main'" "TOOLS_COMMIT=main" "$call" "$one"
  refused "a short commit" "must pin TOOLS_COMMIT" "TOOLS_COMMIT=${one:0:12}" "${call:0:-28}" "$one"
  refused "an option for the commit" "must pin TOOLS_COMMIT" "TOOLS_COMMIT=--upload-pack=x" "$call" "$one"
  refused "two commits" "must pin TOOLS_COMMIT" "$versions
TOOLS_COMMIT=$two" "$call" "$one"
  refused "no ci.yml" "ci.yml is missing" "$versions" absent "$one"
  refused "ci.yml at another commit" "at $one, the commit" "$versions" "${call/$one/$two}" "$one"
  refused "ci.yml calling the gate twice" "once, at $one" "$versions" "$call
  other:
    uses: rfnry/tools/.github/workflows/gate.yml@$two" "$one"
  refused "ci.yml not calling the gate" "must call rfnry/tools" "$versions" "    uses: ./.github/workflows/gate.yml" "$one"
  refused "the tools at another commit" "are at $two, not $one" "$versions" "$call" "$two"
  [ "$failed" = 0 ] && echo "pin: the self-test fails all $((cases - 1)) planted problems"
  return "$failed"
}

if [ "${1:-}" = --self-test ]; then
  self_test
  exit
fi
pin "$(git rev-parse --show-toplevel)" "$here/.."
