import ast
import io
import re
import subprocess
import sys
import tempfile
import tokenize
from collections.abc import Callable
from pathlib import Path

CODES = r"[A-Z]+[0-9]+(?:, ?[A-Z]+[0-9]+)*"
OPTION = r"[a-z][a-z-]*(?:=(?:\"[\w\-, ]*\"|[\w\-,]+))?"
PYTHON_DIRECTIVE = re.compile(
    rf"type: ignore(?:\[[\w\-, ]+\])?|noqa(?:: ?{CODES})?|ruff: noqa(?:: ?{CODES})?|pragma: no (?:cover|branch)"
    rf"|fmt: (?:off|on|skip)|pyright: ignore(?:\[[\w, ]+\])?|mypy: {OPTION}(?:, {OPTION})*"
)
CODING = re.compile(r"#(?: -\*-)? coding[:=] ?[-\w.]+(?: -\*-)?")
SCRIPT_DIRECTIVE = re.compile(
    r"// @ts-expect-error|// biome-ignore(?:-all|-start|-end)? [\w/()-]+(?: [\w/()-]+)*: \S.*"
    r"|/// <reference (?:types|path|lib)=\"[^\"]+\" />"
)
KEYWORDS = {"return", "typeof", "case", "in", "of", "new", "throw", "yield", "await", "else", "do", "void", "delete"}
REGEX_AFTER = set("(,=:[!&|?{};+-*%<>~^")
WORD = re.compile(r"[\w$]+")
HEREDOC = re.compile(r"<<(-?)[ \t]*(?:'([^'\n]*)'|\"([^\"\n]*)\"|\\?([A-Za-z_]\w*))")
META = set(" \t\n;|&()<>")
OWNERS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
RUN = re.compile(r"^( *)(- )?run: *(.*)$")

Found = list[tuple[int, str]]


def python_directive(comment: str, line: int) -> bool:
    if line == 1 and comment.startswith("#!"):
        return True
    if line <= 2 and CODING.fullmatch(comment.rstrip()):
        return True
    return all(PYTHON_DIRECTIVE.fullmatch(part.rstrip()) for part in re.split(r"\s*#\s*", comment)[1:])


def python(text: str, test: bool = False) -> Found:
    tree = ast.parse(text)
    found: Found = []
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if token.type == tokenize.COMMENT and not python_directive(token.string, token.start[0]):
            found.append((token.start[0], "a comment"))
    if test:
        return found
    first = {id(owner.body[0]) for owner in ast.walk(tree) if isinstance(owner, OWNERS) and owner.body}
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            found.append((node.lineno, "a docstring" if id(node) in first else "a bare string"))
    return sorted(found)


def regex_end(text: str, index: int) -> int | None:
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
            flags = WORD.match(text, index + 1)
            return flags.end() if flags else index + 1
        index += 1
    return None


def script(text: str) -> Found:
    found: Found = []
    line = 1
    index = 0
    braces: list[int] = []
    previous = ""
    if text.startswith("#!"):
        index = text.find("\n") if "\n" in text else len(text)
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
            if not SCRIPT_DIRECTIVE.fullmatch(text[index:end].rstrip()):
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
                if text[index] == "\\":
                    line += text[index + 1 : index + 2] == "\n"
                    index += 2
                    continue
                index += 1
            index += 1
            previous = "a"
            continue
        if char == "`" or (char == "}" and braces and braces[-1] == 0):
            if char == "}":
                braces.pop()
            index += 1
            while index < len(text) and text[index] != "`":
                if text[index] == "\\":
                    line += text[index + 1 : index + 2] == "\n"
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
        if char == "/" and (previous == "" or previous in REGEX_AFTER or previous in KEYWORDS):
            end = regex_end(text, index)
            if end is not None:
                index = end
                previous = "a"
                continue
        if char in "+-" and ahead == char:
            index += 2
            previous = ")"
            continue
        word = WORD.match(text, index)
        if word:
            previous = word.group() if word.group() in KEYWORDS and previous != "." else "a"
            index = word.end()
            continue
        if char == "{" and braces:
            braces[-1] += 1
        elif char == "}" and braces:
            braces[-1] -= 1
        previous = char
        index += 1
    return found


