# tools

Before working here, read the design, `rfnry/design` (`PRACTICES.md`, `STACK.md`): it holds the rules this repository
implements (`[rfnry: one-ci-shape]`, `[rfnry: ci-least-access]`, `[rfnry: code-documents-itself]`,
`[rfnry: repo-shape]`, `[rfnry: landing]`).

- Every library pins one commit of this repository: `TOOLS_COMMIT` in its `tools/versions`, and the same commit in its
  `ci.yml`'s `uses: rfnry/tools/.github/workflows/gate.yml@<commit>`. Renovate proposes each bump, as a draft.
- `gate.yml` runs the gate once per Postgres version the caller's `.github/postgres` names (once, with none, for a
  repository that stores nothing), each on its image pinned by digest here; a last job, `gate`, passes only when every
  run did, and is the one check `main` requires. Each run checks the caller out, fetches this repository at the
  caller's `TOOLS_COMMIT` beside it, clones the siblings the caller's `.github/reads` names, and runs
  `scripts/gate.sh`, which acts on the repository it runs in
  (`git rev-parse --show-toplevel`): `check-repo.py`, `lint-comment.py`, the Python gate and the TypeScript gate; a
  repository without `packages/` runs its own `make check`. Locally, from a library's primary checkout: `bash ../tools/scripts/gate.sh`; from one of its worktrees: `bash ../../../tools/scripts/gate.sh`.
- `templates/` holds the publish workflows; a library's copies must equal them, byte for byte, since trusted publishing
  takes no reusable workflow.
- `scripts/protect.sh rfnry/<name>` puts the `main` ruleset on a repository (the `ci / gate` check required, no
  force-push, no deletion). It changes a repository's settings: run it only on the owner's word.
- `make check` is this repository's gate: each script's `--self-test`, the comment lint on itself, `bash -n` on every
  shell script, and the Renovate preset parsing. A script proves it can fail before it runs
  (`[rfnry: tests-can-fail]`).
- Code here carries no comments (`[rfnry: code-documents-itself]`).

## How work lands

`[rfnry: worktree-per-track]`, `[rfnry: draft-prs]`, `[rfnry: landing]`, `[rfnry: commit-messages]`,
`[rfnry: no-attribution-trailers]`. A change here reaches a library only when its pin moves.
