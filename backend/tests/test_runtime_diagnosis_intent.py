"""Hermetic tests for the strict Runtime Diagnosis structured output contract."""

from decimal import Decimal
import unittest

from agents import AgentOutputSchema
from pydantic import ValidationError

from app.agent_runtime import (
    RuntimeDiagnosisIntent,
    runtime_intent_to_drafts,
)
from app.diagnosis import DiagnosisStatus, DiagnosisValidationError
from app.evidence import EvidenceRole


def diagnosed_payload() -> dict:
    return {
        "evidence_selections": [
            {"observation_id": "obs-target", "role": "supporting"},
            {"observation_id": "obs-driver", "role": "supporting"},
            {"observation_id": "obs-control", "role": "negative_control"},
        ],
        "status": "diagnosed",
        "target_metric": "sales",
        "target_evidence_id": "evidence:obs-target:supporting",
        "primary_driver": "conversion_rate",
        "affected_scope": [
            {"dimension": "marketplace", "value": "US"},
            {"dimension": "traffic_source", "value": "Ads"},
        ],
        "evidence_ids": [
            "evidence:obs-target:supporting",
            "evidence:obs-driver:supporting",
            "evidence:obs-control:negative_control",
        ],
        "confidence": "0.90",
        "limitations": ["Data contribution only."],
    }


