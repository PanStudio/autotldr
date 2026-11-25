<p align="center">
  <img src="assets/autotldr_logo_transparent.png" alt="AutoTLDR" width="180" />
</p>

<h1 align="center">AutoTLDR</h1>

<p align="center"><strong>Understand technical work. Follow the evidence.</strong></p>

AutoTLDR turns a file, a mixed folder, an archive, or a documentation URL into a
concise, cited brief. A spreadsheet contributes its formula dependencies; a database
contributes its schema; scientific data contributes dimensions and units. A model then
explains the selected evidence, with references you can follow back to the source.

```bash
autotldr model.xlsx
autotldr ./research --detail brief
autotldr paper.pdf results.parquet analysis.ipynb --detail deep
autotldr ./handoff --out html --budget 262144 -o brief.html
```

**v0.2.0 is being prepared for release.** The CLI, configuration, and output schemas may
evolve during 0.x development. [Release notes](docs/changelog.md) · [Try it](docs/try-it.md)

## Why AutoTLDR

- **Native meaning.** Read formulas, schemas, symbols, and scientific metadata in their
  original formats instead of flattening everything into text.
- **Evidence you can inspect.** Accepted claims cite existing evidence; AutoTLDR derives
  their source locations and rejects unknown references and model substitutions.
- **Visible gaps.** Missing documentation, unsupported inputs, and incomplete extraction
  remain part of the result.
- **An exact output budget.** The complete artifact fits the requested byte ceiling, with
  an inventory of what was omitted. If it cannot fit, the command explains why.
- **Your infrastructure.** Reading, extraction, and rendering run on your machine. Prose
  comes from any OpenAI-compatible server you choose: LM Studio on your laptop, llama.cpp
  on another node, or an authenticated gateway. Extraction also works without a model.

## Install

