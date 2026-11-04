import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
TEMPLATES = SCRIPTS.parent / "templates"
PLACEHOLDER = b"TOOLS_COMMIT"
HIDDEN = (".superpowers", "docs/superpowers")
GITHUB = {".github/reads", ".github/postgres", *(f".github/workflows/{t.name}" for t in TEMPLATES.iterdir())}


def files(repo: Path) -> list[str]:
    listed = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "-co", "--exclude-standard"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split("\n")
    return sorted(name for name in listed if name and (repo / name).is_file())


def postgres(repo: Path) -> list[str]:
    if not (repo / ".github" / "postgres").is_file():
        return []
    plan = subprocess.run(["bash", str(SCRIPTS / "plan.sh")], cwd=repo, capture_output=True, text=True)
    if plan.returncode == 0:
        return []
    return [line for line in plan.stderr.splitlines() if line] or ["check-repo: tools' plan.sh refused .github/postgres"]


def problems(repo: Path) -> list[str]:
    found: list[str] = []
    names = files(repo)
    for hidden in HIDDEN:
        if (repo / hidden).exists():
            found.append(f"check-repo: {hidden} exists; plans live in design/docs/plans")
    for name in names:
        if name.startswith("docs/") and (name.count("/") > 1 or not name.endswith(".md")):
            found.append(f"check-repo: {name} is not a page of the guide; docs/ holds Markdown files only")
    claude = repo / "CLAUDE.md"
    if not claude.is_file() or "[rfnry: " not in claude.read_text(encoding="utf-8"):
        found.append("check-repo: CLAUDE.md must cite the design's practices ([rfnry: <slug>])")
    versions = repo / "tools" / "versions"
    pinned = re.search(r"^TOOLS_COMMIT=([0-9a-f]{40})$", versions.read_text(encoding="utf-8"), re.MULTILINE) if versions.is_file() else None
    if pinned is None:
        found.append("check-repo: tools/versions must pin TOOLS_COMMIT=<40-hex commit>")
    if not (repo / ".github" / "reads").is_file():
        found.append("check-repo: .github/reads must list the siblings the gate checks out, one per line")
    for name in names:
        if name.startswith(".github/") and name not in GITHUB:
            found.append(f"check-repo: {name} is not ci.yml, a publish workflow of tools/templates, reads or postgres")
    if not (repo / ".github" / "workflows" / "ci.yml").is_file():
        found.append("check-repo: .github/workflows/ci.yml is missing")
    for template in sorted(TEMPLATES.iterdir()):
        workflow = repo / ".github" / "workflows" / template.name
        expected = template.read_bytes()
        if PLACEHOLDER in expected:
            if pinned is None:
                continue
            expected = expected.replace(PLACEHOLDER, pinned.group(1).encode())
        if workflow.is_file() and workflow.read_bytes() != expected:
            found.append(f"check-repo: .github/workflows/{template.name} differs from tools/templates/{template.name}")
    found.extend(postgres(repo))
    return found


COMMIT = "a" * 40
CI = (TEMPLATES / "ci.yml").read_text(encoding="utf-8").replace("TOOLS_COMMIT", COMMIT)


def planted(scratch: Path, change: str) -> Path:
    repo = scratch / str(len(list(scratch.iterdir())))
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "CLAUDE.md").write_text("see the design ([rfnry: design-leads])\n", encoding="utf-8")
    (repo / "tools").mkdir()
    (repo / "tools" / "versions").write_text(f"TOOLS_COMMIT={COMMIT}\n", encoding="utf-8")
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / ".github" / "reads").write_text("engine\n", encoding="utf-8")
    (repo / ".github" / "postgres").write_text("18\n", encoding="utf-8")
    (repo / ".github" / "workflows" / "ci.yml").write_text(CI, encoding="utf-8")
    shutil.copy(TEMPLATES / "publish-pypi.yml", repo / ".github" / "workflows" / "publish-pypi.yml")
    shutil.copy(TEMPLATES / "publish-npm.yml", repo / ".github" / "workflows" / "publish-npm.yml")
    (repo / "docs").mkdir()
    (repo / "docs" / "guide.md").write_text("# guide\n", encoding="utf-8")
    if change in CHANGES:
        _, apply, *arguments = CHANGES[change]
        apply(repo, *arguments)
    return repo


