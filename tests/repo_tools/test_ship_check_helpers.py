"""Unit tests for the helpers behind gates G1 to G4, G13, and G14 in tools/ship_check.py.

All inputs are SYNTHETIC strings and throwaway git repositories made for these tests.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import ship_check

Commit = Callable[[Path, str], str]


# ---------------------------------------------------------------- G1


def test_function_body_lines() -> None:
    source = (
        "import os\n"  # 1
        "\n"  # 2
        "@staticmethod\n"  # 3
        "def f(x=os.sep):\n"  # 4
        '    """Doc."""\n'  # 5
        "    y = x\n"  # 6
        "    return y\n"  # 7
        "class C:\n"  # 8
        "    z = 1\n"  # 9
        "    async def g(self):\n"  # 10
        "        if self:\n"  # 11
        "            return 2\n"  # 12
    )
    assert ship_check.function_body_lines(source) == {5, 6, 7, 11, 12}
    assert ship_check.function_body_lines("def broken(:\n") == set()


def test_measured_files_keep_only_files_under_the_clone(tmp_path: Path) -> None:
    report = {
        "files": {
            "src/receipts/a.py": {"summary": {"covered_lines": 1, "num_statements": 2}},
            str(tmp_path / "src" / "receipts" / "b.py"): {"summary": {"covered_lines": 0}},
            "/elsewhere/src/receipts/c.py": {"summary": {}},
        }
    }
    measured = ship_check.measured_files(tmp_path, report)
    assert sorted(measured) == ["src/receipts/a.py", "src/receipts/b.py"]


# ---------------------------------------------------------------- G2 (H04 to H06)


def test_type_ignore_grammar() -> None:
    source = (
        "a = f()  # type: ignore[no-untyped-call]  # third-party stub missing\n"  # 1 ok
        'b: int = "s"  # type: ignore[assignment]# reason without a space\n'  # 2 ok
        'c = 1  # see the "# type: ignore" policy\n'  # 3 not an ignore
        'd = "s"  # type: int  # type: ignore\n'  # 4 bare, after a type comment
        "e = f()  #type:ignore\n"  # 5 bare, no spaces
        "g = f()  # type: ignored-later\n"  # 6 not an ignore
    )
    assert ship_check.unexplained_type_ignores(source) == [4, 5]


def test_inline_mypy_settings() -> None:
    def problems(source: str) -> list[str]:
        return ship_check.suppression_problems("src/receipts/m.py", source)

    assert problems("# mypy: warn-unreachable, strict-equality=True\nx = 1\n") == []
    assert problems("# mypy: enable-error-code=ignore-without-code\n") == []
    assert "relaxes --strict" in problems("# mypy: ignore-errors\n")[0]
    assert "relaxes --strict" in problems("# mypy: warn-unreachable=False\n")[0]
    assert "without a reason" in problems('# mypy: disable-error-code="misc"\n')[0]
    reasoned = '# Reason: synthetic stub module.\n# mypy: disable-error-code="misc,attr-defined"\n'
    assert problems(reasoned) == []
    # Another directive is not a reason, and mypy only reads lines that start the line.
    assert problems('# noqa: E501\n# mypy: disable-error-code="misc"\n')
    assert problems('x = """\n    # mypy: ignore-errors\n"""\n') == []
    assert problems('x = """\n# mypy: ignore-errors\n"""\n')


def test_no_type_check_and_file_noqa() -> None:
    def problems(source: str) -> list[str]:
        return ship_check.suppression_problems("src/receipts/m.py", source)

    assert problems("import typing\n\n@typing.no_type_check\ndef f(): ...\n")
    assert problems("from typing import no_type_check as unchecked\n")
    assert problems("# ruff: noqa\nx = 1\n")
    assert problems("# flake8: NOQA\nx = 1\n")
    assert problems("# ruff: noqa E501\nx = 1\n")
    assert problems("def f() -> None:\n    # ruff: noqa\n    return None\n")
    # Targeted, inline, or unrecognized forms are not file-wide suppressions.
    assert problems("# ruff: noqa: F401\nimport os\n") == []
    assert problems("x = 1  # ruff: noqa\n") == []
    assert problems("# Ruff: noqa\nx = 1\n") == []
    assert problems("import os  # noqa: F401\n") == []


def test_ruff_blanket_ignores_follow_extend(tmp_path: Path) -> None:
    (tmp_path / "base.toml").write_text(
        '[lint.per-file-ignores]\n"src/receipts/analysis/*" = ["ALL"]\n"__init__.py" = ["F401"]\n'
    )
    (tmp_path / "pyproject.toml").write_text('[tool.ruff]\nextend = "base.toml"\n')
    package = ["src/receipts/__init__.py", "src/receipts/analysis/glmm.py"]
    problems = ship_check.ruff_blanket_ignores(tmp_path, package)
    assert len(problems) == 1 and "src/receipts/analysis/glmm.py" in problems[0]
    (tmp_path / "ruff.toml").write_text('[lint.per-file-ignores]\n"!src/**" = ["ALL"]\n')
    assert ship_check.ruff_blanket_ignores(tmp_path, package) == []


