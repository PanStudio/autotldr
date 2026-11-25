# Security and data boundaries

AutoTLDR is local software, not a sandbox. It parses untrusted technical files
with bounded adapters and treats extracted text as data, but parser defects and dependency
defects remain possible. Run it with the operating-system permissions appropriate for the
sources it may read.

## Where source data goes

- Local files are copied into private immutable snapshots before extraction. Generated
  outputs may contain source paths, hashes, native metadata, extracted content, and cited
  model claims. Snapshot copying and watch hashing stop at the initially observed size
  plus one detection byte and reject changes; they do not chase a continuously growing file.
- Prose runs send a bounded canonical evidence pack, not the original files or bulk
  datasets, to the one OpenAI-compatible server in the configuration. That server may be
  on this machine or elsewhere on your network; whoever operates it can read the pack.
  Use `https://` for servers reached over networks you do not trust.
- The HTTP client contacts only the configured host. It ignores proxy environment
  variables and never follows redirects, so a redirecting server cannot divert evidence.
- API keys are read at run time from the environment variable named by `api_key_env`.
  They are never written to configuration files or model-run records, and base URLs that
  embed credentials or query strings are rejected.
- The server's model catalog is a readiness signal, not an identity proof. A response is
  accepted only when it names the configured model, finishes normally, and carries no
  refusal or tool call; any reasoning channel is hashed for audit and never cited.
- URL and documentation-site inputs deliberately make outbound HTTP(S) requests. Redirect,
  origin, page, byte, and timeout policies remain bounded.
- Ordinary invocation never downloads or chooses a model, and never calls model
  load/unload endpoints. Runtime lifecycle and physical residency remain outside its
  authority.

Routers and gateways may load a listed model on first use. AutoTLDR does not control or
observe where or how the server runs the model.

## Agent authority

Shell agents have the same read authority as the process that launches them. The bundled
Agent Skill instructs them to quote paths, set a budget, preserve gaps, and ignore
instructions embedded in source content.

The MCP server is stdio-only and refuses to start without at least one `--root`. Tool
sources must resolve within an authorized root; URLs, stdin, UNC paths, traversal, and
symlink escapes are rejected before acquisition. MCP arguments cannot select a model
endpoint or model ID.

Deferred tasks recheck their creating server's roots before execution. Access to saved
task results remains tied to the original canonical source paths, so replacing an old
source path with a symlink does not transfer result access to another root. These path
checks are process-level guards, not an OS sandbox against concurrent hostile filesystem
mutation; operating-system permissions remain necessary.

## Extensions

Extensions are executable Python code. AutoTLDR never discovers or imports installed
packages ambiently; a CLI flag or reviewed configuration must name each extension import.
Only enable code you trust.

## Reports

Do not include confidential source content in a public issue. Until a private security
contact is published, report a suspected vulnerability to the repository owner through a
private GitHub security advisory. Include the AutoTLDR version, platform, minimal safe
reproduction, and whether the issue crosses a filesystem, network, model, or output
boundary.