def put(repo: Path, name: str, text: str) -> None:
    (repo / name).parent.mkdir(parents=True, exist_ok=True)
    (repo / name).write_text(text, encoding="utf-8")


def remove(repo: Path, name: str) -> None:
    (repo / name).unlink()


def ci(repo: Path, old: str, new: str) -> None:
    put(repo, ".github/workflows/ci.yml", CI.replace(old, new, 1))


CHANGES = {
    "a plan in docs": ("is not a page of the guide", put, "docs/plans/plan.md", "# plan\n"),
    "an image in docs": ("is not a page of the guide", put, "docs/flow.png", "png"),
    "a .superpowers folder": (".superpowers exists", put, ".superpowers/notes.md", "# notes\n"),
    "a docs/superpowers folder": ("docs/superpowers exists", put, "docs/superpowers/notes.md", "# notes\n"),
    "no CLAUDE.md": ("must cite the design", remove, "CLAUDE.md"),
    "no citation": ("must cite the design", put, "CLAUDE.md", "# rules\n"),
    "no tools/versions": ("must pin TOOLS_COMMIT", remove, "tools/versions"),
    "no pin": ("must pin TOOLS_COMMIT", put, "tools/versions", "TOOLS_COMMIT=main\n"),
    "no reads": (".github/reads must list", remove, ".github/reads"),
    "a stray workflow": ("tests.yml is not ci.yml", put, ".github/workflows/tests.yml", "name: tests\n"),
    "a dependabot.yml": ("dependabot.yml is not ci.yml", put, ".github/dependabot.yml", "version: 2\n"),
    "a local action": ("action.yml is not ci.yml", put, ".github/actions/x/action.yml", "runs:\n  using: composite\n"),
    "a drifted publish workflow": ("publish-pypi.yml differs from", put, ".github/workflows/publish-pypi.yml", "name: changed\n"),
    "no ci.yml": ("ci.yml is missing", remove, ".github/workflows/ci.yml"),
    "a gate at another commit": ("ci.yml differs from tools/templates/ci.yml", ci, COMMIT, "b" * 40),
    "ci on drafts": ("ci.yml differs from", ci, " || !github.event.pull_request.draft", ""),
    "the draft guard in a comment": ("ci.yml differs from", ci, "    if: ", "    # "),
    "a write permission": ("ci.yml differs from", ci, "  contents: read\n", "  contents: read\n  pull-requests: write\n"),
    "a push trigger": ("ci.yml differs from", ci, "  workflow_dispatch:\n", "  workflow_dispatch:\n  push:\n"),
    "a pull_request_target trigger": ("ci.yml differs from", ci, "  pull_request:\n", "  pull_request_target:\n"),
    "a second job": ("ci.yml differs from", ci, "jobs:\n", "jobs:\n  other:\n    runs-on: ubuntu-24.04\n    steps: [{uses: actions/checkout@v4}]\n"),
    "a comment in ci.yml": ("ci.yml differs from", ci, "name: ci\n", "name: ci\n# why\n"),
    "postgres without a final newline": ("does not end with a newline", put, ".github/postgres", "18"),
    "postgres naming an older version": ("a version tools pins no image for", put, ".github/postgres", "17\n"),
    "postgres naming a version twice": ("names 18 twice", put, ".github/postgres", "18\n18\n"),
}


def self_test() -> list[str]:
    failed: list[str] = []
    with tempfile.TemporaryDirectory() as scratch:
        clean = problems(planted(Path(scratch), "clean"))
        if clean:
            failed.append(f"check-repo: the self-test's clean repository failed: {clean}")
        for change, (expected, *_) in CHANGES.items():
            if not any(expected in problem for problem in problems(planted(Path(scratch), change))):
                failed.append(f"check-repo: the self-test planted {change} and the check passed")
    return failed


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()


def main(args: list[str]) -> int:
    if args[:1] == ["--self-test"]:
        found = self_test()
        print("\n".join(found) if found else f"check-repo: the self-test fails all {len(CHANGES)} planted problems")
        return 1 if found else 0
    repo = Path(git("rev-parse", "--show-toplevel"))
    name = Path(git("rev-parse", "--path-format=absolute", "--git-common-dir")).parent.name
    found = problems(repo)
    print("\n".join(found) if found else f"check-repo: {name} has the shape of an rfnry library")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