# ---------------------------------------------------------------- G3 (H07 to H09)


def test_shell_commands() -> None:
    script = "set -e\n# a comment\nmake setup \\\n  PY=3.11\nmake ci  # all checks\n\n"
    assert ship_check.shell_commands(script) == ["set -e", "make setup PY=3.11", "make ci"]


def test_matrix_pythons_apply_exclude_then_include() -> None:
    job: dict[str, Any] = {
        "strategy": {
            "matrix": {
                "os": ["ubuntu", "macos"],
                "python-version": ["3.11", "3.12"],
                "exclude": [{"os": "macos", "python-version": "3.12"}],
                "include": [{"python-version": "3.13"}],
            }
        }
    }
    assert ship_check.matrix_pythons(job) == {"3.11", "3.12", "3.13"}
    job["strategy"]["matrix"]["exclude"] = [{"python-version": "3.12"}]
    assert ship_check.matrix_pythons(job) == {"3.11", "3.13"}


def test_mini_yaml_reads_flow_and_block_forms() -> None:
    text = (
        "a: [1, '2', \"3\"]\n"
        "b: {k: v, n: [x, y]}\n"
        "c:\n- one\n- two: 2\n  three: 3\n"
        "d: |\n  line 1\n  line 2\n"
        "e: >\n  folded\n  text\n"
        "f: plain\n  continued\n"
    )
    assert ship_check.MiniYaml(text).node(0) == {
        "a": ["1", "2", "3"],
        "b": {"k": "v", "n": ["x", "y"]},
        "c": ["one", {"two": "2", "three": "3"}],
        "d": "line 1\nline 2\n",
        "e": "folded text",
        "f": "plain continued",
    }


def test_make_rules_parse_the_database() -> None:
    database = (
        "# Variables\nRUN := echo\n\n# Files\n"
        "ci: lint demo\n#  recipe to execute (from 'Makefile', line 3):\n\t-@$(RUN) post\n\n"
        "lint:\n#  recipe to execute (from 'Makefile', line 5):\n\t$(RUN) ruff\n"
    )
    rules = ship_check.make_rules(database)
    assert rules["ci"] == (["lint", "demo"], ["-@$(RUN) post"])
    assert rules["lint"] == ([], ["$(RUN) ruff"])
    assert "RUN" not in rules
    # A continued recipe line is one command; its continuation's dashes are not a prefix.
    continued = "test:\n\t$(RUN) pytest \\\n\t\t--cov-report=json:x $(ARGS)\n"
    assert ship_check.make_rules(continued)["test"][1] == [
        "$(RUN) pytest \\\n\t--cov-report=json:x $(ARGS)"
    ]
    assert ship_check._ignores_errors("@-$(RUN) x") and not ship_check._ignores_errors("$(RUN) -x")


# ---------------------------------------------------------------- G4 (H10)


@pytest.mark.skipif(shutil.which("unshare") is None, reason="needs unshare")
def test_isolates_tells_a_real_isolator_from_a_pass_through() -> None:
    assert not ship_check.isolates(["env"])
    unshare = shutil.which("unshare")
    assert unshare is not None
    works = subprocess.run([unshare, "-rn", "true"], capture_output=True, check=False)
    if works.returncode != 0:
        pytest.skip("unshare -rn is blocked here")
    assert ship_check.isolates([unshare, "-rn"])


# ---------------------------------------------------------------- G13 (H37, H38, H48)


def test_headings_skip_code_and_comments() -> None:
    text = (
        "# Title\n"
        "   ```sh\n# not a heading (indented fence)\n   ```\n"
        "~~~\n# not a heading (tilde fence)\n~~~\n"
        "<!--\n# not a heading (comment)\n-->\n"
        "<!-- # not a heading either -->\n"
        "    # not a heading (indented code)\n"
        "#\nnot a heading (empty marker)\n"
        "## Real heading ##\n"
        "```\n# inside an unclosed fence\n"
    )
    assert ship_check.headings(text) == ["title", "real heading"]
    assert ship_check.strip_code("x\n```\n# not heading\n```\ny") == "x\n\ny"
    assert ship_check.strip_code("a\n````\n```\nstill code\n````\nb") == "a\n\nb"


