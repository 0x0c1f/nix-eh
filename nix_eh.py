"""Dependency-free, conservative Nix diagnostic reader."""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


# Colour codes are stripped before matching, so coloured and plain logs parse
# the same way.
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
ERROR = re.compile(r"^\s*error:\s*(.*)")
LOCATION = re.compile(r"(?:at\s+)?(/[^\n]+?:\d+:\d+)")


def summarize(raw):
    """Classify a raw Nix log and return a dict of summary fields.

    Never raises for unrecognised input: a log without an error line yields
    error_count 0, so callers can fall back to the original text.
    """
    lines = ANSI.sub("", raw).splitlines()
    errors = [(i, m.group(1)) for i, line in enumerate(lines) if (m := ERROR.match(line))]
    if not errors:
        return {
            "summary": "No structured Nix error found.",
            "location": None,
            "details": [],
            "error_count": 0,
            "suggestion": None,
        }

    # Nix commonly prints evaluation frames before the final error. This is a
    # presentation heuristic, not proof that the last error is the root cause.
    index, headline = errors[-1]
    tail = lines[index + 1 :]
    details = []
    for line in tail:
        if line.strip():
            details.append(line.rstrip())
    headline = headline or (details.pop(0).strip() if details else "Nix reported an error.")

    # Insecure-package refusals get a dedicated result that lists the Nixpkgs
    # known issues instead of a generic headline.
    insecure = re.search(
        r"Package [‘'\"](.+?)[’'\"] in (.+?:\d+(?::\d+)?) is marked as insecure", headline
    )
    if insecure:
        package, location = insecure.groups()
        reasons = []
        collecting = False
        for line in tail:
            if line.strip() == "Known issues:":
                collecting = True
                continue
            if collecting and line.strip():
                if not line.lstrip().startswith("- "):
                    break
                reasons.append(line.strip()[2:])
        eol = any(re.search(r"\bEOL\b|end.of.life", reason, re.I) for reason in reasons)
        summary = (
            f"{package} is blocked because it is end-of-life."
            if eol
            else f"{package} is blocked because Nixpkgs marks it as insecure."
        )
        return {
            "summary": summary,
            "location": location,
            "details": reasons or ["Nixpkgs refused to evaluate this package."],
            "error_count": len(errors),
            "category": "insecure-package",
            "package": package,
            "reasons": reasons,
            # Overrides are mentioned only as a warning: they lift the block without
            # removing the vulnerable package.
            "suggestion": "Identify which app or dependency selects this package, then update or replace it. "
            "This trace does not identify the dependent app. "
            "The original log includes override instructions; these bypass the block and do not fix the issue.",
        }

    # Search the headline first, because some messages carry their location inline.
    nearby = [headline] + tail + list(reversed(lines[:index]))
    location = next((m.group(1) for line in nearby if (m := LOCATION.search(line))), None)

    # Suggestions are keyword heuristics on the headline; they point at what to
    # inspect rather than claiming a definite fix.
    lower = headline.lower()
    suggestion = None
    if "undefined variable" in lower or "attribute" in lower and "missing" in lower:
        suggestion = (
            "Check spelling and whether this name exists in the current scope or package set."
        )
    elif "does not exist" in lower and "option" in lower:
        suggestion = (
            "Check the option name and whether its module is imported for your NixOS version."
        )
    elif "syntax error" in lower:
        suggestion = (
            "Inspect the reported location and the preceding expression for missing punctuation."
        )
    elif "hash mismatch" in lower:
        suggestion = "Verify the source and revision before changing the expected hash."
    elif "builder for" in lower or "dependencies" in lower and "failed" in lower:
        suggestion = (
            "Inspect the failed derivation's build log; this message may be a downstream failure."
        )
    return {
        "summary": headline,
        "location": location,
        "details": details,
        "error_count": len(errors),
        "suggestion": suggestion,
    }


def render(raw, full=False):
    """Return the human-readable report for a raw log.

    Unrecognised input is returned unchanged so nothing is hidden from the user;
    full=True appends the original diagnostics.
    """
    result = summarize(raw)
    if not result["error_count"]:
        return raw.rstrip() or "No diagnostics received."
    out = ["Nix error", "", result["summary"]]
    if result["location"]:
        out += ["", "Location: " + result["location"]]
    if result["details"]:
        out += ["", "Details:"] + result["details"][:8]
        if len(result["details"]) > 8:
            out.append("  ... additional details available with --full")
    if result["suggestion"]:
        out += ["", "Suggestion: " + result["suggestion"]]
    if result["error_count"] > 1:
        out += ["", f"{result['error_count']} error entries; showing the last reported error."]
    if full:
        out += ["", "Original diagnostics:", raw.rstrip()]
    else:
        out += ["", "Use --full for the original diagnostics."]
    return "\n".join(out)


def main(argv=None):
    """Run the command-line interface and return the process exit status.

    In run mode the wrapped command's status is returned unchanged, with signals
    mapped to 128 plus the signal number as shells report them.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--json", action="store_true", help="Include original diagnostics in JSON")
    modes = parser.add_subparsers(dest="mode", required=True)
    read = modes.add_parser("read", help="Read a saved log, or stdin with -")
    read.add_argument("file", nargs="?", default="-")
    run = modes.add_parser("run", help="Run a command; stream stdout and summarize stderr on exit")
    run.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    status = 0
    try:
        if args.mode == "read":
            raw = (
                sys.stdin.read()
                if args.file == "-"
                else Path(args.file).read_text(encoding="utf-8", errors="replace")
            )
        else:
            command = args.command
            if command[:1] == ["--"]:
                command = command[1:]
            if not command:
                parser.error("run requires a command after --")

            # Only stderr is captured; stdout passes straight through so command output
            # still streams as it is produced.
            proc = subprocess.Popen(command, stderr=subprocess.PIPE)
            try:
                _, diagnostic = proc.communicate()

            # Stop the child on Ctrl-C and report the conventional interrupt status.
            except KeyboardInterrupt:
                proc.terminate()
                proc.communicate()
                return 130
            raw = diagnostic.decode("utf-8", errors="replace")
            status = proc.returncode if proc.returncode >= 0 else 128 - proc.returncode

        # In run mode the report goes to stderr so it never mixes with the command's
        # own stdout.
        if args.json:
            print(
                json.dumps(
                    {**summarize(raw), "original": raw, "exit_code": status}, ensure_ascii=True
                ),
                file=sys.stderr if args.mode == "run" else sys.stdout,
            )
        elif raw or args.mode == "read":
            print(render(raw, args.full), file=sys.stderr if args.mode == "run" else sys.stdout)
        return status
    except OSError as exc:
        print(f"nix-eh: {exc}", file=sys.stderr)

        # 127 matches the shell's status for a command that cannot be found.
        return 127 if args.mode == "run" and isinstance(exc, FileNotFoundError) else 1


if __name__ == "__main__":
    sys.exit(main())
