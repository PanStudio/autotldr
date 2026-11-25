# AutoTLDR {{VERSION}} installation guide

Support for this build: **{{SUPPORT}}**

AutoTLDR explains technical artifacts through cited prose and native evidence. Commands,
configuration, and output schemas may evolve during 0.x development. This guide is
rendered with the exact package version and support contact when the release bundle is built.

## Before you begin

You need:

- a Unix-like terminal (Linux, macOS, or WSL);
- Python 3.12;
- [`uv`](https://docs.astral.sh/uv/);
- an OpenAI-compatible inference server you can reach (LM Studio, llama.cpp, vLLM,
  Ollama, or a gateway such as LiteLLM) and the exact ID of one generation model on it.

AutoTLDR does not download, load, or silently select a model. Each prose run sends a
bounded evidence pack to the configured server, wherever it runs. URL inputs make
outbound HTTP(S) requests.

## Install this exact build

Run these commands from the directory containing this guide and the `packages/` folder:

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python --find-links packages "autotldr[all]=={{VERSION}}"
source .venv/bin/activate
autotldr --version
```

The final command must print `{{VERSION}}`. The adjacent `SHA256SUMS` file records the
exact files in this bundle.

## Connect the model server

```bash
# LM Studio on this machine (default base URL http://127.0.0.1:1234/v1)
autotldr setup --model EXACT_MODEL_ID

# Any server on your network
autotldr setup --base-url http://inference-host:8080/v1 --model EXACT_MODEL_ID

# A gateway that requires a key; only the variable name is stored
export LITELLM_API_KEY=...
autotldr setup --base-url http://gateway-host:4000/v1 \
  --api-key-env LITELLM_API_KEY --model EXACT_MODEL_ID

autotldr doctor
```

Without `--model`, setup prints the IDs the server lists. `doctor` sends one small
synthetic request and does not read your artifacts. Continue when it reports ready.
The walkthrough is at <https://github.com/akougkas/AutoTLDR/blob/main/docs/try-it.md>.

## Try one real artifact

Quote the path and put `--` before it so a filename cannot become an option:

```bash
autotldr -- "/path/to/your/artifact"
```

The ordinary command returns a prose TLDR with citations, supporting native
evidence, and explicit gaps. Choose a detail level only when it helps your task:

```bash
autotldr --detail brief -- "/path/to/your/artifact"
autotldr --detail standard -- "/path/to/your/artifact"
autotldr --detail deep -- "/path/to/your/artifact"
```

For a machine-readable agent artifact, set an exact complete-output budget:

```bash
autotldr --detail standard --out json --budget 131072 -- "/path/to/your/artifact"
```

If the complete cited result cannot fit, AutoTLDR writes no partial artifact and reports
the measured minimum. Increase the budget rather than truncating the output yourself.

## If something fails

These commands report the installed product state without changing your sources or model:

```bash
autotldr doctor
autotldr formats
autotldr config show
autotldr config paths
```

Common outcomes are intentionally specific:

- exit `2`: invalid command usage;
- exit `3`: named unsupported format or tier;
- exit `4`: input not found; and
- exit `5`: the complete addressable output cannot fit the requested budget.

Do not send source files, source excerpts, credentials, or generated reports through a
public issue. Send the command, AutoTLDR version, platform, exit status, and a redacted
error message to **{{SUPPORT}}**. Suspected security boundary failures should use a private
GitHub security advisory as described in `SECURITY.md`.

## Data boundary

Generated results may contain source paths, extracted content, schema and formula details,
hashes, citations, gaps, and model-run metadata. Store and share them with the same care as
the source. AutoTLDR is not a sandbox; run it with operating-system permissions limited to
the sources it should read.