def test_md_sections_run_to_the_next_heading_of_the_same_level() -> None:
    text = "## Results\nintro\n### E1\ndetail\n## Limits\nother\n"
    sections = dict(ship_check.md_sections(text))
    assert sections["results"] == "intro\n### E1\ndetail"
    assert ship_check.section_text(text, "e1") == "detail"


def test_states_interval() -> None:
    assert ship_check.states_interval("<!--n:a-->0.2<!--/n--> (<!--n:a.ci-->[0.1, 0.3]<!--/n-->)")
    assert ship_check.states_interval("<!--n:a-->0.2 [0.1, 0.3]<!--/n-->")
    assert ship_check.states_interval(
        "<!--n:a-->0.2<!--/n--> <!--n:a.ci_low-->0.1<!--/n--> <!--n:a.ci_high-->0.3<!--/n-->"
    )
    assert not ship_check.states_interval("<!--n:a-->0.2<!--/n--> in CI, see make ci")
    assert not ship_check.states_interval("<!--n:a.ci_low-->0.1<!--/n--> only a bound")
    assert not ship_check.states_interval("<!--n:a.ci-->[0.1, 0.3]<!--/n--> with no estimate")


def test_text_blocks_keep_paragraphs_and_optionally_rows() -> None:
    text = "# T\n\npara one\nline two\n\n| a | b |\n| --- | --- |\n```\ncode\n```\nlast\n"
    assert ship_check.text_blocks(text, rows=False) == ["para one\nline two", "last"]
    rows = ship_check.text_blocks(text, rows=True)
    assert "| a | b |" in rows and "para one\nline two" in rows


def test_image_and_link_paths() -> None:
    text = (
        "[![ci](https://example.invalid/badge.svg)](https://example.invalid)\n"
        '![a](./docs/figures/x.svg "title") <img alt="b" src="docs/y.svg">\n'
        "![c](../outside.svg) ![d](/docs/z.svg) ![e](figures/w.svg#frag)\n"
        "[results](artifacts/e1/results.json) [![fig](f.svg)](prereg/0001.md) [web](https://x.invalid)\n"
    )
    assert ship_check.image_paths(text, "") == [
        "docs/figures/x.svg",
        "docs/z.svg",
        "figures/w.svg",
        "f.svg",
        "docs/y.svg",
    ]
    assert ship_check.image_paths("![w](figures/w.svg)", "docs") == ["docs/figures/w.svg"]
    assert ship_check.link_paths(text, "") == ["artifacts/e1/results.json", "prereg/0001.md"]


def test_hype_and_em_dash_patterns() -> None:
    for text in ("state of\nthe art", "Ground-breaking", "groundbreaking", "SOTA", "revolutionary"):
        assert ship_check.HYPE.search(text), text
    for text in ("statement of the article", "Sota Kato (2025)", "breaking ground"):
        assert ship_check.HYPE.search(text) is None, text
    for text in ("&mdash;", "&MDASH;", "&#8212;", "&#x2014;", "&#X2014;"):
        assert ship_check.EM_DASH_ENTITY.search(text), text
    assert ship_check.EM_DASH_ENTITY.search("&ndash; &#8211;") is None


# ---------------------------------------------------------------- G14 (H51) and environment


@pytest.mark.parametrize("flag", ["--skip-worktree", "--assume-unchanged"])
def test_pre_phase_sees_changes_hidden_by_index_bits(
    git_repo: Path, commit: Commit, flag: str
) -> None:
    (git_repo / ".gitignore").write_text("private/\n")
    (git_repo / "budget_like.toml").write_text("v = 1\n")
    commit(git_repo, "synthetic budget")
    assert ship_check.pre_phase(git_repo) == {}
    (git_repo / "budget_like.toml").write_text("v = 99\n")
    subprocess.run(
        ["git", "-C", str(git_repo), "update-index", flag, "budget_like.toml"], check=True
    )
    status = subprocess.run(
        ["git", "-C", str(git_repo), "status", "--porcelain"], capture_output=True, text=True
    )
    assert status.stdout == ""  # git status alone reports a clean tree
    assert "skip-worktree or assume-unchanged" in ship_check.pre_phase(git_repo)["clean"]


def test_git_redirect_variables_never_reach_git_or_sub_commands(
    git_repo: Path, commit: Commit, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (git_repo / "a.txt").write_text("a\n")
    commit(git_repo, "synthetic")
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "elsewhere.git"))
    monkeypatch.setenv("GIT_INDEX_FILE", str(tmp_path / "index"))
    assert ship_check.tracked(git_repo, "*.txt") == ["a.txt"]
    kept, dropped = ship_check.scrub_environment({"GIT_DIR": "x", "GIT_CONFIG_COUNT": "1"})
    assert dropped == ["GIT_DIR"] and kept == {"GIT_CONFIG_COUNT": "1"}
