"""First-user product contract: config, discovery, detail, and default prose."""

from __future__ import annotations


import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from autotldr.cli import main
from autotldr.product import (
    DETAIL_PROFILES,
    ModelProfile,
    ModelUnavailable,
    ProductConfigError,
    list_served_models,
    load_product_config,
    probe_model_profile,
    require_model_available,
    write_user_model_config,
)
from autotldr.unit import Extraction, GroundedStatement


def test_detail_profiles_expand_one_simple_user_choice():
    assert tuple(DETAIL_PROFILES) == ("brief", "standard", "deep")
    assert [item.max_claims for item in DETAIL_PROFILES.values()] == [2, 4, 6]
    assert [item.evidence_budget_bytes for item in DETAIL_PROFILES.values()] == [
        8_000,
        24_000,
        48_000,
    ]
    assert [item.max_output_tokens for item in DETAIL_PROFILES.values()] == [
        512,
        1_024,
        1_800,
    ]


def test_user_then_project_config_is_strict_and_project_wins(tmp_path, monkeypatch):
    user = tmp_path / "user" / "config.toml"
    monkeypatch.setenv("AUTOTLDR_CONFIG", str(user))
    write_user_model_config(
        ModelProfile("http://127.0.0.1:1234", "served-local"),
        detail="brief",
    )
    project = tmp_path / "project"
    project.mkdir()
    (project / ".autotldr.toml").write_text(
        'version = 1\n[defaults]\ndetail = "deep"\n', encoding="utf-8"
    )

    config = load_product_config(directory=project)

    assert config.detail == "deep"
    assert config.model == ModelProfile("http://127.0.0.1:1234", "served-local")
    assert config.sources == (str(user.resolve()), str((project / ".autotldr.toml").resolve()))
    assert user.stat().st_mode & 0o777 == 0o600


def test_unknown_config_key_fails_closed(tmp_path, monkeypatch):
    config = tmp_path / "config.toml"
    config.write_text("version = 1\ninvented = true\n", encoding="utf-8")
    monkeypatch.setenv("AUTOTLDR_CONFIG", str(config))
    with pytest.raises(ProductConfigError, match="unknown configuration key"):
        load_product_config(directory=tmp_path)


@pytest.mark.parametrize(
    "base_url,normalized",
    (
        ("http://127.0.0.1:1234", "http://127.0.0.1:1234/v1"),
        ("http://127.0.0.1:1234/v1/", "http://127.0.0.1:1234/v1"),
        ("http://mini.tail.ts.net:8080/v1", "http://mini.tail.ts.net:8080/v1"),
        ("https://Gateway.example:4000", "https://gateway.example:4000/v1"),
        ("http://192.168.86.20/api/v1", "http://192.168.86.20/api/v1"),
        ("http://127.0.0.1:1234/v1/chat/completions", "http://127.0.0.1:1234/v1"),
    ),
)
def test_model_profile_accepts_any_openai_compatible_base_url(base_url, normalized):
    assert ModelProfile(base_url, "served").base_url == normalized


@pytest.mark.parametrize(
    "base_url,error",
    (
        ("ftp://127.0.0.1/v1", "scheme"),
        ("http://user:secret@gateway/v1", "credentials"),
        ("http://gateway/v1?key=secret", "query"),
        ("http:///v1", "host"),
        (" http://gateway/v1", "unpadded"),
    ),
)
def test_model_profile_rejects_unusable_or_secret_bearing_urls(base_url, error):
    with pytest.raises(ProductConfigError, match=error):
        ModelProfile(base_url, "served")