def arithmetic_end(text: str, index: int) -> int:
    depth = 0
    while index < len(text):
        if text[index] == "(":
            depth += 1
        elif text[index] == ")":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return index


def shell(text: str, first: int = 1) -> Found:
    found: Found = []
    line = first
    index = 0
    stack: list[str] = []
    pending: list[tuple[str, bool]] = []
    if first == 1 and text.startswith("#!"):
        index = text.find("\n") if "\n" in text else len(text)
    while index < len(text):
        char = text[index]
        top = stack[-1] if stack else ""
        if char == "\n":
            line += 1
            index += 1
            if top in ("", "$(", "("):
                for word, tabs in pending:
                    while index < len(text):
                        end = text.find("\n", index)
                        end = len(text) if end < 0 else end
                        row = text[index:end]
                        index = end + 1
                        line += 1
                        if (row.lstrip("\t") if tabs else row) == word:
                            break
                pending = []
            continue
        if char == "\\" and top != "'":
            line += text[index + 1 : index + 2] == "\n"
            index += 2
            continue
        if top == "'" or top == "$'":
            if char == "'":
                stack.pop()
            index += 1
            continue
        if top == "`":
            if char == "`":
                stack.pop()
            index += 1
            continue
        if top in ('"', "${"):
            if (top == '"' and char == '"') or (top == "${" and char == "}"):
                stack.pop()
            elif text.startswith("$((", index):
                end = arithmetic_end(text, index + 1)
                line += text.count("\n", index, end)
                index = end
                continue
            elif text.startswith(("$(", "${"), index):
                stack.append(text[index : index + 2])
                index += 2
                continue
            elif char == "`" or (top == "${" and char in "'\""):
                stack.append(char)
            index += 1
            continue
        if char == "#" and (index == 0 or text[index - 1] in META):
            end = text.find("\n", index)
            index = len(text) if end < 0 else end
            found.append((line, "a comment"))
            continue
        if text.startswith(("$((", "(("), index):
            end = arithmetic_end(text, index + 1 if char == "$" else index)
            line += text.count("\n", index, end)
            index = end
            continue
        if text.startswith(("$(", "${", "$'"), index):
            stack.append(text[index : index + 2])
            index += 2
            continue
        if text.startswith("<<<", index):
            index += 3
            continue
        heredoc = HEREDOC.match(text, index) if text.startswith("<<", index) else None
        if heredoc:
            pending.append((next(group for group in heredoc.groups()[1:] if group is not None), heredoc.group(1) == "-"))
            index = heredoc.end()
            continue
        if char in "'\"`(":
            stack.append(char)
        elif char == ")" and top in ("$(", "("):
            stack.pop()
        index += 1
    return found


def make(text: str) -> Found:
    found: Found = []
    rows = text.split("\n")
    number = 0
    while number < len(rows):
        start = number + 1
        if rows[number].startswith("\t"):
            recipe = [rows[number][1:]]
            while recipe[-1].endswith("\\") and number + 1 < len(rows):
                number += 1
                recipe.append(rows[number].removeprefix("\t"))
            found.extend(shell("\n".join(recipe).lstrip("@-+ \t"), start))
        else:
            depth = 0
            row = rows[number]
            for index, char in enumerate(row):
                if row.startswith(("$(", "${"), index):
                    depth += 1
                elif char in ")}" and depth:
                    depth -= 1
                elif char == "#" and not depth and (index == 0 or row[index - 1] != "\\"):
                    found.append((start, "a comment"))
                    break
        number += 1
    return found


def workflow(text: str) -> Found:
    found: Found = []
    rows = text.split("\n")
    for number, row in enumerate(rows):
        run = RUN.match(row)
        if run is None:
            continue
        key = len(run.group(1)) + (2 if run.group(2) else 0)
        value = run.group(3)
        if not re.fullmatch(r"[|>][-+]?", value.rstrip()):
            found.extend(shell(value, number + 1))
            continue
        body: list[str] = []
        for following in rows[number + 1 :]:
            if following.strip() and len(following) - len(following.lstrip(" ")) <= key:
                break
            body.append(following)
        indent = min((len(row) - len(row.lstrip(" ")) for row in body if row.strip()), default=0)
        found.extend(shell("\n".join(row[indent:] for row in body), number + 2))
    return found


