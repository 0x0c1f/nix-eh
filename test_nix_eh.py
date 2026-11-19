"""Exercise diagnostic summaries against captured Nix output.

The fixtures keep error evidence stable without requiring this machine to
evaluate or build the original failing configuration.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path
import nix_eh

HERE = Path(__file__).parent


class Diagnostics(unittest.TestCase):
    """Summaries and rendering for captured logs, plus the run and read commands."""

    def test_nested_error_and_location(self):
        result = nix_eh.summarize((HERE / "examples/missing-attribute.log").read_text())

        self.assertEqual(result["summary"], "attribute 'gittt' missing")
        self.assertEqual(result["location"], "/etc/nixos/configuration.nix:12:26")
        self.assertEqual(result["error_count"], 2)

    def test_ansi_multiline_and_full(self):
        raw = "\x1b[31merror: syntax error\x1b[0m\n" + "\n".join(f"detail {i}" for i in range(20))

        self.assertNotIn("detail 19", nix_eh.render(raw))
        self.assertIn(raw, nix_eh.render(raw, True))
        self.assertIn("syntax error", nix_eh.summarize(raw)["summary"])

    # Unrecognised input must come back unchanged rather than being reworded.
    def test_unrecognized_and_empty(self):
        self.assertEqual(nix_eh.render("warning: hello"), "warning: hello")
        self.assertEqual(nix_eh.render(""), "No diagnostics received.")

    def test_empty_error_header(self):
        self.assertEqual(
            nix_eh.summarize("error:\n  A multiline failure")["summary"], "A multiline failure"
        )

    # The wrapper must not alter arguments, stdout or the exit status of the command.
    def test_wrapper_exit_stdout_and_arguments(self):
        code = "import sys; print(sys.argv[1]); print('error: bad input', file=sys.stderr); sys.exit(7)"
        p = subprocess.run(
            [
                sys.executable,
                str(HERE / "nix_eh.py"),
                "--json",
                "run",
                "--",
                sys.executable,
                "-c",
                code,
                "argument with spaces",
            ],
            capture_output=True,
            text=True,
        )

        self.assertEqual(p.returncode, 7)
        self.assertEqual(p.stdout.strip(), "argument with spaces")
        self.assertEqual(json.loads(p.stderr)["summary"], "bad input")

    # A successful command's warnings are passed through as they were printed.
    def test_success_warning_passthrough(self):
        p = subprocess.run(
            [
                sys.executable,
                str(HERE / "nix_eh.py"),
                "run",
                "--",
                sys.executable,
                "-c",
                "import sys; print('warning: hello', file=sys.stderr)",
            ],
            capture_output=True,
            text=True,
        )

        self.assertEqual(p.returncode, 0)
        self.assertEqual(p.stderr.strip(), "warning: hello")

    # 127 matches what a shell reports for a command that cannot be found.
    def test_missing_command(self):
        p = subprocess.run(
            [sys.executable, str(HERE / "nix_eh.py"), "run", "--", "nix-eh-nonexistent-command"],
            capture_output=True,
        )

        self.assertEqual(p.returncode, 127)

    # The compact view must drop the override hint and noisy frames, while the
    # full view keeps every original line.
    def test_insecure_electron(self):
        raw = (HERE / "examples/insecure-electron.log").read_text(encoding="utf-8")
        result = nix_eh.summarize(raw)

        self.assertEqual(result["summary"], "electron-36.9.5 is blocked because it is end-of-life.")
        self.assertEqual(result["category"], "insecure-package")
        self.assertTrue(result["location"].endswith("generic.nix:43"))
        self.assertEqual(result["reasons"], ["Electron version 36.9.5 is EOL"])
        compact = nix_eh.render(raw)
        self.assertNotIn("ALLOW_INSECURE=1", compact)
        self.assertNotIn("while calling", compact)
        self.assertNotIn("fontconfig", compact)
        self.assertIn("does not identify the dependent app", compact)
        self.assertIn(raw.rstrip(), nix_eh.render(raw, True))
        self.assertLess(len(compact), len(raw))

    def test_insecure_non_eol_and_quote_styles(self):
        for left, right in [("‘", "’"), ("'", "'"), ('"', '"')]:
            raw = f"error: Package {left}demo-1{right} in /nix/store/source/package.nix:4:2 is marked as insecure, refusing to evaluate.\nKnown issues:\n - CVE-example\n - Another issue\n\nOverride instructions"
            result = nix_eh.summarize(raw)
            self.assertIn("marks it as insecure", result["summary"])
            self.assertEqual(result["location"], "/nix/store/source/package.nix:4:2")
            self.assertEqual(len(result["reasons"]), 2)

    def test_insecure_no_issues(self):
        result = nix_eh.summarize(
            "error: Package 'demo-1' in /nix/store/source/package.nix:4 is marked as insecure, refusing to evaluate."
        )

        self.assertEqual(result["reasons"], [])
        self.assertNotIn("end-of-life", result["summary"])

    # JSON output must carry the original log unchanged.
    def test_insecure_cli_json_original(self):
        fixture = HERE / "examples/insecure-electron.log"
        p = subprocess.run(
            [sys.executable, str(HERE / "nix_eh.py"), "--json", "read", str(fixture)],
            capture_output=True,
            text=True,
        )

        self.assertEqual(p.returncode, 0)
        result = json.loads(p.stdout)
        self.assertEqual(result["package"], "electron-36.9.5")
        self.assertEqual(result["original"], fixture.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