def test_api_key_is_resolved_from_the_environment_and_never_persisted(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("AUTOTLDR_CONFIG", str(tmp_path / "config.toml"))
    profile = ModelProfile("http://gateway:4000", "mini/model", api_key_env="HLAB_KEY")
    monkeypatch.delenv("HLAB_KEY", raising=False)
    with pytest.raises(ModelUnavailable, match="HLAB_KEY is not set"):
        profile.api_key()
    monkeypatch.setenv("HLAB_KEY", "sk-secret-value")
    assert profile.api_key() == "sk-secret-value"

    path = write_user_model_config(profile)
    assert "sk-secret-value" not in path.read_text()
    assert load_product_config(directory=tmp_path).model == profile
    with pytest.raises(ProductConfigError, match="environment variable name"):
        ModelProfile("http://gateway:4000", "m", api_key_env="NOT A NAME")


def test_old_runtime_config_gets_an_actionable_error(tmp_path, monkeypatch):
    config = tmp_path / "config.toml"
    config.write_text(
        'version = 1\n[model]\nendpoint = "http://127.0.0.1:1234"\n'
        'name = "m"\nruntime = "lm-studio"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("AUTOTLDR_CONFIG", str(config))
    with pytest.raises(ProductConfigError, match="setup --force"):
        load_product_config(directory=tmp_path)


def test_grounded_probe_uses_configured_server_and_a_real_brief_completion_budget(
    monkeypatch,
):
    import autotldr.product
    import autotldr.synthesis

    profile = ModelProfile("http://127.0.0.1:1234", "served-local")
    observed = {}

    monkeypatch.setattr(
        autotldr.product,
        "require_model_available",
        lambda candidate: (candidate.model,),
    )

    def fake_synthesize(extraction, config):
        observed["config"] = config
        unit = extraction.units[0]
        completed = Extraction(
            source=extraction.source,
            kind=extraction.kind,
            units=list(extraction.units),
            relations=list(extraction.relations),
            gaps=list(extraction.gaps),
            meta=dict(extraction.meta),
            summary_claims=[
                GroundedStatement("The probe succeeded.", (unit.origin,), (unit.id,))
            ],
        )
        return SimpleNamespace(extraction=completed)

    monkeypatch.setattr(autotldr.synthesis, "synthesize", fake_synthesize)

    report = probe_model_profile(profile)

    assert report["outcome"] == "accepted"
    assert observed["config"].max_output_tokens == DETAIL_PROFILES["brief"].max_output_tokens
    assert observed["config"].timeout_seconds == 120.0
    assert observed["config"].endpoint == "http://127.0.0.1:1234/v1"
    assert observed["config"].api_key is None
    assert observed["config"].reasoning_effort == "none"
    assert observed["config"].product_detail == "brief"
    assert observed["config"].include_findings is False


def test_formats_json_is_derived_from_live_router(capsys):
    assert main(["formats", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "autotldr-runtime-capabilities-v1"
    assert payload["detail_levels"] == ["brief", "standard", "deep"]
    assert any(item["kind"] == "xlsx" and item["tier"] == 3 for item in payload["inputs"])
    assert any(item["suffix"] == ".pptx" and item["tier"] == 4 for item in payload["declined"])
    assert not {".zip", ".tar", ".tgz"} & {
        item["suffix"] for item in payload["declined"]
    }
    collections = {item["name"]: item for item in payload["collection_capabilities"]}
    assert collections["zip"] == {
        "name": "zip",
        "status": "available",
        "suffixes": [".zip"],
        "schemes": [],
    }
    assert collections["tar"] == {
        "name": "tar",
        "status": "available",
        "suffixes": [".tar", ".tar.gz", ".tgz"],
        "schemes": [],
    }
    leaf_declines = {
        item["suffix"]: item for item in payload["single_file_declines"]
    }
    assert leaf_declines[".zip"]["status"] == "declined"
    assert leaf_declines[".zip"]["scope"] == "single-file-extraction"
    assert leaf_declines[".zip"]["available_via"] == "collection-acquisition"
    assert "available_via" not in leaf_declines[".gz"]
    assert {item["name"] for item in payload["output_capabilities"]} == set(
        payload["outputs"]
    )


def test_formats_human_output_names_available_archive_collections(capsys):
    assert main(["formats"]) == 0

    rendered = capsys.readouterr().out
    assert "Tier 2 collections" in rendered
    assert "zip              available          .zip" in rendered
    assert "tar              available          .tar, .tar.gz, .tgz" in rendered
    assert "doc-site         available          http://, https://" in rendered


def test_default_cli_uses_configured_server_prose_and_detail(
    tmp_path, monkeypatch, capsys
):
    source = tmp_path / "notes.md"
    source.write_text("# Cooling policy\n\nKeep pressure below 240 kPa.\n", encoding="utf-8")
    config_path = tmp_path / "config.toml"
    monkeypatch.setenv("AUTOTLDR_CONFIG", str(config_path))
    monkeypatch.delenv("AUTOTLDR_MODEL", raising=False)
    write_user_model_config(
        ModelProfile("http://127.0.0.1:1234", "served-local"),
        force=True,
    )
    observed = {}

    def fake_synthesize(extraction, config):
        observed["kind"] = extraction.kind
        observed["config"] = config
        unit = extraction.units[0]
        statement = GroundedStatement(
            "The source documents a cooling policy.",
            (unit.origin,),
            (unit.id,),
        )
        result = Extraction(
            source=extraction.source,
            kind=extraction.kind,
            units=list(extraction.units),
            relations=list(extraction.relations),
            gaps=list(extraction.gaps),
            meta=dict(extraction.meta),
            summary_claims=[statement],
        )
        return SimpleNamespace(extraction=result, used_fallback=False)

    import autotldr.synthesis
    import autotldr.product

    monkeypatch.setattr(autotldr.synthesis, "synthesize", fake_synthesize)
    monkeypatch.setattr(
        autotldr.product,
        "require_model_available",
        lambda profile: (profile.model,),
    )

    assert main([str(source), "--detail", "deep", "--out", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert observed["kind"] == "collection"
    assert observed["config"].model == "served-local"
    assert observed["config"].max_claims == 6
    assert observed["config"].evidence_budget_bytes == 48_000
    assert observed["config"].max_output_tokens == 1_800
    assert observed["config"].timeout_seconds == 120.0
    assert observed["config"].endpoint == "http://127.0.0.1:1234/v1"
    assert observed["config"].reasoning_effort == "none"
    assert observed["config"].product_detail == "deep"
    assert observed["config"].include_findings is False
    assert observed["config"].fallback_on_failure is False
    assert payload["summary_claims"][0]["content"] == "The source documents a cooling policy."
    assert payload["kind"] == "markdown"
    assert payload["manifest"]["product"]["mode"] == "prose"
    assert payload["manifest"]["product"]["detail"]["name"] == "deep"


def test_cli_fallback_is_opt_in_and_labelled_in_the_result(
    tmp_path, monkeypatch, capsys
):
    source = tmp_path / "notes.md"
    source.write_text("# Notes\n\nGrounded evidence.\n", encoding="utf-8")
    config_path = tmp_path / "config.toml"
    monkeypatch.setenv("AUTOTLDR_CONFIG", str(config_path))
    monkeypatch.delenv("AUTOTLDR_MODEL", raising=False)
    profile = ModelProfile("http://127.0.0.1:1234", "served-local")
    write_user_model_config(profile, force=True)
    observed = {}

    def fake_synthesize(extraction, config):
        observed["config"] = config
        return SimpleNamespace(extraction=extraction, used_fallback=True)

    import autotldr.product
    import autotldr.synthesis

    monkeypatch.setattr(autotldr.synthesis, "synthesize", fake_synthesize)
    monkeypatch.setattr(
        autotldr.product,
        "require_model_available",
        lambda candidate: (candidate.model,),
    )

    assert (
        main(
            [
                str(source),
                "--allow-evidence-fallback",
                "--out",
                "json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)

    assert observed["config"].fallback_on_failure is True
    assert payload["manifest"]["product"]["mode"] == "evidence-fallback"
    assert payload["manifest"]["product"]["resolved_config"][
        "allow_evidence_fallback"
    ] is True
    assert payload["summary_claims"] == []


def test_explicit_model_off_is_labelled_evidence_mode(tmp_path, monkeypatch, capsys):
    source = tmp_path / "notes.md"
    source.write_text("# Notes\n\nEvidence only.\n", encoding="utf-8")
    monkeypatch.setenv("AUTOTLDR_CONFIG", str(tmp_path / "missing.toml"))
    monkeypatch.delenv("AUTOTLDR_MODEL", raising=False)

    assert main([str(source), "--model", "off", "--out", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["manifest"]["product"]["mode"] == "evidence"
    assert payload["summary_claims"] == []


def test_environment_model_off_is_labelled_evidence_mode(
    tmp_path, monkeypatch, capsys
):
    source = tmp_path / "notes.md"
    source.write_text("# Notes\n\nEvidence only.\n", encoding="utf-8")
    monkeypatch.setenv("AUTOTLDR_CONFIG", str(tmp_path / "missing.toml"))
    monkeypatch.setenv("AUTOTLDR_MODEL", "off")

    def unexpected_model_check(*args, **kwargs):
        raise AssertionError("model-off must not contact the model server")

    monkeypatch.setattr(
        "autotldr.product.require_model_available", unexpected_model_check
    )

    assert main([str(source), "--out", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["manifest"]["product"]["mode"] == "evidence"
    assert payload["summary_claims"] == []


def test_missing_model_fails_before_source_acquisition(tmp_path, monkeypatch, capsys):
    missing_source = tmp_path / "does-not-exist.md"
    monkeypatch.setenv("AUTOTLDR_CONFIG", str(tmp_path / "missing.toml"))
    monkeypatch.delenv("AUTOTLDR_MODEL", raising=False)

    assert main([str(missing_source)]) == 1

    error = capsys.readouterr().err
    assert "no model server is configured" in error
    assert "no such file" not in error


def test_source_named_version_is_not_stolen_after_option_separator(
    tmp_path, monkeypatch, capsys
):
    source = tmp_path / "--version"
    source.write_text("Meaning.\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AUTOTLDR_MODEL", raising=False)

    assert main(["--out", "json", "--model", "off", "--", "--version"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["subject"] == "--version"


def test_all_checked_in_product_surfaces_use_package_version():
    from autotldr import __version__
    from autotldr import mcp

    assert mcp._SERVER_INFO["version"] == __version__
    assert not Path(".well-known/agent-card.json").exists()


def test_human_detail_reports_presentation_without_hiding_machine_evidence(
    tmp_path, monkeypatch, capsys
):
    source = tmp_path / "many.md"
    source.write_text(
        "\n\n".join(f"## Topic {index}\n\nEvidence {index}." for index in range(12)),
        encoding="utf-8",
    )
    monkeypatch.setenv("AUTOTLDR_CONFIG", str(tmp_path / "missing.toml"))
    monkeypatch.delenv("AUTOTLDR_MODEL", raising=False)

    assert main([str(source), "--model", "off", "--detail", "brief", "--out", "md"]) == 0
    brief = capsys.readouterr().out
    assert "Presenting 6 of 24 budget-selected units" in brief

    assert main([str(source), "--model", "off", "--detail", "deep", "--out", "md"]) == 0
    deep = capsys.readouterr().out
    assert "Presenting 24 of 24 budget-selected units" in deep

    assert main([str(source), "--model", "off", "--detail", "brief", "--out", "json"]) == 0
    machine = json.loads(capsys.readouterr().out)
    assert len(machine["units"]) == 24


def test_human_sources_name_extracted_and_declined_collection_members(
    tmp_path, monkeypatch, capsys
):
    root = tmp_path / "handoff"
    root.mkdir()
    (root / "notes.md").write_text("# Notes\n\nSupported.\n", encoding="utf-8")
    (root / "unknown.zzz").write_bytes(b"\x00\x01")
    monkeypatch.setenv("AUTOTLDR_CONFIG", str(tmp_path / "missing.toml"))
    monkeypatch.delenv("AUTOTLDR_MODEL", raising=False)

    assert main([str(root), "--model", "off", "--out", "md"]) == 0
    rendered = capsys.readouterr().out

    assert "## Sources" in rendered
    assert "notes.md" in rendered and "extracted" in rendered
    assert "unknown.zzz" in rendered and "declined" in rendered
    assert "## Gaps" in rendered


def test_bundled_agent_skill_can_be_installed_without_a_source_checkout(
    tmp_path, capsys
):
    destination = tmp_path / "skills"

    assert main(["integrations", "skill", "--install", str(destination)]) == 0

    installed = destination / "autotldr"
    assert (installed / "SKILL.md").is_file()
    assert (installed / "agents" / "openai.yaml").is_file()
    assert "Installed AutoTLDR Agent Skill" in capsys.readouterr().out
    assert main(["integrations", "skill", "--install", str(destination)]) == 1
    assert "already exists" in capsys.readouterr().err

    with pytest.raises(SystemExit) as conflicting_actions:
        main(
            [
                "integrations",
                "skill",
                "--install",
                str(tmp_path / "other-skills"),
                "--print",
            ]
        )
    assert conflicting_actions.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err


def test_watch_uses_configured_prose_for_files_and_rollup(
    tmp_path, monkeypatch
):
    from autotldr.watch import ROLLUP_NAME, artifact_path, run_once

    root = tmp_path / "inbox"
    root.mkdir()
    source = root / "notes.md"
    source.write_text("# Policy\n\nKeep pressure below 240 kPa.\n", encoding="utf-8")
    config_path = tmp_path / "config.toml"
    monkeypatch.setenv("AUTOTLDR_CONFIG", str(config_path))
    monkeypatch.delenv("AUTOTLDR_MODEL", raising=False)
    write_user_model_config(
        ModelProfile("http://127.0.0.1:1234", "served-local"),
        force=True,
    )
    observed = []

    def fake_synthesize(extraction, config):
        observed.append((extraction.kind, config.max_claims))
        unit = extraction.units[0]
        completed = Extraction(
            source=extraction.source,
            kind=extraction.kind,
            units=list(extraction.units),
            relations=list(extraction.relations),
            gaps=list(extraction.gaps),
            meta=dict(extraction.meta),
            summary_claims=[
                GroundedStatement(
                    "The source defines a pressure policy.",
                    (unit.origin,),
                    (unit.id,),
                )
            ],
        )
        return SimpleNamespace(extraction=completed, used_fallback=False)

    import autotldr.synthesis
    import autotldr.product

    monkeypatch.setattr(autotldr.synthesis, "synthesize", fake_synthesize)
    monkeypatch.setattr(
        autotldr.product,
        "require_model_available",
        lambda profile: (profile.model,),
    )

    result = run_once(root, detail="brief", budget=250_000)

    assert result.succeeded == 1
    assert observed == [("collection", 2), ("collection", 2)]
    assert "Cited model prose" in artifact_path(root, "notes.md").read_text()
    assert "Cited model prose" in (root / ".autotldr" / ROLLUP_NAME).read_text()


def test_doctor_requires_catalog_identity_and_grounded_completion_probe(
    tmp_path, monkeypatch, capsys
):
    config_path = tmp_path / "config.toml"
    monkeypatch.setenv("AUTOTLDR_CONFIG", str(config_path))
    profile = ModelProfile("http://127.0.0.1:1234", "served-local")
    write_user_model_config(profile, force=True)
    import autotldr.product

    monkeypatch.setattr(
        autotldr.product,
        "require_model_available",
        lambda candidate: (candidate.model,),
    )
    observed = []

    def successful_probe(candidate):
        observed.append(candidate)
        return {
            "model": candidate.model,
            "base_url": candidate.base_url,
            "claims": 1,
            "outcome": "accepted",
        }

    monkeypatch.setattr(autotldr.product, "probe_model_profile", successful_probe)

    assert main(["doctor", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ready"] is True
    assert observed == [profile]
    assert next(
        item for item in report["checks"] if item["name"] == "grounded-prose"
    )["status"] == "ok"

    monkeypatch.setattr(
        autotldr.product,
        "probe_model_profile",
        lambda _profile: (_ for _ in ()).throw(ValueError("bad response")),
    )
    assert main(["doctor", "--json"]) == 1
    failed = json.loads(capsys.readouterr().out)
    assert failed["ready"] is False
    assert next(
        item for item in failed["checks"] if item["name"] == "grounded-prose"
    )["status"] == "error"


def test_root_help_and_config_introspection_are_discoverable(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("AUTOTLDR_CONFIG", str(tmp_path / "missing.toml"))

    with pytest.raises(SystemExit) as help_exit:
        main(["--help"])
    assert help_exit.value.code == 0
    help_text = capsys.readouterr().out
    for command in ("setup", "doctor", "config", "formats", "watch", "integrations", "mcp"):
        assert command in help_text

    assert main(["config", "show", "--json"]) == 0
    resolved = json.loads(capsys.readouterr().out)
    assert resolved["detail"]["name"] == "standard"
    assert resolved["model"] is None

    assert main(["config", "paths"]) == 0
    paths = capsys.readouterr().out
    assert str(tmp_path / "missing.toml") in paths
    assert ".autotldr.toml" in paths


def test_setup_checks_the_catalog_and_persists_server_and_key_name(
    tmp_path, monkeypatch, capsys
):
    import autotldr.product

    config_path = tmp_path / "config.toml"
    monkeypatch.setenv("AUTOTLDR_CONFIG", str(config_path))
    monkeypatch.setenv("HLAB_KEY", "sk-test")
    observed = []

    def catalog(base_url, *, api_key=None, timeout_seconds=10.0):
        observed.append((base_url, api_key))
        return ("mini/qwen", "mini/gemma")

    monkeypatch.setattr(autotldr.product, "list_served_models", catalog)

    with pytest.raises(SystemExit) as help_exit:
        main(["setup", "--help"])
    assert help_exit.value.code == 0
    setup_help = capsys.readouterr().out
    assert "--base-url" in setup_help and "--api-key-env" in setup_help

    assert main(["setup", "--base-url", "http://gateway:4000", "--api-key-env", "HLAB_KEY"]) == 1
    error = capsys.readouterr().err
    assert "choose a model with --model ID" in error
    assert "mini/gemma" in error and "mini/qwen" in error
    assert not config_path.exists()

    assert main(["setup", "--base-url", "http://gateway:4000", "--model", "mini/absent",
                 "--api-key-env", "HLAB_KEY"]) == 1
    assert "not listed" in capsys.readouterr().err
    assert not config_path.exists()

    assert main([
        "setup", "--base-url", "http://gateway:4000", "--model", "mini/qwen",
        "--api-key-env", "HLAB_KEY", "--detail", "brief",
    ]) == 0
    assert observed[-1] == ("http://gateway:4000/v1", "sk-test")
    config = load_product_config(directory=tmp_path)
    assert config.detail == "brief"
    assert config.model == ModelProfile(
        "http://gateway:4000/v1", "mini/qwen", api_key_env="HLAB_KEY"
    )
    assert "sk-test" not in config_path.read_text()
    assert "Run `autotldr doctor`" in capsys.readouterr().out


def test_setup_selects_the_only_listed_model_on_a_local_server(
    tmp_path, monkeypatch, capsys
):
    import autotldr.product

    config_path = tmp_path / "config.toml"
    monkeypatch.setenv("AUTOTLDR_CONFIG", str(config_path))
    monkeypatch.setattr(
        autotldr.product, "list_served_models", lambda *_a, **_k: ("only-model",)
    )

    assert main(["setup"]) == 0
    assert load_product_config(directory=tmp_path).model == ModelProfile(
        "http://127.0.0.1:1234/v1", "only-model"
    )


def test_cli_model_id_overrides_only_the_configured_model_name(
    tmp_path, monkeypatch, capsys
):
    source = tmp_path / "notes.md"
    source.write_text("# Notes\n\nEvidence.\n", encoding="utf-8")
    monkeypatch.setenv("AUTOTLDR_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.delenv("AUTOTLDR_MODEL", raising=False)
    write_user_model_config(ModelProfile("http://gateway:4000", "mini/qwen"))
    observed = {}

    import autotldr.product
    import autotldr.synthesis

    def fake_synthesize(extraction, config):
        observed["config"] = config
        return SimpleNamespace(extraction=extraction, used_fallback=True)

    monkeypatch.setattr(autotldr.synthesis, "synthesize", fake_synthesize)
    monkeypatch.setattr(
        autotldr.product, "require_model_available", lambda profile: (profile.model,)
    )

    assert main([str(source), "--model", "dynamo/gemma", "--allow-evidence-fallback",
                 "--out", "json"]) == 0
    assert observed["config"].model == "dynamo/gemma"
    assert observed["config"].endpoint == "http://gateway:4000/v1"

    monkeypatch.setenv("AUTOTLDR_CONFIG", str(tmp_path / "missing.toml"))
    with pytest.raises(SystemExit) as unconfigured:
        main([str(source), "--model", "dynamo/gemma"])
    assert unconfigured.value.code == 2


class _OpenAIServer:
    """A real loopback HTTP server that speaks the OpenAI subset AutoTLDR uses."""

    def __init__(self, *, models=("served",), key=None, redirect=False, reply=None):
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        self.requests = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _auth_ok(self):
                return key is None or self.headers.get("Authorization") == f"Bearer {key}"

            def _send(self, status, payload, headers=()):
                body = json.dumps(payload).encode()
                self.send_response(status)
                for name, value in headers:
                    self.send_header(name, value)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                outer.requests.append(("GET", self.path, self.headers.get("Authorization"), None))
                if redirect:
                    self._send(302, {}, [("Location", "http://127.0.0.1:9/v1/models")])
                elif not self._auth_ok():
                    self._send(401, {"error": {"message": "Invalid API key"}})
                else:
                    self._send(200, {"object": "list", "data": [
                        {"id": model, "object": "model", "owned_by": "anyone",
                         "status": {"value": "unloaded"}} for model in models]})

            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                outer.requests.append(("POST", self.path, self.headers.get("Authorization"), body))
                if not self._auth_ok():
                    self._send(401, {"error": {"message": "Invalid API key"}})
                    return
                self._send(200, reply(json.loads(body)))

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base_url = f"http://127.0.0.1:{self.server.server_port}/v1"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_exc):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


def test_catalog_uses_bearer_auth_and_ignores_router_specific_fields(monkeypatch):
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    with _OpenAIServer(models=("b", "a"), key="sk-lab") as server:
        assert list_served_models(server.base_url, api_key="sk-lab") == ("a", "b")
        assert server.requests[-1][:3] == ("GET", "/v1/models", "Bearer sk-lab")
        with pytest.raises(ModelUnavailable, match="HTTP 401.*Invalid API key"):
            list_served_models(server.base_url, api_key="wrong")
        monkeypatch.setenv("LAB_KEY", "sk-lab")
        with pytest.raises(ModelUnavailable, match="not listed.*available: a, b"):
            require_model_available(ModelProfile(server.base_url, "c", api_key_env="LAB_KEY"))


def test_catalog_never_follows_redirects(monkeypatch):
    with _OpenAIServer(redirect=True) as server:
        with pytest.raises(ModelUnavailable, match="HTTP 302"):
            list_served_models(server.base_url)
        assert [request[1] for request in server.requests] == ["/v1/models"]


def test_prose_round_trips_through_a_real_openai_compatible_server(
    tmp_path, monkeypatch, capsys
):
    """Gateway-shaped extras are ignored; reasoning is hashed, never cited."""

    source = tmp_path / "notes.md"
    source.write_text("# Cooling\n\nKeep pressure below 240 kPa.\n", encoding="utf-8")
    monkeypatch.setenv("AUTOTLDR_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.setenv("LAB_KEY", "sk-lab")
    monkeypatch.delenv("AUTOTLDR_MODEL", raising=False)

    def reply(request):
        pack = json.loads(request["messages"][1]["content"].split("\n", 1)[1])
        unit = next(
            item for item in pack["evidence"]["units"] if "240 kPa" in item["content"]
        )
        claims = {"claims": [{"content": "Pressure must stay below 240 kPa.",
                              "evidence_unit_ids": [unit["id"]]}]}
        return {
            "id": "chatcmpl-gateway", "object": "chat.completion", "created": 1,
            "model": request["model"], "system_fingerprint": "b1-test",
            "choices": [{"index": 0, "finish_reason": "stop", "provider_specific_fields": {},
                         "message": {"role": "assistant", "content": json.dumps(claims),
                                     "reasoning_content": "PRIVATE THOUGHTS",
                                     "provider_specific_fields": {"refusal": None}}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15,
                      "prompt_tokens_details": {"cached_tokens": 0}},
            "timings": {"prompt_n": 10, "predicted_ms": 1.5},
        }

    with _OpenAIServer(models=("mini/qwen",), key="sk-lab", reply=reply) as server:
        write_user_model_config(
            ModelProfile(server.base_url, "mini/qwen", api_key_env="LAB_KEY")
        )
        assert main([str(source), "--detail", "brief", "--out", "json"]) == 0
        posts = [request for request in server.requests if request[0] == "POST"]

    payload = json.loads(capsys.readouterr().out)
    assert [claim["content"] for claim in payload["summary_claims"]] == [
        "Pressure must stay below 240 kPa."
    ]
    assert len(posts) == 1
    assert posts[0][1:3] == ("/v1/chat/completions", "Bearer sk-lab")
    assert json.loads(posts[0][3])["reasoning_effort"] == "none"
    run = payload["manifest"]["models"][-1]
    assert run["schema"] == "autotldr-model-run-v3"
    assert run["endpoint"] == f"{server.base_url}/chat/completions"
    assert run["transport"] == {"implementation": "http-client-v1", "authorization": "bearer"}
    assert run["response_facts"]["reasoning"]["bytes"] == len("PRIVATE THOUGHTS")
    serialized = json.dumps(payload)
    assert "PRIVATE THOUGHTS" not in serialized
    assert "sk-lab" not in serialized
