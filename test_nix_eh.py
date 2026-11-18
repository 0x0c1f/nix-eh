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


# Use captured diagnostics rather than real failing rebuilds so each parsing
# case is repeatable without changing or evaluating a host configuration.
class Diagnostics(unittest.TestCase):
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

    def test_unrecognized_and_empty(self):
        self.assertEqual(nix_eh.render("warning: hello"), "warning: hello")
        self.assertEqual(nix_eh.render(""), "No diagnostics received.")

    def test_empty_error_header(self):
        self.assertEqual(
            nix_eh.summarize("error:\n  A multiline failure")["summary"], "A multiline failure"
        )

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

    def test_missing_command(self):
        p = subprocess.run(
            [sys.executable, str(HERE / "nix_eh.py"), "run", "--", "nix-eh-nonexistent-command"],
            capture_output=True,
        )

        self.assertEqual(p.returncode, 127)


if __name__ == "__main__":
    unittest.main()
