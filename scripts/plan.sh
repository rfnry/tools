#!/usr/bin/env bash
set -euo pipefail

image() {
  case "$1" in
    18) echo "pgvector/pgvector:pg18@sha256:c29f30688a9ad961691bdf0ec1650717cc132a5814619d80f80463d6e4c42e47" ;;
    *) return 1 ;;
  esac
}

plan() {
  local file=$1 planned=none seen=" " version number=0
  if [ -s "$file" ]; then
    if [ -n "$(tail -c 1 "$file")" ]; then
      echo "plan: .github/postgres does not end with a newline" >&2
      return 1
    fi
    while IFS= read -r version; do
      number=$((number + 1))
      if ! image "$version" >/dev/null; then
        echo "plan: .github/postgres line $number names ${version@Q}, a version tools pins no image for" >&2
        return 1
      fi
      if [[ $seen == *" $version "* ]]; then
        echo "plan: .github/postgres names $version twice" >&2
        return 1
      fi
      seen+="$version "
      planned=$version
    done <"$file"
  fi
  echo "postgres=$planned"
  echo "image=$(image 18)"
}

expect() {
  local name=$1 content=$2 output=$3 problem=$4 file out err
  file="$scratch/$((++cases))"
  [ "$content" = absent ] || printf "$content" >"$file"
  out=$(plan "$file" 2>"$scratch/err") || true
  err=$(cat "$scratch/err")
  if [ -n "$problem" ] && { [ -n "$out" ] || [[ $err != *"$problem"* ]]; }; then
    echo "plan: the self-test planted $name and the plan passed: $out"
    failed=1
  elif [ -z "$problem" ] && [ "$out" != "$output" ]; then
    echo "plan: the self-test's $name planned $out $err"
    failed=1
  fi
}

self_test() {
  scratch=$(mktemp -d)
  trap 'rm -rf "$scratch"' EXIT
  cases=0
  failed=0
  local none pg18
  none="postgres=none
image=$(image 18)"
  pg18="postgres=18
image=$(image 18)"
  expect "no file" absent "$none" ""
  expect "an empty file" "" "$none" ""
  expect "Postgres 18" '18\n' "$pg18" ""
  local planted=0
  while IFS='|' read -r name content problem; do
    planted=$((planted + 1))
    expect "$name" "$content" "" "$problem"
  done <<'EOF'
a last line without a newline|18|does not end with a newline
an older version|17\n|line 1 names '17'
an older version beside 18|18\n16\n|line 2 names '16'
a version with no pinned image|15\n|line 1 names '15'
a version twice|18\n18\n|names 18 twice
a blank line|18\n\n|line 2 names ''
a carriage return|18\r\n|line 1 names $'18\r'
a padded version|  18\n|line 1 names '  18'
two versions on one line|18 18\n|line 1 names '18 18'
a comment|# versions\n18\n|line 1 names '# versions'
an output in a version|18\nimage=evil\n|line 2 names 'image=evil'
a command in a version|$(touch planted)\n|line 1 names
EOF
  if [ -e planted ] || [ -e "$scratch/planted" ]; then
    echo "plan: the self-test's planted command ran"
    failed=1
  fi
  [ "$failed" = 0 ] && echo "plan: the self-test fails all $planted planted problems"
  return "$failed"
}

if [ "${1:-}" = --self-test ]; then
  self_test
  exit
fi
cd "$(git rev-parse --show-toplevel)"
plan .github/postgres
