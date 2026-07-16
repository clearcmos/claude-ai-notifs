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
