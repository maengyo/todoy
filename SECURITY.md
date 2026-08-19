# Security Policy

> 한국어 버전: [SECURITY.ko.md](SECURITY.ko.md)

## Supported versions

todoy is pre-1.0 and pre-release (currently mid-M1, unreleased on PyPI). There is
no version support matrix yet — only the `main` branch is maintained. Once M5
ships a tagged 1.0 release, this section will list which versions receive
security fixes.

## Reporting a vulnerability

Please report security issues privately, **not** in a public GitHub issue.

Preferred: open a
[GitHub private security advisory](https://github.com/maengyo/todoy/security/advisories/new)
on this repository. This notifies the maintainer directly without exposing the
report publicly before a fix is available.

If GitHub advisories aren't accessible to you, open a regular issue asking the
maintainer to contact you through another channel — please don't include
vulnerability details in that initial issue.

## What to expect

todoy is a solo, spare-time project, so please be patient:

- Acknowledgement: best-effort within a few days.
- Fix or mitigation timeline: depends on severity and complexity; no formal
  SLA at this stage.
- Credit: reporters are credited in the fix's release notes / changelog,
  unless you prefer to stay anonymous.

## Scope notes

todoy is a local CLI/desktop tool — it reads and writes a JSON file on your
own machine (default `~/.local/share/todoy/todos.json`, overridable via
`TODOY_DATA_FILE`) and, from M2 onward, local markdown files you point it at.
There is no network service and no remote data. Relevant reports include
things like: path handling around `TODOY_DATA_FILE`, unsafe parsing of the
data file, or (once the TUI/overlay milestones land) terminal escape sequence
or UI injection via todo text. Reports about the MIT license or dependency
licensing should go to the repository's normal issue tracker instead, not a
security advisory.
