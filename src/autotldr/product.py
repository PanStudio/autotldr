"""First-user product profiles and dependency-free configuration.

This module is intentionally standard-library-only.  The CLI imports it only after a
product command or an ordinary invocation has been parsed, so configuration does not
pull a parser or model runtime into the cold-start import graph.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


CONFIG_VERSION = 1
DEFAULT_BASE_URL = "http://127.0.0.1:1234/v1"
DETAIL_NAMES = ("brief", "standard", "deep")


class ProductConfigError(ValueError):
    """A persisted or requested product setting is invalid."""


class ModelUnavailable(ProductConfigError):
    """The configured inference server cannot provide the requested model."""


@dataclass(frozen=True, slots=True)
class DetailProfile:
    """Versioned expansion of one user-facing detail choice."""

    name: str
    evidence_budget_bytes: int
    max_claims: int
    max_output_tokens: int
    include_supporting_units: bool
    reasoning_effort: str | None

    def as_manifest(self) -> dict[str, object]:
        return {
            "schema": "autotldr-detail-profile-v2",
            "name": self.name,
            "evidence_budget_bytes": self.evidence_budget_bytes,
            "max_claims": self.max_claims,
            "max_output_tokens": self.max_output_tokens,
            "include_supporting_units": self.include_supporting_units,
            "reasoning_effort": self.reasoning_effort,
        }


DETAIL_PROFILES: Mapping[str, DetailProfile] = {
    "brief": DetailProfile("brief", 8_000, 2, 512, False, "none"),
    "standard": DetailProfile("standard", 24_000, 4, 1_024, True, "none"),
    "deep": DetailProfile("deep", 48_000, 6, 1_800, True, "none"),
}


@dataclass(frozen=True, slots=True)
class ModelProfile:
    """One OpenAI-compatible server and the exact model AutoTLDR asks it for.

    The server may be local (LM Studio, llama.cpp) or anywhere reachable, such as a
    homelab gateway. Evidence packs are sent to ``base_url``; source acquisition and
    rendering always stay on this machine. The API key itself is never persisted;
    only the name of the environment variable that holds it.
    """

    base_url: str
    model: str
    timeout_seconds: float = 120.0
    api_key_env: str | None = None

    def __post_init__(self) -> None:
        from .transport import normalize_base_url, validate_env_name

        try:
            object.__setattr__(self, "base_url", normalize_base_url(self.base_url))
            if self.api_key_env is not None:
                validate_env_name(self.api_key_env)
        except ValueError as exc:
            raise ProductConfigError(f"model {exc}") from exc
        if (
            type(self.model) is not str
            or not self.model
            or self.model.strip() != self.model
            or any(ord(character) < 32 for character in self.model)
        ):
            raise ProductConfigError("model must be one non-empty, unpadded identifier")
        try:
            self.model.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise ProductConfigError("model must be valid UTF-8") from exc
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not 0 < float(self.timeout_seconds) <= 300
        ):
            raise ProductConfigError("model timeout_seconds must be in (0, 300]")

    def api_key(self) -> str | None:
        """Resolve the key from the environment at use time."""

        if self.api_key_env is None:
            return None
        value = os.environ.get(self.api_key_env)
        if not value:
            raise ModelUnavailable(
                f"environment variable {self.api_key_env} is not set; "
                "export the API key for the configured server"
            )
        return value

    def as_manifest(self) -> dict[str, object]:
        return {
            "base_url": self.base_url,
            "model": self.model,
            "timeout_seconds": float(self.timeout_seconds),
            "api_key_env": self.api_key_env,
        }


@dataclass(frozen=True, slots=True)
class ProductConfig:
    """Resolved user and project preferences for one invocation."""

    detail: str = "standard"
    allow_evidence_fallback: bool = False
    model: ModelProfile | None = None
    extensions: tuple[str, ...] = ()
    sources: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.detail not in DETAIL_PROFILES:
            raise ProductConfigError(
                f"detail must be one of {', '.join(DETAIL_NAMES)}"
            )
        if not isinstance(self.allow_evidence_fallback, bool):
            raise ProductConfigError("allow_evidence_fallback must be a boolean")
        if self.model is not None and type(self.model) is not ModelProfile:
            raise ProductConfigError("model profile is invalid")
        if type(self.extensions) is not tuple or any(
            type(item) is not str or not item or item.strip() != item
            for item in self.extensions
        ):
            raise ProductConfigError("extensions must be an immutable list of imports")
        if len(set(self.extensions)) != len(self.extensions):
            raise ProductConfigError("extensions must not contain duplicates")

    @property
    def detail_profile(self) -> DetailProfile:
        return DETAIL_PROFILES[self.detail]

    def as_manifest(self) -> dict[str, object]:
        return {
            "schema": "autotldr-resolved-product-config-v1",
            "detail": self.detail_profile.as_manifest(),
            "allow_evidence_fallback": self.allow_evidence_fallback,
            "model": None if self.model is None else self.model.as_manifest(),
            "extensions": list(self.extensions),
            "sources": list(self.sources),
        }


def user_config_path() -> Path:
    """Return the one explicit user configuration path."""

    override = os.environ.get("AUTOTLDR_CONFIG")
    if override:
        return Path(override).expanduser()
    root = os.environ.get("XDG_CONFIG_HOME")
    base = Path(root).expanduser() if root else Path.home() / ".config"
    return base / "autotldr" / "config.toml"


def project_config_path(directory: Path | None = None) -> Path:
    """Return the project config in the invocation directory.

    Alpha deliberately does not walk arbitrary parents.  The file that affects a run is
    visible in the working directory, and its exact path enters the resolved manifest.
    """

    return (directory or Path.cwd()) / ".autotldr.toml"


def load_product_config(
    *,
    use_config: bool = True,
    directory: Path | None = None,
) -> ProductConfig:
    """Load user then project TOML under a closed, deterministic schema."""

    if not use_config:
        return ProductConfig()
    merged: dict[str, Any] = {}
    sources: list[str] = []
    for path in (user_config_path(), project_config_path(directory)):
        if not path.exists():
            continue
        data = _read_config(path)
        _merge_config(merged, data)
        sources.append(str(path.resolve()))
    return _config_from_mapping(merged, sources=tuple(sources))


def write_user_model_config(
    profile: ModelProfile,
    *,
    detail: str = "standard",
    force: bool = False,
) -> Path:
    """Write the small user configuration produced by ``autotldr setup``."""

    if detail not in DETAIL_PROFILES:
        raise ProductConfigError(
            f"detail must be one of {', '.join(DETAIL_NAMES)}"
        )
    path = user_config_path()
    import json

    if path.exists() and not force:
        raise ProductConfigError(f"configuration already exists at {path}; use --force")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        f"version = {CONFIG_VERSION}\n\n"
        "[defaults]\n"
        f'detail = "{detail}"\n'
        "allow_evidence_fallback = false\n\n"
        "[model]\n"
        f'base_url = {json.dumps(profile.base_url)}\n'
        f'name = {json.dumps(profile.model)}\n'
        f"timeout_seconds = {float(profile.timeout_seconds):g}\n"
        + (
            f'api_key_env = {json.dumps(profile.api_key_env)}\n'
            if profile.api_key_env is not None
            else ""
        )
    )
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return path


def list_served_models(
    base_url: str = DEFAULT_BASE_URL,
    *,
    api_key: str | None = None,
    timeout_seconds: float = 10.0,
) -> tuple[str, ...]:
    """Return the model IDs the server's ``/models`` catalog advertises."""

    import json

    from .transport import TransportError, TransportTimeout, models_url

    try:
        url = models_url(base_url)
    except ValueError as exc:
        raise ProductConfigError(f"model {exc}") from exc
    try:
        payload = _transport_request(
            "GET",
            url,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            max_response_bytes=4 * 1024 * 1024,
        )
    except TransportTimeout as exc:
        raise ModelUnavailable(
            f"no response from {url} within {timeout_seconds:g}s; is a server running "
            "there? Pass --base-url for a different server"
        ) from exc
    except TransportError as exc:
        raise ModelUnavailable(f"model catalog unavailable at {url}: {exc}") from exc
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise ModelUnavailable(f"model catalog at {url} is not JSON") from exc
    rows = document.get("data") if type(document) is dict else None
    if type(rows) is not list:
        raise ModelUnavailable(f"model catalog at {url} has no data array")
    models = {
        row["id"]
        for row in rows
        if type(row) is dict and type(row.get("id")) is str and row["id"].strip()
    }
    return tuple(sorted(models))


