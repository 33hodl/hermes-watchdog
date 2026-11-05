#!/usr/bin/env python3
"""Close the oldest open PRs to get under the repo's 5-open-PR contributor cap.

Usage:  python3 docs/triage_open_prs.py [--apply]

Records every closed PR (with its branch) in docs/closed-prs-2026-11-05.md so any
of them can be reopened with `gh pr reopen N --repo NousResearch/hermes-agent`.
"""
from __future__ import annotations

import json
import subprocess
import sys

REPO = "NousResearch/hermes-agent"
KEEP = 4  # leave room for the new catalog PR (cap is 5)


def gh(*args: str) -> str:
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=True).stdout


def main() -> int:
    apply_changes = "--apply" in sys.argv
    raw = gh("api", f"search/issues?q=repo:{REPO}+type:pr+state:open+author:33hodl&per_page=50")
    items = json.loads(raw, strict=False)["items"]
    rows = [
        (str(i["number"]), i["created_at"][:10], i["title"].replace("|", "/"),
         (i.get("pull_request") or {}).get("head", {}).get("ref", ""))
        for i in items
    ]
    rows.sort(key=lambda r: r[1])
    close, keep = rows[:-KEEP], rows[-KEEP:]

    def branch_of(num: str) -> str:
        try:
            data = json.loads(gh("api", f"repos/{REPO}/pulls/{num}"), strict=False)
            return str((data.get("head") or {}).get("ref") or "")
        except Exception:
            return ""

    rows = [(n, d, t, branch_of(n) or "-") for n, d, t, _b in rows]
    close, keep = rows[:-KEEP], rows[-KEEP:]
    print(f"open={len(rows)} closing={len(close)} keeping={[r[0] for r in keep]}")

    if apply_changes:
        for num, *_ in close:
            subprocess.run(["gh", "pr", "close", num, "--repo", REPO], capture_output=True, text=True)
            print("closed", num)

    lines = [
        "# Closed to get under the repo's 5-open-PR contributor cap",
        "",
        f"`{REPO}` caps contributors without write access at 5 open pull requests",
        "([cli/cli#14874](https://github.com/cli/cli/issues/14874)). "
        f"{len(rows)} were open, so the {len(close)} oldest were closed on 2026-11-05 to make room",
        "for the `hermes-watchdog` plugin-catalog PR.",
        "",
        "Branches are untouched. Reopen any of them with:",
        "",
        "```bash",
        f"gh pr reopen <N> --repo {REPO}",
        "```",
        "",
        "| PR | opened | title | branch |",
        "|---|---|---|---|",
    ]
    lines += [f"| #{n} | {d} | {t} | `{b}` |" for n, d, t, b in close]
    lines += ["", "## Left open", "", "| PR | opened | title | branch |", "|---|---|---|---|"]
    lines += [f"| #{n} | {d} | {t} | `{b}` |" for n, d, t, b in keep]
    from pathlib import Path
    Path(__file__).with_name("closed-prs-2026-11-05.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("doc written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
