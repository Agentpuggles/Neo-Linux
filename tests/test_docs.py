"""Documentation hygiene: links, anchors, structure and version drift.

Everything here is a plain-text check on the repo's own markdown — no network, no
markdown tooling. It exists because a README that promises `docs/protocol.md §8.1`
or a version number in three places goes stale the moment anyone edits one of them.
"""

import re
import unittest

from tests import support
from tests.support import neo

ROOT = support.REPO_ROOT

MARKDOWN_FILES = sorted(list(ROOT.glob("*.md")) + list((ROOT / "docs").glob("*.md")))


def read(path):
    return path.read_text(encoding="utf-8")


def iter_lines(text):
    """Yield (line_number, line) for lines outside fenced code blocks."""
    fence = None
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith(("```", "~~~")):
            marker = stripped[:3]
            if fence is None:
                fence = marker
            elif fence == marker:
                fence = None
            continue
        if fence is None:
            yield number, line


def headings(text):
    """(anchors, levels) — every heading's GitHub slug, in document order."""
    anchors, levels = [], []
    for _, line in iter_lines(text):
        match = re.match(r"^(#{1,6})\s+(.*?)\s*$", line)
        if match:
            anchors.append(heading_anchor(match.group(2)))
            levels.append(len(match.group(1)))
    return anchors, levels


def heading_anchor(text):
    """Reproduce GitHub's heading-slug rules closely enough to validate our own docs."""
    text = re.sub(r"`([^`]*)`", r"\1", text)  # inline code -> its content
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)  # links -> their label
    text = re.sub(r"[*_~]", "", text)  # emphasis markers
    text = text.strip().lower()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)  # punctuation goes away
    return text.replace(" ", "-")


def links(text):
    """(line_number, target) for every inline markdown link, images included."""
    for number, line in iter_lines(text):
        for match in re.finditer(r"!?\[[^\]]*\]\(<?([^)>\s]+)>?\)", line):
            yield number, match.group(1)


class TestMarkdownLinks(unittest.TestCase):
    def test_files_and_anchors_exist(self):
        anchors_by_file = {path: set(headings(read(path))[0]) for path in MARKDOWN_FILES}
        for path in MARKDOWN_FILES:
            for line_number, target in links(read(path)):
                if target.startswith(("http://", "https://", "mailto:", "#!")):
                    continue
                with self.subTest(link=f"{path.name}:{line_number} -> {target}"):
                    file_part, _, anchor = target.partition("#")
                    if file_part:
                        resolved = (path.parent / file_part).resolve()
                        self.assertTrue(resolved.is_file(), f"missing file: {file_part}")
                    else:
                        resolved = path
                    if anchor:
                        self.assertIn(
                            anchor, anchors_by_file.get(resolved, set()), f"no heading produces #{anchor}"
                        )

    def test_external_links_are_https(self):
        for path in MARKDOWN_FILES:
            for line_number, target in links(read(path)):
                with self.subTest(link=f"{path.name}:{line_number}"):
                    self.assertFalse(
                        target.startswith("http://"), "link to a non-TLS URL in a doc about credentials"
                    )


class TestStructure(unittest.TestCase):
    def test_headings_do_not_skip_levels(self):
        for path in MARKDOWN_FILES:
            with self.subTest(file=path.name):
                _, levels = headings(read(path))
                for before, after in zip(levels, levels[1:]):
                    self.assertLessEqual(after - before, 1, "heading level jumps by 2+")

    def test_every_markdown_table_is_rectangular(self):
        for path in MARKDOWN_FILES:
            block = []
            for line_number, line in [*list(iter_lines(read(path))), (None, "")]:
                is_row = line.startswith("|")
                if not is_row and block:
                    widths = {row.count("|") for row in block}
                    with self.subTest(file=path.name, first_line=block[0][0]):
                        self.assertEqual(len(widths), 1, "inconsistent column count in table")
                    block = []
                if is_row:
                    block.append((line_number, line))
            # end of file flushes any trailing table

    def test_readme_contents_matches_headings_when_present(self):
        text = read(ROOT / "README.md")
        parts = re.split(r"^## Contents\s*$", text, flags=re.M)
        if len(parts) == 1:
            return  # a short, player-facing README does not need a Contents table
        self.assertEqual(len(parts), 2, "README.md has more than one Contents section")
        contents = parts[1].split("\n## ", 1)[0]
        linked = {target.partition("#")[2] for _, target in links(contents)}
        h2 = [heading_anchor(line[3:]) for _, line in iter_lines(text) if line.startswith("## ")]
        for anchor in h2:
            if anchor == "contents":
                continue
            with self.subTest(section=anchor):
                self.assertIn(anchor, linked, "top-level section missing from Contents")

    def test_readme_documents_the_desktop_default_and_terminal_opt_out(self):
        text = read(ROOT / "README.md")
        for command in ("make install", "make install-cli", "neo --help"):
            self.assertIn(command, text)
        self.assertIn("docs/assets/neo-gui.png", text)
        self.assertLess(text.index("## Install"), text.index("## Prefer the terminal?"))

    def test_readme_links_every_document_in_docs(self):
        referenced = {target.split("#")[0] for _, target in links(read(ROOT / "README.md"))}
        for path in sorted((ROOT / "docs").glob("*.md")):
            with self.subTest(doc=path.name):
                self.assertIn(f"docs/{path.name}", referenced, "docs/ file not linked from the README")