def require_model_available(profile: ModelProfile) -> tuple[str, ...]:
    """Fail before source acquisition unless the server lists the configured model.

    Listing is the portable readiness signal. Routers and gateways load models on
    demand, so a listed model may still take time on its first request.
    """

    models = list_served_models(
        profile.base_url,
        api_key=profile.api_key(),
        timeout_seconds=min(float(profile.timeout_seconds), 10.0),
    )
    if profile.model not in models:
        raise ModelUnavailable(
            f"model {profile.model!r} is not listed at {profile.base_url}; "
            f"{_model_choices(models)}"
        )
    return models


def require_configured_model(config: ProductConfig) -> ModelProfile:
    if config.model is None:
        raise ModelUnavailable(
            "no model server is configured; run `autotldr setup` and then retry"
        )
    return config.model


def probe_model_profile(profile: ModelProfile) -> dict[str, object]:
    """Run one bounded, source-free grounding probe against the configured model.

    Catalog presence alone does not prove that a server accepts AutoTLDR's request or
    returns a usable response.  The probe sends synthetic public text only.
    """

    require_model_available(profile)
    from .api import assemble_collection
    from .router import extract_stdin
    from .synthesis import SynthesisConfig, synthesize

    leaf = extract_stdin(
        b"# AutoTLDR doctor\n\nThe diagnostic fixture states that the probe succeeded.\n",
        kind="markdown",
    )
    collection = assemble_collection((leaf,), subject="<autotldr-doctor>")
    result = synthesize(
        collection,
        SynthesisConfig(
            model=profile.model,
            endpoint=profile.base_url,
            api_key=profile.api_key(),
            evidence_budget_bytes=4_096,
            timeout_seconds=float(profile.timeout_seconds),
            max_output_tokens=DETAIL_PROFILES["brief"].max_output_tokens,
            max_claims=1,
            reasoning_effort=DETAIL_PROFILES["brief"].reasoning_effort,
            product_detail="brief",
            include_findings=False,
            fallback_on_failure=False,
        ),
    )
    return {
        "model": profile.model,
        "base_url": profile.base_url,
        "claims": len(result.extraction.summary_claims),
        "outcome": "accepted",
    }


