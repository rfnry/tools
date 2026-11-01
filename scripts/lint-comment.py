import ast
import io
import subprocess
import sys
import tempfile
import tokenize
from pathlib import Path

PYTHON_DIRECTIVES = ("# type:", "# noqa", "# pragma:")
SCRIPT_DIRECTIVES = ("// @ts-expect-error", "// biome-ignore", "/// <reference")
REGEX_AFTER = set("(,=:[!&|?{};+-*%<>~^")


def python(text: str, test: bool = False) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if token.type == tokenize.COMMENT and not token.string.startswith(PYTHON_DIRECTIVES):
            found.append((token.start[0], "a comment"))
    if test:
        return found
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                if isinstance(body[0].value.value, str):
                    found.append((body[0].lineno, "a docstring"))
    return found


def script(text: str) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    line = 1
    index = 0
    braces: list[int] = []
    previous = ""
    while index < len(text):
        char = text[index]
        ahead = text[index + 1] if index + 1 < len(text) else ""
        if char == "\n":
            line += 1
            index += 1
            continue
        if char in " \t\r":
            index += 1
            continue
        if char == "/" and ahead == "/":
            end = text.find("\n", index)
            end = len(text) if end < 0 else end
            if not text[index:end].startswith(SCRIPT_DIRECTIVES):
                found.append((line, "a comment"))
            index = end
            continue
        if char == "/" and ahead == "*":
            end = text.find("*/", index + 2)
            end = len(text) if end < 0 else end + 2
            found.append((line, "a comment"))
            line += text.count("\n", index, end)
            index = end
            continue
        if char in "'\"":
            index += 1
            while index < len(text) and text[index] != char:
                index += 2 if text[index] == "\\" else 1
            index += 1
            previous = "a"
            continue
        if char == "`" or (char == "}" and braces and braces[-1] == 0):
            if char == "}":
                braces.pop()
            index += 1
            while index < len(text) and text[index] != "`":
                if text[index] == "\\":
                    index += 2
                    continue
                if text.startswith("${", index):
                    braces.append(0)
                    index += 2
                    break
                if text[index] == "\n":
                    line += 1
                index += 1
            else:
                index += 1
                previous = "a"
                continue
            previous = "("
            continue
        if char == "/" and (previous == "" or previous in REGEX_AFTER):
            index += 1
            klass = False
            while index < len(text) and text[index] != "\n":
                if text[index] == "\\":
                    index += 2
                    continue
                if text[index] == "[":
                    klass = True
                elif text[index] == "]":
                    klass = False
                elif text[index] == "/" and not klass:
                    break
                index += 1
            index += 1
            previous = "a"
            continue
        if char == "{" and braces:
            braces[-1] += 1
        elif char == "}" and braces:
            braces[-1] -= 1
        previous = char
        index += 1
    return found


def shell(text: str) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for number, row in enumerate(text.splitlines(), 1):
        if row.lstrip().startswith("#") and not (number == 1 and row.startswith("#!")):
            found.append((number, "a comment"))
    return found


KINDS = {".py": python, ".ts": script, ".tsx": script, ".js": script, ".mjs": script, ".sh": shell}


def problems(repo: Path) -> tuple[list[str], int]:
    listed = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "-co", "--exclude-standard"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split("\n")
    found: list[str] = []
    scanned = 0
    for name in sorted(listed):
        path = repo / name
        kind = KINDS.get(path.suffix)
        if kind is None or not path.is_file() or "/dist/" in f"/{name}":
            continue
        scanned += 1
        text = path.read_text(encoding="utf-8")
        test = "tests" in Path(name).parts
        for line, what in (python(text, test) if kind is python else kind(text)):
            found.append(f"lint-comment: {name}:{line} holds {what}; say it in a name, a test or the guide")
    return found, scanned


PLANTED = {
    "a Python comment": ("a.py", "x = 1  # why\n", "holds a comment"),
    "a Python docstring": ("a.py", 'def f():\n    """what"""\n    return 1\n', "holds a docstring"),
    "a comment in a test": ("tests/t.py", "x = 1  # why\n", "holds a comment"),
    "a TypeScript line comment": ("a.ts", "const x = 1 // why\n", "holds a comment"),
    "a TypeScript block comment": ("a.ts", "/* what */\nexport const x = 1\n", "holds a comment"),
    "a comment after a template": ("a.ts", "const x = `a${b}c` // why\n", "holds a comment"),
    "a shell comment": ("a.sh", "#!/usr/bin/env bash\n# why\necho hi\n", "holds a comment"),
}
CLEAN = {
    "a.py": 'url = "http://example.com/#anchor"  # type: ignore\n',
    "b.ts": 'const a = "//not"; const b = /\\/\\//g; const c = `x ${"//"} y`\n// @ts-expect-error\nf()\n',
    "c.sh": '#!/usr/bin/env bash\necho "# not a comment"\n',
    "tests/d.py": 'class Verdict:\n    """The description under test."""\n',
}


def git_repo(scratch: Path, name: str, contents: dict[str, str]) -> Path:
    repo = scratch / name
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    for file, text in contents.items():
        (repo / file).parent.mkdir(parents=True, exist_ok=True)
        (repo / file).write_text(text, encoding="utf-8")
    return repo


def self_test() -> list[str]:
    failed: list[str] = []
    with tempfile.TemporaryDirectory() as root:
        scratch = Path(root)
        for index, (name, (file, text, expected)) in enumerate(PLANTED.items()):
            found, _ = problems(git_repo(scratch, f"planted{index}", {file: text}))
            if not any(expected in problem for problem in found):
                failed.append(f"lint-comment: the self-test planted {name} and the lint passed")
        found, _ = problems(git_repo(scratch, "clean", CLEAN))
        if found:
            failed.append(f"lint-comment: the self-test's clean files failed: {found}")
        _, scanned = problems(git_repo(scratch, "empty", {"README.md": "# x\n"}))
        if scanned:
            failed.append("lint-comment: the self-test's repository without code was scanned")
    return failed


def main(args: list[str]) -> int:
    if args[:1] == ["--self-test"]:
        found = self_test()
        print("\n".join(found) if found else f"lint-comment: the self-test fails all {len(PLANTED)} planted comments")
        return 1 if found else 0
    repo = Path(
        subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True).stdout.strip()
    )
    found, scanned = problems(repo)
    if not scanned:
        print(f"lint-comment: {repo.name} holds no code to scan")
        return 1
    print("\n".join(found) if found else f"lint-comment: {scanned} files of {repo.name}, no comment and no docstring")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
