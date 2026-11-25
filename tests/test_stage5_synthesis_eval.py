"""Offline tests for the frozen Stage 5 synthesis eval and safe runner."""

from __future__ import annotations

import importlib.util
import hashlib
import json
import sys
from pathlib import Path

import pytest

from autotldr.unit import Extraction, Modality, Origin, Relation, RelationKind, Unit


ROOT = Path(__file__).resolve().parents[1]
EVALUATE_PATH = ROOT / "benchmarks" / "synthesis" / "evaluate.py"


def _load(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification and specification.loader
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


evaluate = _load("autotldr_stage5_eval_test", EVALUATE_PATH)


def _unit(source: str, content: str, *, modality: Modality = Modality.PROSE) -> Unit:
    return Unit(
        source=source,
        modality=modality,
        content=content,
        origin=Origin(source, "source"),
        salience=0.9,
    )


def _evaluation_collection() -> Extraction:
    units = [
        _unit(
            "borealis/overview.md",
            "Borealis monitors Station Alpha reservoir cooling and safety. "
            "reservoir_temp_c is 18.0 and pressure_kpa is 240. "
            "calibration/current.csv is missing.",
        ),
        _unit(
            "borealis/config.json",
            "reservoir_temp_c target 18.0 degC; pressure_kpa ceiling 240 kPa",
            modality=Modality.RECORD,
        ),
        _unit(
            "borealis/controller.py",
            "The controller consumes configuration and telemetry measurements and "
            "records safety events in SQLite.",
            modality=Modality.CODE,
        ),
        _unit(
            "borealis/measurements.parquet",
            "Telemetry schema: reservoir_temp_c, pressure_kpa",
            modality=Modality.SCHEMA,
        ),
        _unit(
            "borealis/safety.sqlite",
            "Safety event store schema",
            modality=Modality.SCHEMA,
        ),
        _unit(
            "borealis/experiments.h5",
            "experiments.h5 provides scientific experiment context",
            modality=Modality.SCHEMA,
        ),
        _unit(
            "borealis/forecast.nc",
            "forecast.nc provides NetCDF scientific forecast context",
            modality=Modality.SCHEMA,
        ),
        _unit(
            "borealis/capacity.xlsx",
            "capacity workbook computes reserve margin",
            modality=Modality.EQUATION,
        ),
        _unit(
            "borealis/operations.html",
            "Operators review reservoir safety alerts.",
        ),
        _unit(
            "borealis/station.csv",
            "Station metric schema and units",
            modality=Modality.SCHEMA,
        ),
    ]
    relations = [
        Relation(
            units[index].id,
            units[index + 1].id,
            RelationKind.CORRESPONDS,
            evidence=f"offline-eval-link-{index}",
            confidence=1.0,
        )
        for index in range(len(units) - 1)
    ]
    manifest = {
        "schema": 1,
        "source": "borealis",
        "kind": "directory",
        "container": {"type": "synthetic-offline-test"},
        "policy": {"ordering": "test-order-v1"},
        "limits": {"max_members": 10},
        "members": [
            {"order": index, "source": unit.source, "status": "extracted"}
            for index, unit in enumerate(units)
        ],
        "counts": {
            "extracted": len(units),
            "declined": 0,
            "ignored": 0,
            "records": len(units),
        },
        "admitted_bytes": 1_024,
    }
    manifest["sha256"] = hashlib.sha256(
        json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    production_fusion = {
        "backend": "deterministic-signals-v1",
        "signals": {
            "literal-v1": {
                "version": "literal-v1",
                "accepted": 0,
                "raw_before_disposition": 0,
                "disposition": {"status": "ship-complete", "subtypes": []},
                "policy": {
                    "acceptance": "unique exact or lexically normalized source identity",
                    "ambiguous": "abstain",
                },
            },
            "identifier-v1": {
                "version": "identifier-v1",
                "accepted": 0,
                "raw_before_disposition": 0,
                "disposition": {
                    "status": "ship-preregistered-subtype",
                    "subtypes": ["native-native"],
                },
                "policy": {
                    "anchor_required": True,
                    "single_discriminative_token_min_chars": 6,
                    "common_token_suppression": "fixed-v1",
                },
            },
            "structural-v1": {
                "version": "structural-v1",
                "accepted": 0,
                "raw_before_disposition": 0,
                "disposition": {"status": "ship-complete", "subtypes": []},
                "policy": {
                    "minimum_discriminative_fields": 3,
                    "minimum_jaccard": {"numerator": 3, "denominator": 4},
                    "minimum_type_compatibility": {"numerator": 4, "denominator": 5},
                },
            },
            "contradiction-v1": {
                "version": "contradiction-v1",
                "accepted": 0,
                "raw_before_disposition": 0,
                "disposition": {"status": "disable", "subtypes": []},
                "policy": {
                    "explicit_scalar_only": True,
                    "ambiguous_within_source": "abstain",
                    "different_units": "abstain",
                },
            },
        },
        "orphans": [],
        "evaluated_dispositions": {
            "evaluated_implementation_sha256": (
                "830d42e7efcdf3fd20beac11733acf9276c0484af810e439dd70122de8dc8420"
            ),
            "scored_predictions_sha256": (
                "c9fd530184b14219cbc6f409380dd0a1e6ac45c12efda445c90ef5a184d17ac9"
            ),
            "signals": {
                "literal-v1": {"status": "ship-complete", "subtypes": []},
                "identifier-v1": {
                    "status": "ship-preregistered-subtype",
                    "subtypes": ["native-native"],
                },
                "structural-v1": {"status": "ship-complete", "subtypes": []},
                "contradiction-v1": {"status": "disable", "subtypes": []},
                "orphan-v1": {"status": "disable", "subtypes": []},
                "unresolved-v1": {
                    "status": "ship-preregistered-subtype",
                    "subtypes": ["local-path"],
                },
            },
            "unresolved_raw_before_disposition": 1,
            "orphan_candidates_suppressed": 0,
        },
    }
    return Extraction(
        source="borealis",
        kind="collection",
        units=units,
        relations=relations,
        meta={"models": [], "acquisition": manifest, "fusion": production_fusion},
    )


def _freeze(tmp_path: Path, extraction: Extraction) -> tuple[Path, dict]:
    record = evaluate.build_freeze_record(extraction=extraction)
    target = tmp_path / "freeze.json"
    evaluate.write_freeze(target, record)
    return target, record


def test_freeze_binds_policy_hero_extraction_evidence_and_all_requests(tmp_path):
    extraction = _evaluation_collection()
    path, record = _freeze(tmp_path, extraction)

    verified, observed_extraction = evaluate.verify_freeze_record(
        evaluate.read_freeze(path), extraction=extraction
    )

    assert verified == record
    assert observed_extraction is extraction
    assert record["policy"]["sha256"] == evaluate.FROZEN_POLICY_SHA256
    assert record["hero"]["manifest_sha256"] == evaluate.FROZEN_HERO_MANIFEST_SHA256
    assert record["acquisition"]["manifest_sha256"] == (
        extraction.meta["acquisition"]["sha256"]
    )
    assert record["acquisition"]["member_count"] == 10
    assert record["extraction"]["unit_count"] == 10
    assert record["evidence_pack"]["bytes"] <= 24_000
    assert len(record["requests"]) == 4
    assert len({item["sha256"] for item in record["requests"]}) == 4
    assert record["freeze_sha256"]

    with pytest.raises(evaluate.EvaluationError, match="overwrite"):
        evaluate.write_freeze(path, record)


def test_freeze_rejects_missing_or_tampered_acquisition_manifest():
    missing = _evaluation_collection()
    missing.meta.pop("acquisition")
    with pytest.raises(evaluate.EvaluationError, match="no Tier 2 acquisition"):
        evaluate.build_freeze_record(extraction=missing)

    tampered = _evaluation_collection()
    tampered.meta["acquisition"]["members"][0]["status"] = "declined"
    with pytest.raises(evaluate.EvaluationError, match="self-hash is invalid"):
        evaluate.build_freeze_record(extraction=tampered)


def test_real_hero_freeze_is_reproducible_bounded_and_fact_recoverable():
    first = evaluate.build_freeze_record()
    second = evaluate.build_freeze_record()

    assert first == second
    assert first["extraction"]["unit_count"] > 0
    assert first["extraction"]["relation_count"] > 0
    assert first["extraction"]["gap_count"] > 0
    assert first["evidence_pack"]["bytes"] <= 24_000
    assert first["evidence_pack"]["selection"]["selected_unit_count"] <= 48
    assert first["evidence_pack"]["selection"]["selected_source_count"] >= 8
    assert all(
        item["recoverable_from_pack"]
        for item in first["evidence_pack"]["required_fact_coverage"]
    )


def test_pre_output_freeze_guard_refuses_an_existing_candidate_artifact(tmp_path):
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    (output_dir / "granite.json").write_text("model output", encoding="utf-8")

    with pytest.raises(evaluate.EvaluationError, match="after candidate output exists"):
        evaluate.require_no_model_outputs(output_dir)


def test_fact_regex_without_support_in_the_cited_unit_is_not_recovered():
    extraction = _evaluation_collection()
    policy, _ = evaluate.load_policy()
    fact = next(item for item in policy["required_facts"] if item["id"] == "purpose")
    unrelated = next(unit for unit in extraction.units if unit.source.endswith("station.csv"))
    score = evaluate._score_fact(
        fact,
        [
            {
                "content": "Borealis monitors the reservoir cooling system for safety.",
                "evidence_unit_ids": [unrelated.id],
            }
        ],
        {unrelated.id: unrelated.source},
        {unrelated.id: [unrelated.content]},
    )

    assert score["content_recovered"] is True
    assert score["evidence_supported"] is False
    assert score["recovered"] is False


