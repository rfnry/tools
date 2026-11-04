# tools

Before working here, read the design, `rfnry/design` (`PRACTICES.md`, `STACK.md`): it holds the rules this repository
implements (`[rfnry: one-ci-shape]`, `[rfnry: ci-least-access]`, `[rfnry: code-documents-itself]`,
`[rfnry: repo-shape]`, `[rfnry: landing]`).

- Every library pins one commit of this repository: `TOOLS_COMMIT` in its `tools/versions`, and the same commit in its
  `ci.yml`. Pins move by hand until Renovate is installed on the organization; `default.json` is the preset each
  repository extends, and `renovate.json` this repository's own (its Actions and the pgvector digests of `plan.sh`).
- `gate.yml` runs one `test` job, on Postgres 18 when the caller's `.github/postgres` names it and with no database
  URL for a repository that stores nothing, on the image pinned by digest in `scripts/plan.sh`; a last job, `gate`,
  passes only when `test` did, and is the one check `main` requires. Each job fetches this repository beside the caller
  at the caller's `TOOLS_COMMIT`; on this repository's own CI the checkout is already the tools beside, and nothing is
  fetched. `plan` runs `pin.sh` (that commit is 40 hex, is the one `ci.yml` calls, and is what was fetched) and
  `plan.sh` (`.github/postgres` names only 18, the one version pinned here, once, the file ending in a newline).
  `test` clones the siblings `.github/reads` names with `siblings.sh`, each at the pull request's branch when the sibling
  has a branch of that name, else at `main`, and runs `scripts/gate.sh`, which acts on the repository it runs in
  (`git rev-parse --show-toplevel`): `check-repo.py`, `lint-comment.py`, the Python gate (`uv lock --check` first) and
  the TypeScript gate (`test:integration` too where a package has it); a repository without `packages/` runs its own
  `make check`. Locally, from a library's primary checkout: `bash ../tools/scripts/gate.sh`; from one of its
  worktrees: `bash ../../../tools/scripts/gate.sh`.
- `check-repo.py` holds a library's `.github/` to `ci.yml`, the publish workflows, `reads` and `postgres`, and checks
  `postgres` with `plan.sh`.
- `templates/` holds `ci.yml`, with `TOOLS_COMMIT` where the commit goes, and the publish workflows. A library's
  `ci.yml` must equal `templates/ci.yml` once the commit of its `tools/versions` is filled in, and its publish
  workflows must equal theirs byte for byte, since trusted publishing takes no reusable workflow.
- `scripts/protect.sh rfnry/<name>` puts the `main` ruleset on a repository: the `ci / gate` check, reported by GitHub
  Actions, required on a head up to date with `main`; linear history; no force-push; no deletion. It changes a
  repository's settings: run it only on the owner's word.
- `make check` is this repository's gate: each script's `--self-test`, the comment lint on itself, `bash -n` on every
  shell script, actionlint on the workflows and the templates (a pinned release, its checksum verified), and
  renovate-config-validator on `default.json` and `renovate.json` (pinned, through `npx`). A script proves it can
  fail before it runs (`[rfnry: tests-can-fail]`): its self-test plants every rule it enforces.
- Code here carries no comments (`[rfnry: code-documents-itself]`).

## How work lands

`[rfnry: worktree-per-track]`, `[rfnry: draft-prs]`, `[rfnry: landing]`, `[rfnry: commit-messages]`,
`[rfnry: no-attribution-trailers]`. A change here reaches a library only when its pin moves.
