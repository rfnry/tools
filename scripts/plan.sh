#!/usr/bin/env bash
set -euo pipefail

image() {
  case "$1" in
    16) echo "pgvector/pgvector:pg16@sha256:0dd3149a06e4579a0d70d8fef9945636cd514005e7237deb27f9b67886f8dc4f" ;;
    17) echo "pgvector/pgvector:pg17@sha256:7d0a41464797aeb9862dfdc0bbf1526b82cfd324cdd8036df19e3545f4a9ccb8" ;;
    18) echo "pgvector/pgvector:pg18@sha256:c29f30688a9ad961691bdf0ec1650717cc132a5814619d80f80463d6e4c42e47" ;;
    *) return 1 ;;
  esac
}

plan() {
  local file=$1 entries=() seen=" " version number=0
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
      entries+=("{\"version\":\"$version\",\"image\":\"$(image "$version")\"}")
    done <"$file"
  fi
  [ "${#entries[@]}" -gt 0 ] || entries=("{\"version\":\"none\",\"image\":\"$(image 16)\"}")
  echo "postgres=[$(IFS=,; echo "${entries[*]}")]"
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
  elif [ -z "$problem" ] && [ "$out" != "postgres=[$output]" ]; then
    echo "plan: the self-test's $name planned $out $err"
    failed=1
  fi
}

self_test() {
  scratch=$(mktemp -d)
  trap 'rm -rf "$scratch"' EXIT
  cases=0
  failed=0
  local none pg16 pg17 pg18
  none="{\"version\":\"none\",\"image\":\"$(image 16)\"}"
  pg16="{\"version\":\"16\",\"image\":\"$(image 16)\"}"
  pg17="{\"version\":\"17\",\"image\":\"$(image 17)\"}"
  pg18="{\"version\":\"18\",\"image\":\"$(image 18)\"}"
  expect "no file" absent "$none" ""
  expect "an empty file" "" "$none" ""
  expect "three versions" '16\n17\n18\n' "$pg16,$pg17,$pg18" ""
  expect "one version" '17\n' "$pg17" ""
  local planted=0
  while IFS='|' read -r name content problem; do
    planted=$((planted + 1))
    expect "$name" "$content" "" "$problem"
  done <<'EOF'
a last line without a newline|16\n17\n18|does not end with a newline
one version without a newline|17|does not end with a newline
a version with no pinned image|15\n16\n|line 1 names '15'
an unpinned last version|16\n15\n|line 2 names '15'
a version twice|16\n16\n|names 16 twice
a blank line|16\n\n17\n|line 2 names ''
a carriage return|16\r\n|line 1 names $'16\r'
a padded version|  16\n|line 1 names '  16'
two versions on one line|16 17\n|line 1 names '16 17'
a comment|# versions\n16\n|line 1 names '# versions'
JSON in a version|16","image":"evil\n|line 1 names
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