def _read_config(path: Path) -> dict[str, Any]:
    import tomllib

    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ProductConfigError(f"cannot read configuration {path}: {exc}") from exc
    if len(payload) > 256 * 1024:
        raise ProductConfigError(f"configuration {path} exceeds 256 KiB")
    try:
        data = tomllib.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ProductConfigError(f"invalid configuration {path}: {exc}") from exc
    if type(data) is not dict:
        raise ProductConfigError(f"configuration {path} must be a TOML table")
    return data


def _merge_config(target: dict[str, Any], update: Mapping[str, Any]) -> None:
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge_config(target[key], value)
        else:
            target[key] = value


def _config_from_mapping(
    data: Mapping[str, Any], *, sources: tuple[str, ...]
) -> ProductConfig:
    allowed = {"version", "defaults", "model", "extensions"}
    if extras := sorted(set(data) - allowed):
        raise ProductConfigError(f"unknown configuration key: {extras[0]}")
    version = data.get("version", CONFIG_VERSION)
    if type(version) is not int or version != CONFIG_VERSION:
        raise ProductConfigError(f"configuration version must be {CONFIG_VERSION}")

    defaults = data.get("defaults", {})
    if type(defaults) is not dict:
        raise ProductConfigError("defaults must be a TOML table")
    if extras := sorted(set(defaults) - {"detail", "allow_evidence_fallback"}):
        raise ProductConfigError(f"unknown defaults key: {extras[0]}")
    detail = defaults.get("detail", "standard")
    fallback = defaults.get("allow_evidence_fallback", False)

    model_data = data.get("model")
    model = None
    if model_data is not None:
        if type(model_data) is not dict:
            raise ProductConfigError("model must be a TOML table")
        if "endpoint" in model_data or "runtime" in model_data:
            raise ProductConfigError(
                "model.endpoint and model.runtime were replaced by model.base_url; "
                "rerun `autotldr setup --force`"
            )
        if extras := sorted(
            set(model_data) - {"base_url", "name", "timeout_seconds", "api_key_env"}
        ):
            raise ProductConfigError(f"unknown model key: {extras[0]}")
        if "base_url" not in model_data or "name" not in model_data:
            raise ProductConfigError("model.base_url and model.name are required")
        model = ModelProfile(
            base_url=model_data["base_url"],
            model=model_data["name"],
            timeout_seconds=model_data.get("timeout_seconds", 120.0),
            api_key_env=model_data.get("api_key_env"),
        )

    extensions_data = data.get("extensions", {})
    if type(extensions_data) is not dict:
        raise ProductConfigError("extensions must be a TOML table")
    if extras := sorted(set(extensions_data) - {"imports"}):
        raise ProductConfigError(f"unknown extensions key: {extras[0]}")
    imports = extensions_data.get("imports", [])
    if type(imports) is not list:
        raise ProductConfigError("extensions.imports must be an array")
    return ProductConfig(
        detail=detail,
        allow_evidence_fallback=fallback,
        model=model,
        extensions=tuple(imports),
        sources=sources,
    )


def _transport_request(method: str, url: str, **kwargs: Any) -> bytes:
    from .transport import request

    return request(method, url, **kwargs)


def _model_choices(models: tuple[str, ...]) -> str:
    if not models:
        return "the server lists no models"
    shown = ", ".join(models[:20])
    more = f" (and {len(models) - 20} more)" if len(models) > 20 else ""
    return f"available: {shown}{more}"


__all__ = [
    "CONFIG_VERSION",
    "DEFAULT_BASE_URL",
    "DETAIL_NAMES",
    "DETAIL_PROFILES",
    "DetailProfile",
    "ModelProfile",
    "ModelUnavailable",
    "ProductConfig",
    "ProductConfigError",
    "list_served_models",
    "load_product_config",
    "project_config_path",
    "probe_model_profile",
    "require_configured_model",
    "require_model_available",
    "user_config_path",
    "write_user_model_config",
]
