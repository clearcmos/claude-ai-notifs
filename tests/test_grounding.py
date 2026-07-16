#!/usr/bin/env python3
"""Regression tests for conservative Stop-announcement rendering."""

import importlib.util
import json
import pathlib
import subprocess
import sys
import unittest


_MODULE_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / "bin"
    / "claude-announce-render.py"
)
_spec = importlib.util.spec_from_file_location("claude_announce_render", _MODULE_PATH)
render = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(render)


def assessment(status, evidence, topic):
    return {"status": status, "evidence": evidence, "topic": topic}


class GroundedRendering(unittest.TestCase):
    def test_authoritative_hook_reply_preserves_head_and_tail(self):
        reply = "start " + ("x" * 3000) + " no changes were made"
        value = render.reply_from_hook(json.dumps({"last_assistant_message": reply}))
        self.assertTrue(value.startswith("start "))
        self.assertTrue(value.endswith(" no changes were made"))
        self.assertIn("middle omitted", value)
        self.assertLess(len(value), len(reply))

    def test_hook_reply_rejects_invalid_shapes(self):
        self.assertEqual(render.reply_from_hook("not json"), "")
        self.assertEqual(render.reply_from_hook(json.dumps(
            {"last_assistant_message": {"unexpected": "object"}}
        )), "")

    def test_investigation_is_not_rendered_as_completed(self):
        source = "I investigated how Okta access is granted. No access was changed."
        value = assessment(
            "investigated",
            "investigated how Okta access is granted",
            "Okta access",
        )
        self.assertEqual(render.render(source, value),
                         "Claude investigated Okta access.")

    def test_false_changed_label_on_investigation_is_downgraded(self):
        source = "I investigated how Okta access is granted. No access was changed."
        value = assessment(
            "changed",
            "investigated how Okta access is granted",
            "Okta access",
        )
        self.assertEqual(render.render(source, value),
                         "Claude worked on Okta access.")

    def test_explicit_completed_change_is_accepted(self):
        source = "I granted Maya access to Okta and verified her role."
        value = assessment(
            "changed",
            "I granted Maya access to Okta",
            "Maya access to Okta",
        )
        self.assertEqual(render.render(source, value),
                         "Claude made changes to Maya access to Okta.")

    def test_explicit_passive_change_is_accepted(self):
        source = "Maya's Workday access was granted and the ticket was updated."
        value = assessment(
            "changed",
            "Maya's Workday access was granted",
            "Maya's Workday access",
        )
        self.assertEqual(render.render(source, value),
                         "Claude made changes to Maya's Workday access.")

    def test_general_description_of_how_access_is_granted_is_not_a_change(self):
        source = "I found that access is granted through the administrators group."
        value = assessment(
            "changed",
            "access is granted through the administrators group",
            "access",
        )
        self.assertEqual(render.render(source, value),
                         "Claude worked on access.")

    def test_negated_change_is_not_accepted(self):
        source = "I did not update production; I only documented the procedure."
        value = assessment(
            "changed",
            "I did not update production",
            "production",
        )
        self.assertEqual(render.render(source, value),
                         "Claude worked on production.")

    def test_evidence_must_come_from_source(self):
        source = "I reviewed the deployment instructions."
        value = assessment("verified", "All deployment tests passed", "deployment")
        self.assertEqual(render.render(source, value),
                         "Claude worked on deployment.")

    def test_ordered_ellipsis_evidence_is_grounded(self):
        source = (
            "The skill commit is on origin/main, and both files are present "
            "there. Your skill is included and unaffected."
        )
        value = assessment(
            "verified",
            "The skill commit is on origin/main ... both files are present "
            "there. ... Your skill is included and unaffected",
            "skill on origin/main",
        )
        self.assertEqual(render.render(source, value),
                         "Claude verified skill on origin/main.")

    def test_ellipsis_evidence_fragments_must_remain_in_order(self):
        source = "First the configuration was checked. Then the tests passed."
        value = assessment(
            "verified",
            "the tests passed ... configuration was checked",
            "configuration",
        )
        self.assertEqual(render.render(source, value),
                         "Claude worked on configuration.")

    def test_status_must_be_supported_by_its_evidence(self):
        source = "I explained the access steps, but did not perform them."
        value = assessment(
            "failed",
            "I explained the access steps, but did not perform them",
            "access steps",
        )
        self.assertEqual(render.render(source, value),
                         "Claude worked on access steps.")

    def test_verified_status_with_matching_evidence_is_accepted(self):
        source = "I verified the Admin role after updating the account."
        value = assessment("verified", "I verified the Admin role", "Admin role")
        self.assertEqual(render.render(source, value),
                         "Claude verified Admin role.")

    def test_negated_verification_is_not_accepted(self):
        source = "I did not verify the production deployment."
        value = assessment("verified", "did not verify", "production deployment")
        self.assertEqual(render.render(source, value),
                         "Claude worked on production deployment.")

    def test_no_error_is_not_rendered_as_failure(self):
        source = "The checks completed without errors."
        value = assessment("failed", "without errors", "checks")
        self.assertEqual(render.render(source, value),
                         "Claude worked on checks.")

    def test_not_blocked_is_not_rendered_as_blocked(self):
        source = "The migration is not blocked."
        value = assessment("blocked", "not blocked", "migration")
        self.assertEqual(render.render(source, value),
                         "Claude worked on migration.")

    def test_topic_must_come_from_source(self):
        source = "I investigated the authentication flow."
        value = assessment("investigated", "investigated", "production database")
        self.assertEqual(render.render(source, value),
                         "Claude investigated the request.")

    def test_topic_can_reorder_grounded_words(self):
        source = "The comparison covers pricing for OneLogin versus Okta."
        value = assessment(
            "answered",
            "The comparison covers pricing",
            "OneLogin and Okta pricing",
        )
        self.assertEqual(render.render(source, value),
                         "Claude explained OneLogin and Okta pricing.")

    def test_topic_cannot_introduce_an_unsupported_word(self):
        source = "I investigated the authentication flow."
        value = assessment("investigated", "investigated", "production flow")
        self.assertEqual(render.render(source, value),
                         "Claude investigated the request.")

    def test_latest_request_can_ground_a_produced_topic(self):
        source = (
            "The cursor blinks, a patient friend,\n"
            "through tangled logs and lines that bend.\n"
            "A quiet chime, the work is done —\n"
            "soft as dusk, and won."
        )
        value = assessment(
            "produced",
            "The cursor blinks, a patient friend",
            "poem",
        )
        self.assertEqual(
            render.render(source, value, topic_source="write 4 lines poem"),
            "Claude created the requested poem.",
        )

    def test_reply_can_still_ground_topic_when_request_does_not(self):
        source = "Here is a limerick about a compiler."
        value = assessment("produced", "Here is a limerick", "limerick")
        self.assertEqual(
            render.render(source, value, topic_source="surprise me"),
            "Claude created the requested limerick.",
        )

    def test_latest_request_is_never_outcome_evidence(self):
        source = "I investigated the permissions. No changes were made."
        value = assessment(
            "changed",
            "grant Maya access",
            "Maya access",
        )
        self.assertEqual(
            render.render(source, value, topic_source="grant Maya access"),
            "Claude worked on Maya access.",
        )

    def test_produced_without_specific_topic_has_safe_wording(self):
        source = "Blue light gathers where the quiet evening ends."
        value = assessment("produced", "Blue light gathers", "sonnet")
        self.assertEqual(
            render.render(source, value, topic_source="make something creative"),
            "Claude produced the requested content.",
        )

    def test_vague_request_can_use_reply_topic_for_waiting(self):
        source = (
            "Sounds good. Nothing to do until the reviewer acts. "
            "Ping me tomorrow when there's movement."
        )
        value = assessment(
            "waiting",
            "Nothing to do until the reviewer acts",
            "the reviewer",
        )
        self.assertEqual(
            render.render(
                source,
                value,
                topic_source="I will wait until tomorrow to see",
            ),
            "Claude is waiting on the reviewer.",
        )

    def test_state_summary_is_rendered_as_recap(self):
        source = "Current state: deployment is paused and testing remains open."
        value = assessment("recapped", "Current state", "deployment")
        self.assertEqual(
            render.render(source, value, topic_source="okay"),
            "Claude recapped deployment.",
        )

    def test_generic_waiting_topic_uses_status_specific_fallback(self):
        source = "The request is waiting for external approval."
        value = assessment("waiting", "waiting for external approval", "request")
        self.assertEqual(
            render.render(source, value, topic_source="I'll wait"),
            "Claude is waiting for the next step.",
        )

    def test_waiting_requires_dependency_evidence(self):
        source = "The cursor blinks, a patient friend."
        value = assessment("waiting", "The cursor blinks", "poem")
        self.assertEqual(
            render.render(source, value, topic_source="write a poem"),
            "Claude worked on poem.",
        )

    def test_negated_waiting_is_not_accepted(self):
        source = "The deployment is no longer waiting on approval."
        value = assessment(
            "waiting",
            "no longer waiting on approval",
            "deployment",
        )
        self.assertEqual(
            render.render(source, value),
            "Claude worked on deployment.",
        )

    def test_generic_recap_topic_uses_status_specific_fallback(self):
        source = "Here is a recap of the current task."
        value = assessment("recapped", "Here is a recap", "task")
        self.assertEqual(
            render.render(source, value, topic_source="thanks"),
            "Claude recapped the current state.",
        )

    def test_force_neutral_overrides_supported_change(self):
        source = "Grant Maya access to Okta"
        value = assessment("changed", "Grant Maya access", "Maya access to Okta")
        self.assertEqual(render.render(source, value, force_neutral=True),
                         "Claude worked on Maya access to Okta.")

    def test_malformed_assessment_is_empty_for_model_fallback(self):
        self.assertEqual(render.render("source", None), "")

    def test_fenced_json_is_accepted(self):
        raw = "```json\n" + json.dumps(
            assessment("answered", "Here are the steps", "administrator steps")
        ) + "\n```"
        self.assertEqual(
            render.parse_assessment(raw),
            assessment("answered", "Here are the steps", "administrator steps"),
        )

    def test_cli_renders_plain_sentence(self):
        source = "I investigated Okta access."
        value = assessment("investigated", "investigated", "Okta access")
        result = subprocess.run(
            [sys.executable, str(_MODULE_PATH), source],
            input=json.dumps(value),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "Claude investigated Okta access.")

    def test_cli_accepts_latest_request_as_topic_source_only(self):
        source = "Morning opens slowly over rain-dark streets."
        value = assessment("produced", "Morning opens slowly", "poem")
        result = subprocess.run(
            [
                sys.executable,
                str(_MODULE_PATH),
                "--topic-source",
                "write a poem",
                "--",
                source,
            ],
            input=json.dumps(value),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "Claude created the requested poem.")

    def test_cli_extracts_hook_reply(self):
        result = subprocess.run(
            [sys.executable, str(_MODULE_PATH), "--hook-reply"],
            input=json.dumps({"last_assistant_message": "Final response."}),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "Final response.")


if __name__ == "__main__":
    unittest.main()
