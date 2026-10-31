"""Tests for scripts/generate_data.py: the synthetic dataset must be reproducible and its answer key honest."""
import csv
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = PROJECT_ROOT / "scripts" / "generate_data.py"
COMMITTED_DATA = PROJECT_ROOT / "data" / "transactions.csv"
COMMITTED_KEY = PROJECT_ROOT / "data" / "planted_cases.csv"


def generate(folder, seed=None):
    """Run the generator into a folder. Returns (dataset_path, answer_key_path)."""
    dataset, key = Path(folder) / "transactions.csv", Path(folder) / "planted_cases.csv"
    command = [sys.executable, str(SCRIPT), "--output", str(dataset), "--answer-key", str(key)]
    if seed is not None:
        command += ["--seed", str(seed)]
    subprocess.run(command, check=True, capture_output=True, text=True)
    return dataset, key


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


class GeneratorTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)

    def test_the_same_seed_gives_identical_files(self):
        (self.root / "a").mkdir()
        (self.root / "b").mkdir()
        data_a, key_a = generate(self.root / "a")
        data_b, key_b = generate(self.root / "b")
        self.assertEqual(data_a.read_bytes(), data_b.read_bytes())
        self.assertEqual(key_a.read_bytes(), key_b.read_bytes())

    def test_committed_data_files_are_exactly_what_the_generator_produces(self):
        data, key = generate(self.root)
        self.assertEqual(data.read_bytes(), COMMITTED_DATA.read_bytes(),
                         "data/transactions.csv was edited by hand or the generator changed; "
                         "run: python scripts/generate_data.py")
        self.assertEqual(key.read_bytes(), COMMITTED_KEY.read_bytes())

    def test_a_different_seed_changes_the_background_but_not_the_planted_cases(self):
        (self.root / "s1").mkdir()
        (self.root / "s2").mkdir()
        data_1, key_1 = generate(self.root / "s1", seed=1)
        data_2, key_2 = generate(self.root / "s2", seed=2)
        self.assertNotEqual(data_1.read_bytes(), data_2.read_bytes())

        def planted(key_path):
            return sorted((k["case"], k["expected_result"], k["expected_flags"]) for k in read_csv(key_path))

        self.assertEqual(planted(key_1), planted(key_2))

    def test_every_answer_key_line_points_at_the_row_it_describes(self):
        data, key = generate(self.root)
        lines = data.read_text(encoding="utf-8").split("\n")
        for entry in read_csv(key):
            first_field = next(csv.reader([lines[int(entry["source_line"]) - 1]]))[0]
            with self.subTest(case=entry["case"], line=entry["source_line"]):
                self.assertEqual(first_field, entry["transaction_id"])

    def test_ordinary_rows_stay_small_so_they_cannot_trigger_a_rule(self):
        data, key = generate(self.root)
        planted_lines = {int(k["source_line"]) for k in read_csv(key)}
        for line_number, row in enumerate(read_csv(data), start=2):
            if line_number not in planted_lines:
                self.assertLessEqual(float(row["amount"]), 400.00, msg=f"line {line_number}")


if __name__ == "__main__":
    unittest.main()