class TestVersionDrift(unittest.TestCase):
    def test_readme_states_the_same_version_as_the_launcher(self):
        text = read(ROOT / "README.md")
        stated = re.search(r"Current release:\s*\*\*v?([0-9.]+)\*\*", text)
        self.assertIsNotNone(stated, "no 'Current release: **vX.Y.Z**' line in README.md")
        self.assertEqual(stated.group(1), neo.VERSION)

    def test_changelog_newest_entry_matches_the_launcher(self):
        text = read(ROOT / "CHANGELOG.md")
        versions = re.findall(r"^## \[(\d+\.\d+\.\d+)\]", text, flags=re.M)
        self.assertTrue(versions, "no dated release entry in CHANGELOG.md")
        self.assertEqual(
            versions[0], neo.VERSION, "the newest CHANGELOG release must be the version neo reports"
        )

    def test_changelog_keeps_an_unreleased_section(self):
        text = read(ROOT / "CHANGELOG.md")
        self.assertTrue(
            re.search(r"^## \[Unreleased\]", text, re.M),
            "Keep a Changelog wants an Unreleased section for work in flight",
        )

    def test_ci_matrix_covers_the_python_the_readme_promises(self):
        minimum = re.search(r"\*\*Python(?: / Qt)?\*\*\s*\|[^\n]*?≥\s*(\d+\.\d+)", read(ROOT / "README.md"))
        self.assertIsNotNone(minimum, "README must state a minimum Python in the table")
        workflow = read(ROOT / ".github" / "workflows" / "ci.yml")
        tested = set(re.findall(r"""["'](\d+\.\d+)["']""", workflow))
        self.assertTrue(tested, "ci.yml has no python matrix")
        self.assertIn(minimum.group(1), tested, f"README promises ≥{minimum.group(1)} but CI never runs it")
        self.assertIn(
            "py" + minimum.group(1).replace(".", ""),
            read(ROOT / "ruff.toml"),
            "ruff.toml target-version should match the documented floor",
        )


HYGIENE_FILES = [
    "README.md",
    "CHANGELOG.md",
    "LICENSE",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CODE_OF_CONDUCT.md",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/ISSUE_TEMPLATE/config.yml",
    ".github/dependabot.yml",
    ".github/workflows/ci.yml",
    "Makefile",
    "ruff.toml",
]


class TestCommunityFiles(unittest.TestCase):
    def test_repository_hygiene_files_are_present(self):
        for name in HYGIENE_FILES:
            with self.subTest(file=name):
                self.assertTrue((ROOT / name).is_file(), f"{name} is missing")
                self.assertGreater((ROOT / name).stat().st_size, 40, f"{name} looks empty")

    def test_license_is_the_mit_text_readme_claims(self):
        self.assertTrue(read(ROOT / "LICENSE").startswith("MIT License"))
        self.assertRegex(read(ROOT / "README.md"), r"MIT")

    def test_issue_templates_are_valid_yaml_shaped_forms(self):
        forms = sorted((ROOT / ".github" / "ISSUE_TEMPLATE").glob("*.yml"))
        self.assertTrue(forms, ".github/ISSUE_TEMPLATE has no forms")
        for path in forms:
            keys = {
                line.split(":", 1)[0]
                for line in read(path).splitlines()
                if line and not line.startswith((" ", "#")) and ":" in line
            }
            if path.name == "config.yml":
                with self.subTest(template="config.yml"):
                    self.assertIn("blank_issues_enabled", keys, "config.yml must set it explicitly")
                    self.assertIn("contact_links", keys, "no where-else-to-go links beside the forms")
                continue
            with self.subTest(template=path.name):
                for key in ("name", "description", "labels", "body"):
                    self.assertIn(key, keys, f"issue form is missing its `{key}` key")


if __name__ == "__main__":
    unittest.main()
