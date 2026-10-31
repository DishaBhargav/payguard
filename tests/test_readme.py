"""Tests that keep README.md honest: what it documents must match what the program does."""
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from main import build_parser

PROJECT_ROOT = Path(__file__).resolve().parent.parent
README = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
GENERATOR_SOURCE = (PROJECT_ROOT / "scripts" / "generate_data.py").read_text(encoding="utf-8")


def main_options():
    """Every long option the real command line accepts, e.g. '--input'."""
    options = set()
    for action in build_parser()._actions:
        options.update(name for name in action.option_strings if name.startswith("--"))
    return options


class ReadmeAgreesWithTheCodeTests(unittest.TestCase):
    def test_every_command_line_option_is_documented(self):
        for option in main_options() - {"--help"}:
            with self.subTest(option=option):
                self.assertIn(f"`{option}`", README)

    def test_the_readme_mentions_no_option_that_does_not_exist(self):
        generator_options = set(re.findall(r'add_argument\("(--[a-z-]+)"', GENERATOR_SOURCE))
        allowed = main_options() | generator_options
        mentioned = set(re.findall(r"--[a-z][a-z-]*", README))
        self.assertEqual(mentioned - allowed, set())

    def test_documented_default_values_match_the_code(self):
        defaults = build_parser().parse_args([])
        rows = re.findall(r"^\| `(--[a-z-]+)` \| `([^`]+)` \|", README, flags=re.MULTILINE)
        self.assertGreaterEqual(len(rows), 6)
        for option, documented in rows:
            with self.subTest(option=option):
                actual = getattr(defaults, option[2:].replace("-", "_"))
                self.assertEqual(documented, str(actual))

    def test_example_output_is_what_the_program_really_prints(self):
        match = re.search(r"## Example output.*?```text\n(.*?)\n```", README, flags=re.DOTALL)
        self.assertIsNotNone(match, "README has no ```text block under '## Example output'")
        with tempfile.TemporaryDirectory() as folder:
            shutil.copytree(PROJECT_ROOT / "data", Path(folder) / "data")
            run = subprocess.run([sys.executable, str(PROJECT_ROOT / "main.py")],
                                 cwd=folder, capture_output=True, text=True, check=True)
        self.assertEqual(match.group(1).rstrip(), run.stdout.rstrip(),
                         "the example output in README.md is out of date; re-run python main.py and paste it in")


class ReadmeStructureTests(unittest.TestCase):
    def test_required_sections_exist(self):
        for heading in ("Features (implemented and tested)", "What is not included",
                        "Architecture and data flow", "Requirements and setup", "Example command",
                        "Input CSV schema and sample rows", "Configuration options", "Example output",
                        "Rule definitions and assumptions", "Running the tests", "Known limitations",
                        "Future improvements (not implemented)"):
            with self.subTest(heading=heading):
                self.assertIn(f"\n## {heading}\n", README)

    def test_the_readme_states_that_flags_are_not_proof_of_fraud(self):
        lowered = README.lower()
        self.assertIn("not** a fraud detection system", lowered)
        self.assertIn("not proof of fraud", lowered)
        self.assertIn("no machine learning", lowered)

    def test_every_module_listed_in_the_layout_exists(self):
        layout = README.split("## Project layout")[1]
        for name in re.findall(r"^\s+(\w+\.py)\s", layout, flags=re.MULTILINE):
            with self.subTest(module=name):
                self.assertTrue(any(PROJECT_ROOT.rglob(name)), f"{name} is listed in the README but missing")


if __name__ == "__main__":
    unittest.main()
