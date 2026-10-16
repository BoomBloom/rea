# REA evaluation for the BuildAlpha investigation

Date: 2026-10-16. REA version 6.5.0, built from `BoomBloom/rea` (fork of
`morluto/rea`) at commit `180ba03`.

## What REA is (verified from the repository)

REA ("Reverse Engineer Anything") is a Node.js MCP server plus CLI that gives an
agent evidence-producing analysis tools: native binaries (through Hopper, Ghidra
or IDA), JavaScript/Electron apps, static .NET (PE/CLI) metadata and CIL,
websites through the Chrome DevTools Protocol, network captures (HAR/SAZ/pcap),
Android packages and more (`README.md`, "What you can analyze"). Every result
is an Evidence record with provenance, confidence and limitations.

## Setup performed in this environment

| Step                          | Command                                                                                                                                                                        | Result                                                                                                                |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------- |
| Install locked dependencies   | `npm ci` (Node 22.22.0; REA requires >=22.19)                                                                                                                                  | OK                                                                                                                    |
| Build                         | `npm run build:cached`                                                                                                                                                         | OK, 3 turbo tasks                                                                                                     |
| Readiness                     | `node scripts/rea.mjs doctor --json`                                                                                                                                           | Node/host healthy; no native engines (Hopper/Ghidra/IDA/JADX/Kuna) configured, which only matters for binary analysis |
| Register with Claude Code     | `claude mcp add --scope local rea -- node /home/claude/rea/scripts/rea.mjs mcp` (backup of `~/.claude.json` taken first; local scope per `docs/installation.md` "One project") | `claude mcp list` shows `rea ... √ Connected`                                                                         |
| MCP verification              | Stdio MCP client (`@modelcontextprotocol/client`) → `listTools`                                                                                                                | Server `rea` 6.5.0, **207 tools**                                                                                     |
| Browser workflow verification | Headless Chromium with CDP on 127.0.0.1:9222; MCP `list_browser_targets`; CLI `inspect-web-page` on a reachable control page (github.com/morluto/rea)                          | Both returned Evidence records (`rea.browser-target-list`, DOM/scripts/resources/network capture)                     |

REA lives entirely in the repository's own `node_modules`; the trading
application in `alphaforge/` has a separate Python environment and shares no
dependencies with it.

## Using REA on BuildAlpha: what happened

1. **Website (buildalpha.com)**: blocked. This cloud container's egress proxy
   refuses `buildalpha.com` (`CONNECT tunnel failed, response 403`). Chromium
   loaded an error document, and `inspect-web-page` on that target returned
   `target_unavailable` / `target_not_allowed`. REA works (the control page
   succeeded); the network policy is the blocker. Fix: allow `buildalpha.com`
   in a project cloud environment, or run REA on a machine that can reach it.
2. **Desktop application**: not attempted. BuildAlpha is a Windows-only
   .NET Framework 4.0 application (vendor FAQ) with no public trial. REA's static
   managed-code tools (`inspect-managed-artifact`, `inspect-managed-members`)
   would be a strong technical fit, _but_ they need the program files, which
   require a license, and decompiling licensed software can breach its terms.
   We do not do this without the user owning a license and confirming the
   license permits analysis.

## Where REA adds genuine value (once the site is reachable)

- `inspect-web-page` / `capture-web-screenshot`: render JavaScript-gated pages
  (the licensing page is unreadable without JavaScript) and record exactly
  what was observed, with timestamps and digests, as citable evidence.
- `analyze-web-bundle`: shows whether any part of the product (e.g. a web
  demo or account portal) runs client-side logic worth studying. For a
  WordPress marketing site we expect little beyond content.
- Evidence bundles make the feature inventory reproducible and auditable.

## Where REA adds little

- Strategy-generation algorithms, fill models and robustness formulas live in
  the desktop program, not on the website. REA cannot recover them remotely.
- For reading public documentation text, a plain fetch is cheaper and
  equivalent. We used one for the inventory.

## Conclusion

REA is installed, registered and verified here. Its realistic contribution to a
_remote_ BuildAlpha investigation is citable observation of the public website,
currently blocked by network policy. It cannot reveal BuildAlpha's internals
without a licensed binary. The product is therefore designed from public feature
descriptions and from published quantitative-finance methods, not from
BuildAlpha's code.