Use **Python 3.12**, a Unix-like terminal (Linux, macOS, or WSL), and
[`uv`](https://docs.astral.sh/uv/getting-started/installation/). Python 3.12 is the
qualified version for the complete optional parser set.

From a checkout:

```bash
git clone https://github.com/akougkas/AutoTLDR.git
cd AutoTLDR
uv venv --python 3.12
uv pip install -e '.[all]'
source .venv/bin/activate
autotldr --version
```

If you already have the checkout, start at `uv venv`. The `[all]` extra installs every
supported parser. The base package has no runtime dependencies; narrower installs can
use the `office`, `pdf`, `code`, `structured`, `web`, or `data` extras.

Check extraction immediately:

```bash
autotldr README.md --model off --detail brief
autotldr formats
```

`--model off` produces an evidence map. Ordinary commands use a configured model to write
the prose brief. The [installation guide](docs/install-guide.md) also covers installing
the exact wheel from a release bundle; no PyPI package publication is claimed yet.

## Connect the AI

AutoTLDR borrows inference from one OpenAI-compatible server and one exact model. Only
the bounded evidence pack for a run is sent to that server; your files are read and
rendered locally. AutoTLDR never downloads, loads, or swaps models.

```bash
# LM Studio, Ollama, or llama.cpp on this machine (the default base URL is LM Studio's)
autotldr setup --model EXACT_MODEL_ID
autotldr setup --base-url http://127.0.0.1:8080/v1 --model EXACT_MODEL_ID

# A server elsewhere on your network
autotldr setup --base-url http://inference-node:8080/v1 --model EXACT_MODEL_ID

# An authenticated gateway such as LiteLLM; the key stays in your environment
export LITELLM_API_KEY=...
autotldr setup --base-url http://gateway:4000/v1 --api-key-env LITELLM_API_KEY \
  --model node/EXACT_MODEL_ID

autotldr doctor
```

Setup reads the server's `/v1/models` catalog and refuses a model that is not listed.
Without `--model`, it lists what the server offers. `doctor` sends one small synthetic
request and reports whether the model returned an acceptable cited answer. To try a
different model for one run, pass `--model OTHER_ID`; the configured server stays in force.

Any server that implements chat completions with JSON-schema `response_format` works.
Routers and gateways that load models on demand may make the first request slow, so
setup's `--timeout` (default 120 seconds, maximum 300) applies to each model request.
Use `https://` for servers you reach over untrusted networks.

## Use it

### Choose how much explanation you need

| Detail | Useful for | Maximum prose claims |
| --- | --- | --- |
| `brief` | A quick orientation | 2 |
| `standard` | Everyday understanding; the default | 4 |
| `deep` | A technical handoff or closer inspection | 6 |

These are ceilings, not padding targets. Detail controls the evidence available to the
model and the supporting evidence shown in human output.

```bash
autotldr ./experiment --detail brief
autotldr model.xlsx --detail deep
autotldr https://docs.example.org/guide --crawl --detail standard
```

### Save or share a result

```bash
autotldr report.pdf -o brief.md
autotldr ./experiment --budget 262144 -o brief.html
autotldr ./experiment --budget 1048576 -o brief.pdf
autotldr ./experiment --out json --budget 262144 -o context.json
printf '# Notes\nThe service stores events in SQLite.\n' | autotldr - --type md
```

The six output formats are **ANSI, Markdown, HTML, PDF, JSON, and JSONL**. A recognized
output filename selects its format; `--out` overrides that inference. HTML is self-contained.
JSON and JSONL preserve the complete budget-selected representation at every detail level.

`--budget N` measures the **whole output in bytes**, including citations, formatting,
metadata, and omission records: UTF-8 bytes for text, binary bytes for PDF. It is not the
model's token count. Rich mixed-folder output and PDFs need larger budgets. If the required
minimum cannot fit, exit status `5` names the measured minimum and no partial result is written.

### Keep a folder brief current

```bash
autotldr watch ./inbox --once
autotldr watch ./inbox --recursive --debounce 10
autotldr watch ./inbox --status
```

Watch writes per-file briefs and a folder roll-up beneath `.autotldr/`. It reuses successful
outputs when both the source and effective policy match. Missing outputs and failed work
are retried on subsequent scans; failures remain visible in status and roll-up gaps.

## Supported inputs

| Input | Native evidence |
| --- | --- |
| XLSX / XLSM | Formula dependencies, populated range interiors, structural inputs, hardcoded values, cycles |
| Parquet, SQLite, DuckDB | Schemas, types, constraints, relationships, bounded statistics |
| HDF5, NetCDF, NumPy / NPZ, Arrow, Feather, ORC, FITS | Shapes, dimensions, units, groups, attributes, metadata |
| Markdown, text, JSON, YAML, TOML, XML, CSV, TSV | Addressable prose, structure, schemas, bounded tabular profiles |
| Source code | Symbols, declarations, imports, and native source locations |
| PDF, DOCX, HTML, notebooks, LaTeX, EPUB | Text-layer content and document structure |
| Folders, Git worktrees, ZIP / TAR, documentation sites | Bounded acquisition, source outcomes, cross-file relationships |

`autotldr formats` is the authoritative inventory for your installation, including missing
optional dependencies and named declines. Bulk dataset rows and arrays are not put into
the model's evidence pack. Scanned PDFs, images, audio, and video are outside this release.

Spreadsheet extraction does not calculate formulas. Named ranges, table references,
external references, dynamic targets, and unsupported reference expressions are reported
at the affected formula instead of silently presenting a complete dependency graph.

## Configuration and troubleshooting

```bash
autotldr doctor
autotldr config show
autotldr config paths
autotldr formats
```

Setup writes an owner-only user configuration. A project can use `.autotldr.toml`;
precedence is CLI flags, project settings, user settings, then defaults. `AUTOTLDR_CONFIG`
selects a separate user configuration, useful for trying the tool without changing your
usual setup. `--no-config` ignores configuration files.

| Problem | Next step |
| --- | --- |
| No configured model | Run the appropriate `setup` command above |
| Cannot connect | Check the base URL and that the server is reachable from this machine |
| HTTP 401 | Export the API key named by `api_key_env` in this shell |
| Model is not listed | Use an ID from the list in the error, or rerun `setup --force` |
| Timeout | The model may be loading; retry, or raise `--timeout` with `setup --force` |
| Existing configuration | Inspect `config show`; use `setup --force` only when replacing it |
| Missing parser | Install the extra named in the error, or `[all]` |
| Unsupported input | Check `formats`; exit `3` identifies the format |
| Input not found | Check the path; exit `4` identifies the missing source |
| Budget cannot fit | Increase to the reported minimum; exit `5` writes no partial result |

Model failure is reported; evidence-only fallback is never silent. To inspect extraction
independently, rerun with `--model off`.

## Python and agents

```python
from autotldr import summarize_product

result = summarize_product(
    ["paper.pdf", "results.parquet", "analysis.ipynb"],
    detail="standard", output="json", budget=262144,
)
print(result.rendered)
```

Shell agents use the same CLI. Install the bundled Agent Skill or start a stdio MCP server
with explicit source roots:

```bash
autotldr integrations skill --install /path/to/skills
autotldr mcp --root /path/to/project --root /path/to/data
```

## Trust and current limits

The model receives a bounded evidence pack and returns claim text plus existing unit IDs.
AutoTLDR validates the response, derives origins, and rejects known authority errors.
**A valid citation does not independently prove that a sentence is entailed.** Follow
important citations and evaluate the result against your sources.

Native parsers run with your process permissions. Generated reports can contain source
content and paths. Exact budgeting can be slow for large collections, and full provenance
can consume substantial JSON or PDF space. See [security and data boundaries](docs/security.md)
and the [audit](docs/public-alpha-audit.md) for the measured limits.

## Development

```bash
uv sync --locked --all-extras --dev
uv run pytest
uv build
uv run python scripts/check_release.py dist
```

The suite enforces lazy imports, a Tier 0 cold-start contract, warnings as errors, native
parser behavior, source authority, grounded synthesis, exact budgets, and package contents.

Start with the [vision](docs/vision.md), [product contract](docs/product-alpha.md),
[technical specification](docs/spec-v1.md), and [decision log](docs/decisions.md).
The [first-user study](docs/first-user-validation.md) remains a follow-up learning plan.

## License

MIT. See [LICENSE](LICENSE).
