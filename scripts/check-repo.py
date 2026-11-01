import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
PINNED = re.compile(r"^\s*-?\s*uses:\s*(\S+)", re.MULTILINE)
SHA = re.compile(r"@[0-9a-f]{40}$")
GATE = re.compile(r"uses:\s*rfnry/tools/\.github/workflows/gate\.yml@([0-9a-f]{40})")
HIDDEN = (".superpowers", "docs/superpowers")


def files(repo: Path) -> list[str]:
    listed = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "-co", "--exclude-standard"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split("\n")
    return sorted(name for name in listed if name and (repo / name).is_file())


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
    workflows = sorted(name for name in names if name.startswith(".github/workflows/"))
    allowed = {".github/workflows/ci.yml", *(f".github/workflows/{t.name}" for t in TEMPLATES.iterdir())}
    for name in workflows:
        if name not in allowed:
            found.append(f"check-repo: {name} is not ci.yml or a publish workflow of tools/templates")
    for template in sorted(TEMPLATES.iterdir()):
        name = f".github/workflows/{template.name}"
        if name in workflows and (repo / name).read_bytes() != template.read_bytes():
            found.append(f"check-repo: {name} differs from tools/templates/{template.name}")
    ci = repo / ".github" / "workflows" / "ci.yml"
    if not ci.is_file():
        found.append("check-repo: .github/workflows/ci.yml is missing")
    else:
        text = ci.read_text(encoding="utf-8")
        gate = GATE.search(text)
        if gate is None:
            found.append("check-repo: ci.yml must call rfnry/tools/.github/workflows/gate.yml at a commit")
        elif pinned is not None and gate.group(1) != pinned.group(1):
            found.append("check-repo: ci.yml calls the gate at another commit than tools/versions pins")
        if "!github.event.pull_request.draft" not in text:
            found.append("check-repo: ci.yml must run nothing on a draft pull request")
    for name in workflows:
        text = (repo / name).read_text(encoding="utf-8")
        if not re.search(r"^permissions:\s*\n\s+contents: read", text, re.MULTILINE):
            found.append(f"check-repo: {name} must grant contents: read at the top")
        for action in PINNED.findall(text):
            if not action.startswith("./") and not SHA.search(action):
                found.append(f"check-repo: {name} uses {action}, which is not pinned by commit")
    return found


GOOD_CI = """name: ci
on:
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review]
  workflow_dispatch:
permissions:
  contents: read
jobs:
  ci:
    if: ${{ github.event_name == 'workflow_dispatch' || !github.event.pull_request.draft }}
    uses: rfnry/tools/.github/workflows/gate.yml@COMMIT
"""


def planted(scratch: Path, change: str) -> Path:
    repo = scratch / change
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    commit = "a" * 40
    (repo / "CLAUDE.md").write_text("see the design ([rfnry: design-leads])\n", encoding="utf-8")
    (repo / "tools").mkdir()
    (repo / "tools" / "versions").write_text(f"TOOLS_COMMIT={commit}\n", encoding="utf-8")
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / ".github" / "reads").write_text("", encoding="utf-8")
    (repo / ".github" / "workflows" / "ci.yml").write_text(GOOD_CI.replace("COMMIT", commit), encoding="utf-8")
    shutil.copy(TEMPLATES / "publish-pypi.yml", repo / ".github" / "workflows" / "publish-pypi.yml")
    (repo / "docs").mkdir()
    (repo / "docs" / "guide.md").write_text("# guide\n", encoding="utf-8")
    if change == "a plan in docs":
        (repo / "docs" / "plans").mkdir()
        (repo / "docs" / "plans" / "plan.md").write_text("# plan\n", encoding="utf-8")
    elif change == "a .superpowers folder":
        (repo / ".superpowers").mkdir()
    elif change == "no citation":
        (repo / "CLAUDE.md").write_text("# rules\n", encoding="utf-8")
    elif change == "no pin":
        (repo / "tools" / "versions").write_text("TOOLS_COMMIT=main\n", encoding="utf-8")
    elif change == "no reads":
        (repo / ".github" / "reads").unlink()
    elif change == "a stray workflow":
        (repo / ".github" / "workflows" / "tests.yml").write_text("permissions:\n  contents: read\n", encoding="utf-8")
    elif change == "a drifted publish workflow":
        (repo / ".github" / "workflows" / "publish-pypi.yml").write_text("name: changed\n", encoding="utf-8")
    elif change == "a gate at another commit":
        ci = GOOD_CI.replace("COMMIT", "b" * 40)
        (repo / ".github" / "workflows" / "ci.yml").write_text(ci, encoding="utf-8")
    elif change == "ci on drafts":
        ci = GOOD_CI.replace("COMMIT", commit).replace(" || !github.event.pull_request.draft", "")
        (repo / ".github" / "workflows" / "ci.yml").write_text(ci, encoding="utf-8")
    elif change == "an action by tag":
        ci = GOOD_CI.replace("COMMIT", commit) + "      - uses: actions/checkout@v7\n"
        (repo / ".github" / "workflows" / "ci.yml").write_text(ci, encoding="utf-8")
    elif change == "write permissions":
        ci = GOOD_CI.replace("COMMIT", commit).replace("contents: read", "contents: write")
        (repo / ".github" / "workflows" / "ci.yml").write_text(ci, encoding="utf-8")
    return repo


CHANGES = {
    "a plan in docs": "is not a page of the guide",
    "a .superpowers folder": ".superpowers exists",
    "no citation": "must cite the design",
    "no pin": "must pin TOOLS_COMMIT",
    "no reads": ".github/reads must list",
    "a stray workflow": "is not ci.yml or a publish workflow",
    "a drifted publish workflow": "differs from tools/templates",
    "a gate at another commit": "at another commit than tools/versions",
    "ci on drafts": "run nothing on a draft",
    "an action by tag": "not pinned by commit",
    "write permissions": "must grant contents: read",
}


def self_test() -> list[str]:
    failed: list[str] = []
    with tempfile.TemporaryDirectory() as scratch:
        clean = problems(planted(Path(scratch), "clean"))
        if clean:
            failed.append(f"check-repo: the self-test's clean repository failed: {clean}")
        for change, expected in CHANGES.items():
            if not any(expected in problem for problem in problems(planted(Path(scratch), change))):
                failed.append(f"check-repo: the self-test planted {change} and the check passed")
    return failed


def main(args: list[str]) -> int:
    if args[:1] == ["--self-test"]:
        found = self_test()
        print("\n".join(found) if found else f"check-repo: the self-test fails all {len(CHANGES)} planted problems")
        return 1 if found else 0
    repo = Path(
        subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True).stdout.strip()
    )
    found = problems(repo)
    print("\n".join(found) if found else f"check-repo: {repo.name} has the shape of an rfnry library")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