class TestRuntimeDiagnosisIntent(unittest.TestCase):
    def parse(self, payload: dict) -> RuntimeDiagnosisIntent:
        return RuntimeDiagnosisIntent.model_validate_json(__import__("json").dumps(payload))

    def test_diagnosed_intent_converts_to_domain_drafts(self) -> None:
        evidence, diagnosis = runtime_intent_to_drafts(self.parse(diagnosed_payload()))
        self.assertEqual(
            tuple((item.observation_id, item.role) for item in evidence.selections),
            (
                ("obs-target", EvidenceRole.SUPPORTING),
                ("obs-driver", EvidenceRole.SUPPORTING),
                ("obs-control", EvidenceRole.NEGATIVE_CONTROL),
            ),
        )
        self.assertEqual(diagnosis.status, DiagnosisStatus.DIAGNOSED)
        self.assertEqual(dict(diagnosis.affected_scope), {"marketplace": "US", "traffic_source": "Ads"})
        self.assertEqual(diagnosis.confidence, Decimal("0.90"))

    def test_unambiguous_observation_id_evidence_aliases_are_normalized(self) -> None:
        payload = diagnosed_payload()
        payload["target_evidence_id"] = "obs-target"
        payload["evidence_ids"] = ["obs-target", "obs-driver", "obs-control"]

        _, diagnosis = runtime_intent_to_drafts(self.parse(payload))

        self.assertEqual(diagnosis.target_evidence_id, "evidence:obs-target:supporting")
        self.assertEqual(
            diagnosis.evidence_ids,
            (
                "evidence:obs-target:supporting",
                "evidence:obs-driver:supporting",
                "evidence:obs-control:negative_control",
            ),
        )

    def test_no_anomaly_and_empty_budget_intents_convert(self) -> None:
        normal = diagnosed_payload()
        normal.update({
            "evidence_selections": [{"observation_id": "obs-normal", "role": "supporting"}],
            "status": "no_material_anomaly",
            "target_evidence_id": "evidence:obs-normal:supporting",
            "primary_driver": None,
            "affected_scope": [],
            "evidence_ids": ["evidence:obs-normal:supporting"],
        })
        _, normal_draft = runtime_intent_to_drafts(self.parse(normal))
        self.assertEqual(normal_draft.status, DiagnosisStatus.NO_MATERIAL_ANOMALY)

        budget = diagnosed_payload()
        budget.update({
            "evidence_selections": [], "status": "budget_exhausted",
            "target_evidence_id": None, "primary_driver": None,
            "affected_scope": [], "evidence_ids": [], "confidence": None,
        })
        evidence, diagnosis = runtime_intent_to_drafts(self.parse(budget))
        self.assertEqual(evidence.selections, ())
        self.assertEqual(diagnosis.status, DiagnosisStatus.BUDGET_EXHAUSTED)

    def test_schema_rejects_extra_missing_enum_and_empty_strings(self) -> None:
        cases = []
        extra = diagnosed_payload(); extra["extra"] = "x"; cases.append(extra)
        missing = diagnosed_payload(); missing.pop("limitations"); cases.append(missing)
        enum = diagnosed_payload(); enum["status"] = "unknown"; cases.append(enum)
        empty = diagnosed_payload(); empty["target_metric"] = "   "; cases.append(empty)
        role = diagnosed_payload(); role["evidence_selections"][0]["role"] = "unknown"; cases.append(role)
        for payload in cases:
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                self.parse(payload)

    def test_python_tuple_and_string_pseudo_lists_are_rejected(self) -> None:
        base = diagnosed_payload()
        for field, value in (
            ("evidence_selections", tuple(base["evidence_selections"])),
            ("affected_scope", tuple(base["affected_scope"])),
            ("evidence_ids", "evidence-id"),
            ("limitations", "boundary"),
        ):
            payload = {**base, field: value}
            with self.subTest(field=field), self.assertRaises(ValidationError):
                RuntimeDiagnosisIntent.model_validate(payload)

    def test_duplicate_scope_and_domain_collections_are_rejected(self) -> None:
        duplicate_scope = diagnosed_payload()
        duplicate_scope["affected_scope"].append({"dimension": "marketplace", "value": "DE"})
        with self.assertRaises(DiagnosisValidationError):
            runtime_intent_to_drafts(self.parse(duplicate_scope))

        for field in ("evidence_selections", "evidence_ids"):
            payload = diagnosed_payload()
            payload[field].append(payload[field][0])
            with self.subTest(field=field), self.assertRaises(DiagnosisValidationError):
                runtime_intent_to_drafts(self.parse(payload))

    def test_confidence_valid_and_invalid_boundaries(self) -> None:
        for value, expected in (("0", Decimal("0")), ("1", Decimal("1")), ("0.125", Decimal("0.125"))):
            payload = diagnosed_payload(); payload["confidence"] = value
            _, draft = runtime_intent_to_drafts(self.parse(payload))
            self.assertEqual(draft.confidence, expected)

        for value in (0, 0.5, True):
            payload = diagnosed_payload(); payload["confidence"] = value
            with self.subTest(value=value), self.assertRaises(ValidationError):
                self.parse(payload)
        for value in (" ", "NaN", "Infinity", "-Infinity", "1.01", "-0.01"):
            payload = diagnosed_payload(); payload["confidence"] = value
            with self.subTest(value=value), self.assertRaises((ValidationError, DiagnosisValidationError)):
                runtime_intent_to_drafts(self.parse(payload))

    def test_models_are_deeply_immutable_and_fact_free(self) -> None:
        intent = self.parse(diagnosed_payload())
        self.assertIsInstance(intent.evidence_selections, tuple)
        self.assertIsInstance(intent.affected_scope, tuple)
        with self.assertRaises(ValidationError):
            intent.target_metric = "orders"
        forbidden = {"current_value", "baseline_value", "relative_change", "unit", "change", "root_cause"}
        self.assertTrue(forbidden.isdisjoint(RuntimeDiagnosisIntent.model_fields))
        for nested in intent.evidence_selections:
            self.assertTrue(forbidden.isdisjoint(nested.__class__.model_fields))

    def test_official_sdk_output_schema_is_strict_and_closed(self) -> None:
        schema = AgentOutputSchema(RuntimeDiagnosisIntent)
        self.assertTrue(schema.is_strict_json_schema())
        json_schema = schema.json_schema()

        def assert_closed(node):
            if isinstance(node, dict):
                if node.get("type") == "object":
                    self.assertFalse(node.get("additionalProperties", True))
                for value in node.values():
                    assert_closed(value)
            elif isinstance(node, list):
                for value in node:
                    assert_closed(value)

        assert_closed(json_schema)

    def test_non_intent_input_is_rejected(self) -> None:
        with self.assertRaises(DiagnosisValidationError):
            runtime_intent_to_drafts(object())


if __name__ == "__main__":
    unittest.main()