SUFFIXES: dict[str, Callable[[str], Found]] = {
    ".py": python,
    ".pyi": python,
    ".ts": script,
    ".mts": script,
    ".cts": script,
    ".js": script,
    ".mjs": script,
    ".cjs": script,
    ".sh": shell,
    ".bash": shell,
}
MAKEFILES = {"Makefile", "makefile", "GNUmakefile"}


def interpreted(path: Path) -> Callable[[str], Found] | None:
    with path.open("rb") as file:
        head = file.readline(256)
    if not head.startswith(b"#!"):
        return None
    words = head[2:].decode("utf-8", "replace").split()
    program = words[0].rsplit("/", 1)[-1] if words else ""
    if program == "env":
        program = next((word for word in words[1:] if not word.startswith("-")), "")
    if re.fullmatch(r"python[0-9.]*", program):
        return python
    if program in ("bash", "sh", "dash", "zsh", "ksh"):
        return shell
    if program in ("node", "deno", "bun"):
        return script
    return None


def kind(repo: Path, name: str) -> Callable[[str], Found] | None:
    path = Path(name)
    if path.parts[:1] == ("packages",) and path.parts[2:3] == ("dist",):
        return None
    if path.name in MAKEFILES or path.suffix == ".mk":
        return make
    if name.startswith(".github/workflows/") and path.suffix in (".yml", ".yaml"):
        return workflow
    if path.suffix:
        return SUFFIXES.get(path.suffix)
    return interpreted(repo / name)


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
        if not name or not (repo / name).is_file():
            continue
        read = kind(repo, name)
        if read is None:
            continue
        scanned += 1
        text = (repo / name).read_text(encoding="utf-8")
        try:
            hits = python(text, "tests" in Path(name).parts) if read is python else read(text)
        except SyntaxError as error:
            found.append(f"lint-comment: {name}:{error.lineno} does not parse as Python: {error.msg}")
            continue
        for line, what in hits:
            found.append(f"lint-comment: {name}:{line} holds {what}; say it in a name, a test or the guide")
    return found, scanned


