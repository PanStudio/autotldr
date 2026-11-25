# AutoTLDR for PanCode

This pack adds AutoTLDR's MCP server to PanCode. It serves one tool,
`autotldr_summarize`, which reads local files and directories and returns what
they mean with every claim addressed back to its source. AutoTLDR and this pack
are MIT licensed.

## Install

Once the pack is listed in PanHub:

```bash
pancode hub install plugin:autotldr
```

From a checkout of this repository:

```bash
pancode hub install <checkout>/pancode --user
```

Installing launches nothing.

## Approve it

PanCode asks for two approvals before the model can call the tool:

```bash
pancode mcp trust autotldr             # approves the launch
pancode mcp trust autotldr --surface   # approves the tool surface it serves
```

`pancode mcp test autotldr --call autotldr_summarize --args '<json>'` checks the
server from outside a session.

## Launch and pin

The server starts as `uvx --from autotldr==0.2.0 autotldr-mcp`. The exact version
pins what uv is asked to install, not the bytes PyPI serves for it. The first
launch downloads the package from PyPI, so it needs network access, and `uvx` must
be on `PATH`.

## What it can read

A pack's arguments are fixed text, so it cannot name your project. The server is
rooted at your home directory (`--root ~`) and started with
`--refuse-hidden-sources`: it can read any visible file under your home directory,
and it refuses any source whose resolved path passes through a directory or file
whose name starts with `.`, such as `~/.ssh` or `~/.config`, including through a
visible symlink. Directory walks skip hidden entries and never follow symlinks.

To confine it to one project, declare the server yourself in PanCode's user
`mcp.yaml` (`~/.config/pancode/mcp.yaml` on Linux) with that root, and disable the
pack with `pancode hub disable plugin:autotldr`:

```yaml
version: 1
servers:
  - id: autotldr-project
    command: uvx
    args: [--from, "autotldr==0.2.0", autotldr-mcp, --root, /path/to/project, --refuse-hidden-sources]
    timeoutMs: 600000
    toolActionClasses:
      autotldr_summarize: read
```

## Action class

`autotldr_summarize` is classed `read`. It changes no file of yours; the only
thing it writes is its own task state, owner-only, under
`$XDG_STATE_HOME/autotldr/mcp-tasks` (`~/.local/state/autotldr/mcp-tasks` by
default). In prose mode it sends a bounded evidence pack to the model you
configured, the same exposure as PanCode's own read tool handing file content to
the session model. The pack declares no `toolPathArguments`: `sources` is an array,
and AutoTLDR's own root check is the boundary.

The request timeout is 600000 ms because prose runs wait on model requests. A
directory, archive or multi-source call returns an MCP task at once and is polled,
so the timeout bounds one request, not the whole run.

## Evidence and prose

Evidence mode (`"mode": "evidence"`) needs no model and works offline. Prose
mode, the default, uses the model in your AutoTLDR configuration
(`~/.config/autotldr/config.toml`, written by `autotldr setup`). PanCode passes
the server no credential, so prose mode works from this pack only with a model
server that takes no key, such as the default `http://127.0.0.1:1234/v1`.

Inside a PanCode fleet worker, the server's process reaches the network, even a
model on the loopback address, only after you approve the launch with the grant:

```bash
pancode mcp trust autotldr --network
```

Approving it again without `--network` drops the grant.

## Formats that need an extra

The pack installs AutoTLDR without extras: the base package uses the Python
standard library only. A file whose format needs an extra answers
`MISSING_OPTIONAL_DEPENDENCY` and names the extra. To add one, declare the server
in your user `mcp.yaml` as above with `--from "autotldr[pdf]==0.2.0"` (or `office`,
`structured`, `code`, `web`, `data`, `all`). The `code` extra has wheels for
Python 3.12 only, so add `--python`, `"3.12"` before `--from` when you use it. The
`pdf` extra brings PyMuPDF, which is licensed AGPL.
