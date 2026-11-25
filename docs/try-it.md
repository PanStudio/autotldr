# Try AutoTLDR in ten minutes

AutoTLDR reads and renders everything on your machine. For prose it borrows one model
from any OpenAI-compatible server you can reach: LM Studio on your laptop, a llama.cpp
or Ollama node on your network, or a gateway such as LiteLLM in front of several nodes.
Only the bounded evidence pack for each run travels to that server.

## 1. Install

```bash
git clone https://github.com/akougkas/AutoTLDR.git
cd AutoTLDR
uv venv --python 3.12
uv pip install -e '.[all]'
source .venv/bin/activate
autotldr --version
```

## 2. Point it at your inference server

Use a separate configuration for this trial so your usual settings stay untouched:

```bash
autotldr_try="$(mktemp -d)"
export AUTOTLDR_CONFIG="$autotldr_try/config.toml"
```

Pick the line that matches your setup. Without `--model`, setup prints the server's
model list so you can copy an exact ID.

```bash
# A gateway that requires a key (the key stays in the environment, never in the config)
export LITELLM_API_KEY=...
autotldr setup --base-url http://gateway-host:4000/v1 --api-key-env LITELLM_API_KEY

# A llama.cpp, vLLM, or Ollama server on another machine
autotldr setup --base-url http://inference-host:8080/v1

# LM Studio on this machine (the default)
autotldr setup
```

Then rerun setup with `--model EXACT_ID` and check the connection end to end:

```bash
autotldr doctor
```

`doctor` sends one small synthetic request. On servers that load models on demand, the
first request waits for the load; if it times out, rerun `doctor` or raise the limit with
`setup --force --timeout 300`.

## 3. Try a mixed technical package

```bash
python acceptance/build_edge_telemetry.py "$autotldr_try/inputs"
autotldr "$autotldr_try/inputs" --detail brief
```

The package holds a README, a spreadsheet, a SQLite database, a Parquet table, and a
NetCDF file. Read the opening claims and follow one citation back to its source.

```bash
autotldr "$autotldr_try/inputs/capacity.xlsx" --detail deep
autotldr "$autotldr_try/inputs" --detail deep --budget 262144 -o "$autotldr_try/brief.html"
xdg-open "$autotldr_try/brief.html"   # macOS: open
```

Look for formula dependencies, documented assumptions, source links, and explicit gaps.

To compare models for a single run without changing the configuration:

```bash
autotldr "$autotldr_try/inputs" --detail brief --model ANOTHER_EXACT_ID
```

To see the native evidence with no model at all, add `--model off`.

## 4. Try your own material

```bash
autotldr --detail standard -- "/absolute/path/to/your/file-or-folder"
```

Choose material you are comfortable sending, as an evidence pack, to the server you
configured.

## If you hit a snag

- **Cannot reach the server:** check the base URL from this machine with
  `curl BASE_URL/models`.
- **HTTP 401:** export the variable named by `--api-key-env` in the current shell.
- **Model not listed:** copy an ID from the list in the error message.
- **Budget too small:** increase `--budget` to at least the minimum shown in the error.
- **A claim seems wrong:** inspect its citation and compare with `--model off`. A valid
  citation is not proof that the model's interpretation is right.

When finished, run `unset AUTOTLDR_CONFIG` to return to your usual configuration.