PLANTED = {
    "a Python comment": ("a.py", "x = 1  # why\n"),
    "a Python docstring": ("a.py", 'def f():\n    """what"""\n    return 1\n'),
    "a bare string in a function": ("a.py", 'def f():\n    x = 1\n    """explain x"""\n    return x\n'),
    "a comment in a test": ("tests/t.py", "x = 1  # why\n"),
    "prose after # type:": ("a.py", "x = 1  # type: because the API returns it\n"),
    "prose after # type: ignore": ("a.py", "x = f()  # type: ignore[arg-type]  # the stub is wrong\n"),
    "prose after # noqa": ("a.py", "x = 1  # noqa this is why\n"),
    "prose after # noqa codes": ("a.py", "x = 1  # noqa: E501 the URL is long\n"),
    "prose after # fmt:": ("a.py", "x = [1]  # fmt: skip it here\n"),
    "a shebang past line 1": ("a.py", "x = 1\n#!/usr/bin/env python3\n"),
    "a coding cookie past line 2": ("a.py", "x = 1\ny = 2\n# -*- coding: utf-8 -*-\n"),
    "a comment in a stub": ("a.pyi", "x: int  # why\n"),
    "Python that does not parse": ("a.py", "def f(:\n"),
    "a TypeScript line comment": ("a.ts", "const x = 1 // why\n"),
    "a TypeScript block comment": ("a.ts", "/* what */\nexport const x = 1\n"),
    "a comment after a template": ("a.ts", "const x = `a${b}c` // why\n"),
    "a comment after a regex after return": ("a.ts", "function f(s) {\n  return /a/g // why\n}\n"),
    "a comment after a regex holding a quote": ("a.ts", "function q(s) {\n  return /'/.test(s) // why\n}\n"),
    "prose after @ts-expect-error": ("a.ts", "// @ts-expect-error because the types lie\nf()\n"),
    "prose after a reference": ("a.ts", '/// <reference types="node" /> and why\n'),
    "a biome-ignore with no reason": ("a.ts", "// biome-ignore lint/style/noNonNullAssertion\nf()!\n"),
    "a comment after a division": ("a.ts", "const h = i++ / 2 // why\n"),
    "a comment after a division of a property named return": ("a.ts", "const d = x.return / 2 // why\n"),
    "a comment in a .mjs": ("a.mjs", "export const x = 1 // why\n"),
    "a comment in a .cjs": ("a.cjs", "module.exports = 1 // why\n"),
    "a comment in a .mts": ("a.mts", "export const x = 1 // why\n"),
    "a comment in a .cts": ("a.cts", "export const x = 1 // why\n"),
    "a comment in a .js": ("a.js", "export const x = 1 // why\n"),
    "a shell comment": ("a.sh", "#!/usr/bin/env bash\n# why\necho hi\n"),
    "a trailing shell comment": ("a.sh", "#!/usr/bin/env bash\necho hi  # why\n"),
    "a shell comment after a heredoc": ("a.sh", "cat <<'EOF'\n# body\nEOF\n# why\n"),
    "a shell comment after an indented heredoc": ("a.sh", "cat <<-EOF\n\t# body\n\tEOF\necho hi # why\n"),
    "a shell comment after a herestring": ("a.sh", "cat <<<x\n# why\n"),
    "a shell comment in a subshell": ("a.sh", 'x="$(echo hi # why\n)"\n'),
    "a shell comment after a shift in arithmetic": ("a.sh", "echo $((a << b))\n# why\n"),
    "a shell comment after a quoted brace in an expansion": ("a.sh", 'echo ${x:-"}"}\n# why\n'),
    "a comment in a bash script with no extension": ("scripts/release", "#!/usr/bin/env bash\n# why\necho hi\n"),
    "a comment in a Python script with no extension": ("scripts/tool", "#!/usr/bin/python3\nx = 1  # why\n"),
    "a comment in a node script with no extension": ("bin/cli", "#!/usr/bin/env node\nconst x = 1 // why\n"),
    "a Makefile comment": ("Makefile", "# why\nall:\n\t@echo hi\n"),
    "a Makefile trailing comment": ("Makefile", "X := 1 # why\nall:\n\t@echo hi\n"),
    "a shell comment in a recipe": ("Makefile", "all:\n\t@echo hi  # why\n"),
    "a comment in a .mk": ("rules.mk", "# why\n"),
    "a comment in a workflow's run block": (".github/workflows/ci.yml", "jobs:\n  a:\n    steps:\n      - run: |\n          # why\n          echo hi\n"),
    "a comment past a blank line of a run block": (".github/workflows/ci.yml", "jobs:\n  a:\n    steps:\n      - run: |\n          echo a\n\n          # why\n"),
    "a comment in a workflow's run line": (".github/workflows/ci.yml", "jobs:\n  a:\n    steps:\n      - run: echo hi # why\n"),
    "a comment in a dist/ that is not a package's": ("src/pkg/dist/mod.py", "x = 1  # why\n"),
}
PLANTED_LINES = {
    "a shell comment after a heredoc": 4,
    "a shell comment after an indented heredoc": 4,
    "a shell comment in a recipe": 2,
    "a comment in a workflow's run block": 5,
    "a comment past a blank line of a run block": 7,
    "a shell comment after a shift in arithmetic": 2,
    "a shell comment after a quoted brace in an expansion": 2,
    "a Python docstring": 2,
    "a bare string in a function": 3,
}
CLEAN = {
    "a.py": 'url = "http://example.com/#anchor"  # type: ignore\n',
    "b.py": "#!/usr/bin/env python3\n# -*- coding: utf-8 -*-\nx = 1  # type: ignore[arg-type,return-value]\n",
    "c.py": "# coding=utf-8\n# fmt: off\nx = [1,\n  2]\n# fmt: on\ny = [1, 2]  # fmt: skip\n",
    "d.py": "# ruff: noqa: E501\n# mypy: disable-error-code=\"attr-defined\"\nx = 1  # noqa\ny = 2  # noqa: E501, F401\n",
    "e.py": "x: int = f()  # pyright: ignore[reportAssignmentType]\nz = 1  # type: ignore  # noqa: E501\nw = 1  # pragma: no cover\n",
    "f.py": "x = 3\ny = f\"#{x:#x} {'#'}\"\n",
    "tests/g.py": 'class Verdict:\n    """The description under test."""\n',
    "h.ts": 'const a = "//not"; const b = /\\/\\//g; const c = `x ${"//"} y`\n// @ts-expect-error\nf()\n',
    "i.ts": "export function u(s: string) {\n  return /https?:\\/\\//.test(s)\n}\nswitch (x) {\n  case /\\/\\//.source: break\n}\n",
    "j.ts": "const n = (b + c) / 2 / d\nconst f = () => /\\/\\//\nlet i = 0\nconst h = i++ / 2\nconst u = 'http://x'\n",
    "k.ts": "const a = `x${`y${z}`}w`\nconst b = `x${ {k: 1}.k }y//`\nconst g = f<number>(1) / 2\nconst t = typeof /x\\/\\//\n",
    "l.ts": "function q(s: string) {\n  return /'/.test(s)\n}\nconst t = 'x'\nconst d = x.return / 2 / 3\n",
    "m.ts": '/// <reference types="node" />\n// biome-ignore lint/style/noNonNullAssertion: the map holds every key\nexport const v = m.get(k)!\n',
    "n.mjs": "#!/usr/bin/env node\n/\\/\\//.test(process.argv[2]) && f('http://x')\n",
    "o.sh": '#!/usr/bin/env bash\necho "# not a comment"\necho \'# not\' a#b ${#arr[@]} $# "${x#y}"\n',
    "p.sh": "cat <<'EOF'\n# Title\nEOF\ncat <<-EOF\n\t# indented\n\tEOF\ncat <<\"END\"\n# quoted\nEND\n",
    "q.sh": 'x="$(printf \'%s\' "a # b")"\n[[ $x =~ ^# ]] && echo $((16#ff)) $(( 1 << 2 ))\n(( y = 1 << 2 ))\n',
    "r.sh": "echo $'it\\'s # not'\necho `echo '#'`\necho \"a\\\" # b\"\n",
    "Makefile": 'SHELL := /bin/bash\nX := $(shell echo "#")\ncheck:\n\t@echo "#" \'#\' $$#\n\t@for f in *.sh; do \\\n\t  bash -n "$$f"; done\n',
    ".github/workflows/ci.yml": (
        "jobs:\n  a:\n    steps:\n"
        "      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1\n"
        "      - run: |\n          echo \"#\"\n"
        "      - uses: actions/setup-node@949feb2413d6458794dcd2491c4babbbce0c15c1 # v7.1.0\n"
        "      - run: |\n          cat <<'EOF'\n          # heading\n          EOF\n"
        "      - run: echo '#'\n"
    ),
    "packages/typescript/dist/index.js": "export const x = 1 // built\n",
    "packages/python/dist/mod.py": "x = 1  # built\n",
    "component.tsx": "export const A = () => <p>see https://example.com, it's here</p>\n",
    "component.jsx": "export const A = () => <p>Don't</p>\n",
    "LICENSE": "MIT # not code\n",
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
        for index, (name, (file, text)) in enumerate(PLANTED.items()):
            found, _ = problems(git_repo(scratch, f"planted{index}", {file: text}))
            line = PLANTED_LINES.get(name)
            if not found or (line is not None and not any(f":{line} " in problem for problem in found)):
                failed.append(f"lint-comment: the self-test planted {name} and the lint passed: {found}")
        found, scanned = problems(git_repo(scratch, "clean", CLEAN))
        if found:
            failed.append(f"lint-comment: the self-test's clean files failed: {found}")
        if scanned != len(CLEAN) - 5:
            failed.append(f"lint-comment: the self-test scanned {scanned} of the clean files, not {len(CLEAN) - 5}")
        _, scanned = problems(git_repo(scratch, "empty", {"README.md": "# x\n"}))
        if scanned:
            failed.append("lint-comment: the self-test's repository without code was scanned")
    return failed


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()


def main(args: list[str]) -> int:
    if args[:1] == ["--self-test"]:
        found = self_test()
        print("\n".join(found) if found else f"lint-comment: the self-test fails all {len(PLANTED)} planted comments")
        return 1 if found else 0
    repo = Path(git("rev-parse", "--show-toplevel"))
    name = Path(git("rev-parse", "--path-format=absolute", "--git-common-dir")).parent.name
    found, scanned = problems(repo)
    if not scanned:
        print(f"lint-comment: {name} holds no code to scan")
        return 1
    print("\n".join(found) if found else f"lint-comment: {scanned} files of {name}, no comment and no docstring")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
