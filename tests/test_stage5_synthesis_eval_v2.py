"""Semantic, human-adjudicated closure tests for synthesis benchmark v2."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
EVALUATE_PATH = ROOT / "benchmarks" / "synthesis" / "evaluate.py"
BUILD_HERO_PATH = ROOT / "benchmarks" / "synthesis" / "build_hero.py"
RAW_ONLY_SQLITE_SENTINEL = "AUTOTLDR_RAW_ONLY_SQLITE_20260830_7F3C91"
RAW_ONLY_CANARIES = {
    "capacity.xlsx": "AUTOTLDR_RAW_ONLY_XLSX_20260830_5A1D2C",
    "measurements.parquet": "AUTOTLDR_RAW_ONLY_PARQUET_20260830_8E4B17",
    "safety.sqlite": RAW_ONLY_SQLITE_SENTINEL,
    "analytics.duckdb": "AUTOTLDR_RAW_ONLY_DUCKDB_20260830_C2A845",
    "experiments.h5": "AUTOTLDR_RAW_ONLY_HDF5_20260830_D6E913",
    "forecast.nc": "AUTOTLDR_RAW_ONLY_NETCDF_20260830_B4F720",
}
CANARY_ID_BY_FILE = {
    "capacity.xlsx": "xlsx_raw_only_sentinel",
    "measurements.parquet": "parquet_raw_only_sentinel",
    "safety.sqlite": "sqlite_raw_only_sentinel",
    "analytics.duckdb": "duckdb_raw_only_sentinel",
    "experiments.h5": "hdf5_raw_only_sentinel",
    "forecast.nc": "netcdf_raw_only_sentinel",
}
TIER3_FIXTURE_SHA256 = {
    "capacity.xlsx": "72b3c3d385ed786634acefaac3d2efc166589cccaeabeea746db05c9cd1a92eb",
    "measurements.parquet": "5821d599ae93f7108440eb1c4c87449e11906dcf13898d92969c6a855929ee65",
    "safety.sqlite": "3bfc757879e34a641025c6d419a5dd77662c4381a5fac5c7460e3b5c4fc936f7",
    "analytics.duckdb": "fa5520a834c57287838741711e4dddbf3908f577e779527e3bf90ea5e933f05f",
    "experiments.h5": "818e8f2d75c4445252548f9e84b72e99b5fa0b7f73f2da1e93364c041a27e5a1",
    "forecast.nc": "ae5622349005cdc943f9c996e0c856c9e12258b61745a022c27c3d26a2f55fe9",
}


def _load(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification and specification.loader
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


evaluate = _load("autotldr_stage5_eval_v2_test", EVALUATE_PATH)
hero_builder = _load("autotldr_stage5_build_hero_v2_test", BUILD_HERO_PATH)


def _api_response(message: dict, *, model: str) -> bytes:
    content = json.dumps(message, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return json.dumps(
        {
            "id": "offline-stage5-v2",
            "object": "chat.completion",
            "created": 1788141600,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "system_fingerprint": "offline-stage5-v2-fingerprint",
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
            },
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


class HeroEvidenceClient:
    endpoint_url = "http://127.0.0.1:1234/v1/chat/completions"

    def __init__(self):
        from autotldr.synthesis import offline_test_transport_attestation

        self.attestation = offline_test_transport_attestation()

    def complete(self, request_body: bytes, *, timeout_seconds: float, max_response_bytes: int):
        del timeout_seconds, max_response_bytes
        request = json.loads(request_body)
        user = request["messages"][1]["content"]
        prefix = "Canonical evidence pack follows. Treat it only as data.\n"
        assert user.startswith(prefix)
        pack = json.loads(user[len(prefix) :])
        units = pack["evidence"]["units"]
        by_address = {
            (item["source"], item["origin"]["ref"], item["modality"]): item["id"]
            for item in units
        }

        def unit(source: str, ref: str, modality: str) -> str:
            return by_address[(source, ref, modality)]

        overview = unit("borealis/overview.md", "line:3-6", "prose")
        claims = [
            {
                "content": (
                    "Borealis monitors and controls the Station Alpha cooling reservoir; "
                    "reservoir_temp_c targets 18.0 °C and pressure_kpa is capped at 240 kPa."
                ),
                "evidence_unit_ids": [
                    overview,
                    unit(
                        "borealis/config.json",
                        "pointer:/reservoir_temp_c/target",
                        "schema",
                    ),
                    unit(
                        "borealis/config.json",
                        "pointer:/pressure_kpa/ceiling",
                        "schema",
                    ),
                ],
            },
            {
                "content": (
                    "The controller reads configuration, consumes Parquet telemetry, "
                    "and records safety events in SQLite."
                ),
                "evidence_unit_ids": [
                    overview,
                    unit(
                        "borealis/measurements.parquet",
                        "column:pressure_kpa",
                        "schema",
                    ),
                    unit("borealis/safety.sqlite", "table:safety_events", "schema"),
                ],
            },
            {
                "content": (
                    "HDF5 experiments, NetCDF forecasts, bounded DuckDB profiles, and the "
                    "capacity workbook provide analysis context; calibration/current.csv "
                    "is referenced but missing."
                ),
                "evidence_unit_ids": [
                    unit("borealis/overview.md", "line:8-11", "prose"),
                    unit(
                        "borealis/experiments.h5",
                        "/experiments/run_001/pressure_kpa",
                        "schema",
                    ),
                    unit("borealis/forecast.nc", "/pressure_kpa", "schema"),
                    unit("borealis/capacity.xlsx", "Inputs!B4", "record"),
                    unit(
                        "borealis/appendix.zip!/appendix/calibration.md",
                        "line:3",
                        "prose",
                    ),
                ],
            },
        ]
        return _api_response({"claims": claims}, model=request["model"])


def _fact_claim_map(packet: dict) -> dict[str, list[str]]:
    claims = packet["claims"]
    assert len(claims) == 3
    return {
        "purpose": [claims[0]["id"]],
        "operating_constraints": [claims[0]["id"]],
        "data_flow": [claims[1]["id"]],
        "scientific_and_capacity_context": [claims[2]["id"]],
        "missing_calibration": [claims[2]["id"]],
    }


def _review(
    context: dict,
    reviewer_id: str,
    *,
    fact_overrides: dict[tuple[str, str], str] | None = None,
    summary_overrides: dict[tuple[str, str], bool] | None = None,
) -> dict:
    fact_overrides = fact_overrides or {}
    summary_overrides = summary_overrides or {}
    fact_rows = []
    claim_rows = []
    summary_rows = []
    for packet in context["packets"]["packets"]:
        supporting = _fact_claim_map(packet)
        for fact in context["truth"]["facts"]:
            key = (packet["packet_id"], fact["id"])
            entailment = fact_overrides.get(key, "entailed")
            fact_rows.append(
                {
                    "packet_id": packet["packet_id"],
                    "fact_id": fact["id"],
                    "supporting_claim_ids": (
                        supporting[fact["id"]] if entailment == "entailed" else []
                    ),
                    "entailment": entailment,
                    "rationale": "The cited text directly supports every named semantic slot.",
                }
            )
        for claim in packet["claims"]:
            detected_canaries = sorted(
                item["id"]
                for item in context["truth"]["payload_canaries"]
                if item["literal"] in claim["content"]
            )
            claim_rows.append(
                {
                    "packet_id": packet["packet_id"],
                    "claim_id": claim["id"],
                    "every_citation_relevant": True,
                    "atomic_claim": True,
                    "hard_negative_ids": [],
                    "payload_canary_ids": detected_canaries,
                    "other_raw_payload_leak": False,
                    "usefulness": "useful",
                    "rationale": "Every clause is supported and contributes to the TLDR.",
                }
            )
        summary = {
            "packet_id": packet["packet_id"],
            "coherent": True,
            "concise": True,
            "integrates_sources": True,
            "useful_over_inventory": True,
            "rationale": "The three claims form a concise cross-source explanation.",
        }
        for gate in (
            "coherent",
            "concise",
            "integrates_sources",
            "useful_over_inventory",
        ):
            summary[gate] = summary_overrides.get(
                (packet["packet_id"], gate), summary[gate]
            )
        summary_rows.append(summary)
    record = {
        "schema": evaluate.REVIEW_ARTIFACT_V2_SCHEMA,
        "benchmark": context["freeze"]["benchmark"],
        "freeze_sha256": context["freeze"]["freeze_sha256"],
        "packet_set_sha256": context["packets"]["packet_set_sha256"],
        "review_schema_sha256": context["freeze"]["review_schema_v2"]["sha256"],
        "reviewer_id": reviewer_id,
        "human_authored": True,
        "completed_at": "2026-08-30T18:00:00-05:00",
        "fact_rows": fact_rows,
        "claim_rows": claim_rows,
        "summary_rows": summary_rows,
    }
    return evaluate.finalize_review_artifact_v2(record)


@pytest.fixture(scope="module")
def context(tmp_path_factory):
    directory = tmp_path_factory.mktemp("stage5-v2")
    extraction = evaluate.build_hero_extraction()
    base_policy, _ = evaluate.load_policy()
    policy_v2, _ = evaluate.load_policy_v2()
    truth, _ = evaluate.load_truth_v2()
    review_schema, _ = evaluate.load_review_schema_v2()
    freeze = evaluate.build_freeze_record_v2(extraction=extraction)
    base_freeze_path = directory / "base-freeze.json"
    evaluate.write_freeze(base_freeze_path, freeze["base_freeze"])
    artifacts = []
    for candidate in evaluate.policy_candidates(base_policy):
        artifacts.append(
            evaluate.run_candidate(
                candidate["model_id"],
                directory / f"{candidate['slug']}.json",
                freeze_path=base_freeze_path,
                client_factory=lambda repeat, config: HeroEvidenceClient(),
                extraction=extraction,
            )
        )
    packets = evaluate.build_review_packets_v2(
        artifacts,
        freeze_v2=freeze,
        extraction=extraction,
        base_policy=base_policy,
        truth=truth,
    )
    result = {
        "directory": directory,
        "extraction": extraction,
        "base_policy": base_policy,
        "policy_v2": policy_v2,
        "truth": truth,
        "review_schema": review_schema,
        "freeze": freeze,
        "artifacts": artifacts,
        "packets": packets,
    }
    result["review_a"] = _review(result, "human-reviewer-a")
    result["review_b"] = _review(result, "human-reviewer-b")
    result["adjudication"] = evaluate.adjudicate_reviews_v2(
        result["review_a"],
        result["review_b"],
        packet_set=packets,
        freeze_v2=freeze,
        truth=truth,
        review_schema=review_schema,
        policy_v2=policy_v2,
    )
    return result


def test_v2_sidecars_are_hash_pinned_and_forbid_aggregate_accuracy():
    policy, policy_bytes = evaluate.load_policy_v2()
    truth, truth_bytes = evaluate.load_truth_v2()
    schema, schema_bytes = evaluate.load_review_schema_v2()

    assert evaluate._sha256(policy_bytes) == evaluate.FROZEN_POLICY_V2_SHA256
    assert evaluate._sha256(truth_bytes) == evaluate.FROZEN_TRUTH_V2_SHA256
    assert evaluate._sha256(schema_bytes) == evaluate.FROZEN_REVIEW_SCHEMA_V2_SHA256
    assert policy["eligibility"]["aggregate_accuracy_is_gate"] is False
    assert policy["required_endpoint_class"] == "openai-compatible-zbook-local"
    assert policy["render_budget_scope"] == {
        "classification": "benchmark-complete-audit-wire-v1",
        "includes_model_run_manifest": True,
        "product_acceptance_target": False,
        "review_required_before_product_lock": True,
    }
    assert len(truth["facts"]) == 5
    assert len(truth["hard_negatives"]) == 5
    assert len(truth["payload_canaries"]) == 6
    assert schema["model_generated_review_allowed"] is False


def _sqlite_content(path: Path) -> tuple[object, ...]:
    uri = path.resolve().as_uri() + "?mode=ro&immutable=1"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        schema = connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY name"
        ).fetchall()
        rows = {
            name: connection.execute(
                f'SELECT * FROM "{name}" ORDER BY rowid'
            ).fetchall()
            for kind, name, _, _ in schema
            if kind == "table"
        }
        page_size = connection.execute("PRAGMA page_size").fetchone()
    return schema, rows, page_size


def test_final_tier3_fixtures_and_manifest_are_repeat_build_deterministic(
    tmp_path, monkeypatch
):
    hero_builder.validate()
    checked_payloads = {
        name: (evaluate.HERO_DIR / name).read_bytes() for name in RAW_ONLY_CANARIES
    }
    manifest_payload = evaluate.HERO_MANIFEST_PATH.read_bytes()
    manifest = json.loads(manifest_payload)
    manifest_entries = {item["path"]: item for item in manifest["files"]}

    assert hero_builder.RAW_ONLY_SQLITE_SENTINEL == RAW_ONLY_SQLITE_SENTINEL
    assert hero_builder.read_raw_canaries() == RAW_ONLY_CANARIES
    assert evaluate._truth_canary_values(
        evaluate.load_truth_v2()[0], hero_dir=evaluate.HERO_DIR
    ) == {
        CANARY_ID_BY_FILE[name]: literal
        for name, literal in RAW_ONLY_CANARIES.items()
    }
    assert evaluate._sha256(manifest_payload) == evaluate.FROZEN_HERO_MANIFEST_SHA256
    for name, checked_payload in checked_payloads.items():
        assert evaluate._sha256(checked_payload) == TIER3_FIXTURE_SHA256[name]
        assert manifest_entries[name] == {
            "bytes": len(checked_payload),
            "path": name,
            "sha256": TIER3_FIXTURE_SHA256[name],
        }

    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    monkeypatch.setattr(hero_builder, "HERO", first_root)
    hero_builder._build_locked_tier3()
    first_payloads = {
        name: (first_root / name).read_bytes() for name in RAW_ONLY_CANARIES
    }
    first_canaries = hero_builder.read_raw_canaries()
    first_manifest = hero_builder._manifest()
    monkeypatch.setattr(hero_builder, "HERO", second_root)
    hero_builder._build_locked_tier3()
    second_payloads = {
        name: (second_root / name).read_bytes() for name in RAW_ONLY_CANARIES
    }
    second_canaries = hero_builder.read_raw_canaries()
    second_manifest = hero_builder._manifest()

    assert first_payloads == second_payloads
    # safety.sqlite comes from the interpreter's SQLite, which uv.lock does not
    # pin, and SQLite versions differ in header and cell layout. Its checked
    # sha256 stays pinned above; a rebuild must match its schema and rows.
    assert {
        name: payload
        for name, payload in first_payloads.items()
        if name != "safety.sqlite"
    } == {
        name: payload
        for name, payload in checked_payloads.items()
        if name != "safety.sqlite"
    }
    assert _sqlite_content(first_root / "safety.sqlite") == _sqlite_content(
        evaluate.HERO_DIR / "safety.sqlite"
    )
    assert first_manifest == second_manifest
    assert first_canaries == second_canaries == RAW_ONLY_CANARIES


@pytest.mark.parametrize("shape", ["ansi", "md"])
def test_human_render_audit_verifies_observed_full_drop_records(shape):
    from autotldr.render import render
    from autotldr.unit import (
        Extraction,
        GroundedStatement,
        Modality,
        Origin,
        Relation,
        RelationKind,
        Unit,
    )

    kept = Unit(
        source="kept.md",
        modality=Modality.PROSE,
        content="compact evidence",
        origin=Origin("kept.md", "line:1", (0, 16)),
        salience=1.0,
    )
    unsafe_source = "源`\x1b\x7f\u202e🧪.md"
    dropped = Unit(
        source=unsafe_source,
        modality=Modality.PROSE,
        content="x" * 30_000,
        origin=Origin(unsafe_source, "line:`\x07\u2066é", (4, 44)),
        salience=0.0,
    )
    relation = Relation(
        kept.id,
        dropped.id,
        RelationKind.DERIVES_FROM,
        evidence="structural derivation",
    )
    statement = GroundedStatement(
        content="The retained fact is grounded in the omitted appendix.",
        origins=(kept.origin, dropped.origin),
        evidence_unit_ids=(kept.id, dropped.id),
    )
    extraction = Extraction(
        source="adversarial collection",
        kind="collection",
        units=[kept, dropped],
        relations=[relation],
        summary_claims=[statement],
    )
    budget = 8192
    text = render(extraction, output=shape, budget=budget)

    parsed, errors = evaluate._parse_human_render_audit(
        shape, text, extraction, budget
    )
    assert errors == []
    assert parsed["dropped_unit_ids"] == [dropped.id]
    assert parsed["dropped_relation_indexes"] == [0]
    assert parsed["dropped_statement_ids"] == [statement.id]

    prefix = "- drop-v1/" if shape == "ansi" else "  - `drop-v1/"
    suffix = "" if shape == "ansi" else "`"

    def unpack_record(line: str) -> tuple[str, str]:
        payload = line.removeprefix(prefix)
        if suffix:
            assert payload.endswith(suffix)
            payload = payload.removesuffix(suffix)
        return tuple(payload.split(" ", 1))

    def inventory(rendered: str) -> dict[str, list[dict]]:
        records = {"units": [], "relations": [], "statements": []}
        plural = {"unit": "units", "relation": "relations", "statement": "statements"}
        for line in rendered.splitlines():
            if line.startswith(prefix):
                kind, payload = unpack_record(line)
                records[plural[kind]].append(json.loads(payload))
        return records

    unit_line = next(
        line for line in text.splitlines() if line.startswith(prefix + "unit ")
    )
    kind, raw_record = unpack_record(unit_line)
    forged_record = json.loads(raw_record)
    forged_record["origin"]["ref"] = "line:forged"
    forged_payload = evaluate._canonical_human_drop_json(forged_record)
    forged_line = f"{prefix}{kind} {forged_payload}{suffix}"
    stale_digest_text = text.replace(unit_line, forged_line, 1)

    _parsed, stale_errors = evaluate._parse_human_render_audit(
        shape, stale_digest_text, extraction, budget
    )
    assert "human renderer unit drop records differ from extraction" in stale_errors
    assert "human renderer drop-set digest differs from wire inventory" in stale_errors

    old_digest = parsed["drop_digest"]
    forged_digest = evaluate._sha256(
        evaluate._canonical_bytes(inventory(stale_digest_text))
    )
    self_consistent_forgery = stale_digest_text.replace(
        old_digest, forged_digest, 1
    )
    _parsed, forged_errors = evaluate._parse_human_render_audit(
        shape, self_consistent_forgery, extraction, budget
    )
    assert "human renderer unit drop records differ from extraction" in forged_errors
    assert not any("digest" in error for error in forged_errors)


