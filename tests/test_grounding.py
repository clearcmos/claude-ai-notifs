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
                         "Investigated Okta access.")

    def test_false_changed_label_on_investigation_is_downgraded(self):
        source = "I investigated how Okta access is granted. No access was changed."
        value = assessment(
            "changed",
            "investigated how Okta access is granted",
            "Okta access",
        )
        self.assertEqual(render.render(source, value),
                         "Worked on Okta access.")

    def test_explicit_completed_change_is_accepted(self):
        source = "I granted Maya access to Okta and verified her role."
        value = assessment(
            "changed",
            "I granted Maya access to Okta",
            "Maya access to Okta",
        )
        self.assertEqual(render.render(source, value),
                         "Made changes to Maya access to Okta.")

    def test_explicit_passive_change_is_accepted(self):
        source = "Maya's Workday access was granted and the ticket was updated."
        value = assessment(
            "changed",
            "Maya's Workday access was granted",
            "Maya's Workday access",
        )
        self.assertEqual(render.render(source, value),
                         "Made changes to Maya's Workday access.")

    def test_contracted_completed_change_is_accepted(self):
        source = ("I've updated the zram configuration to use zstd "
                  "and committed the change.")
        value = assessment(
            "changed",
            "I've updated the zram configuration",
            "the zram configuration",
        )
        self.assertEqual(render.render(source, value),
                         "Made changes to the zram configuration.")

    def test_adverbial_completed_change_is_accepted(self):
        source = "Done. I also enabled the systemd unit and pushed the commit."
        value = assessment(
            "changed",
            "I also enabled the systemd unit",
            "the systemd unit",
        )
        self.assertEqual(render.render(source, value),
                         "Made changes to the systemd unit.")

    def test_hedged_contracted_change_stays_neutral(self):
        source = "I've patched the retry loop so it should no longer stall."
        value = assessment(
            "changed",
            "I've patched the retry loop so it should no longer stall",
            "the retry loop",
        )
        self.assertEqual(render.render(source, value),
                         "Worked on the retry loop.")

    def test_general_description_of_how_access_is_granted_is_not_a_change(self):
        source = "I found that access is granted through the administrators group."
        value = assessment(
            "changed",
            "access is granted through the administrators group",
            "access",
        )
        self.assertEqual(render.render(source, value),
                         "Worked on access.")

    def test_negated_change_is_not_accepted(self):
        source = "I did not update production; I only documented the procedure."
        value = assessment(
            "changed",
            "I did not update production",
            "production",
        )
        self.assertEqual(render.render(source, value),
                         "Worked on production.")

    def test_evidence_must_come_from_source(self):
        source = "I reviewed the deployment instructions."
        value = assessment("verified", "All deployment tests passed", "deployment")
        self.assertEqual(render.render(source, value),
                         "Worked on deployment.")

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
                         "Verified skill on origin/main.")

    def test_ellipsis_evidence_fragments_must_remain_in_order(self):
        source = "First the configuration was checked. Then the tests passed."
        value = assessment(
            "verified",
            "the tests passed ... configuration was checked",
            "configuration",
        )
        self.assertEqual(render.render(source, value),
                         "Worked on configuration.")

    def test_status_must_be_supported_by_its_evidence(self):
        source = "I explained the access steps, but did not perform them."
        value = assessment(
            "failed",
            "I explained the access steps, but did not perform them",
            "access steps",
        )
        self.assertEqual(render.render(source, value),
                         "Worked on access steps.")

    def test_verified_status_with_matching_evidence_is_accepted(self):
        source = "I verified the Admin role after updating the account."
        value = assessment("verified", "I verified the Admin role", "Admin role")
        self.assertEqual(render.render(source, value),
                         "Verified Admin role.")

    def test_negated_verification_is_not_accepted(self):
        source = "I did not verify the production deployment."
        value = assessment("verified", "did not verify", "production deployment")
        self.assertEqual(render.render(source, value),
                         "Worked on production deployment.")

    def test_no_error_is_not_rendered_as_failure(self):
        source = "The checks completed without errors."
        value = assessment("failed", "without errors", "checks")
        self.assertEqual(render.render(source, value),
                         "Worked on checks.")

    def test_not_blocked_is_not_rendered_as_blocked(self):
        source = "The migration is not blocked."
        value = assessment("blocked", "not blocked", "migration")
        self.assertEqual(render.render(source, value),
                         "Worked on migration.")

    def test_topic_must_come_from_source(self):
        source = "I investigated the authentication flow."
        value = assessment("investigated", "investigated", "production database")
        self.assertEqual(render.render(source, value),
                         "Investigated the request.")

    def test_topic_can_reorder_grounded_words(self):
        source = "The comparison covers pricing for OneLogin versus Okta."
        value = assessment(
            "answered",
            "The comparison covers pricing",
            "OneLogin and Okta pricing",
        )
        self.assertEqual(render.render(source, value),
                         "Explained OneLogin and Okta pricing.")

    def test_topic_cannot_introduce_an_unsupported_word(self):
        source = "I investigated the authentication flow."
        value = assessment("investigated", "investigated", "production flow")
        self.assertEqual(render.render(source, value),
                         "Investigated the request.")

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
            "Produced the requested poem.",
        )

    def test_produced_without_content_request_downgrades_neutrally(self):
        # The request never asked for content, so even reply-grounded evidence
        # may not render a creation claim; the reply still grounds the topic.
        source = "Here is a limerick about a compiler."
        value = assessment("produced", "Here is a limerick", "limerick")
        self.assertEqual(
            render.render(source, value, topic_source="surprise me"),
            "Worked on limerick.",
        )

    def test_explaining_existing_feature_is_not_produced(self):
        # Regression: llama3.2:3b labeled a feature explanation "produced" and
        # the old template announced "Claude created the requested codebase."
        source = (
            "Yes. The QA logging is the setup.sh --log-on / --log-off pair, "
            "added on this branch along with its test."
        )
        value = assessment(
            "produced",
            "The QA logging is the setup.sh --log-on / --log-off pair",
            "codebase",
        )
        self.assertEqual(
            render.render(
                source,
                value,
                topic_source=(
                    "This codebase now has a way to log responses for QA "
                    "purposes. Do you see that?"
                ),
            ),
            "Worked on codebase.",
        )

    def test_question_about_generating_is_not_a_content_request(self):
        # Reviewer-reported bypass: content vocabulary inside a question about
        # existing behavior must not license a "produced" creation claim.
        source = "This function generates a summary of the changes."
        value = assessment(
            "produced", "This function generates a summary", "summary"
        )
        self.assertEqual(
            render.render(
                source,
                value,
                topic_source="Does this function generate a summary?",
            ),
            "Worked on summary.",
        )

    def test_question_about_writing_is_not_a_content_request(self):
        source = "By default it writes the report to /var/log nightly."
        value = assessment(
            "produced", "it writes the report to /var/log", "report"
        )
        self.assertEqual(
            render.render(
                source, value, topic_source="Where does it write the report?"
            ),
            "Worked on report.",
        )

    def test_directive_explain_is_not_a_content_request(self):
        # Round-two reviewer bypasses: a directive marker must govern the
        # content verb itself, not merely coexist with content vocabulary.
        source = "It builds the tree, then generates a summary of the changes."
        value = assessment(
            "produced", "generates a summary of the changes", "summary"
        )
        for request in (
            "Can you explain how this function generates a summary?",
            "Please explain how this function generates a summary.",
        ):
            with self.subTest(request=request):
                self.assertEqual(
                    render.render(source, value, topic_source=request),
                    "Worked on summary.",
                )

    def test_i_need_to_know_is_not_a_content_request(self):
        source = "By default it writes the report to /var/log nightly."
        value = assessment(
            "produced", "it writes the report to /var/log", "report"
        )
        self.assertEqual(
            render.render(
                source,
                value,
                topic_source="I need to know where it writes the report.",
            ),
            "Worked on report.",
        )

    def test_directed_content_verbs_still_render_produced(self):
        source = "Dawn code compiles in silence."
        value = assessment("produced", "Dawn code compiles in silence", "poem")
        for request in (
            "I need you to write a poem",
            "we want a poem for the launch page",
            "can I get a haiku? make it a poem about spring",
        ):
            with self.subTest(request=request):
                self.assertEqual(
                    render.render(source, value, topic_source=request),
                    "Produced the requested poem.",
                )

    def test_quoted_or_hyphenated_verbs_are_not_imperatives(self):
        # Round-three reviewer bypasses: quotes and bullet markers count only
        # at a real line or sentence boundary, and a bullet needs following
        # whitespace, so hyphenated words and quoted names never match.
        source = "Yes. The nightly job runs it and writes the report."
        value = assessment("produced", "writes the report", "report")
        for request in (
            'Does the "write report" command run nightly?',
            "Does the 'generate summary' option use the diff?",
            "Does the read-write path generate a report?",
            "Does auto-generate produce a summary here?",
        ):
            with self.subTest(request=request):
                self.assertEqual(
                    render.render(source, value, topic_source=request),
                    "Worked on report.",
                )

    def test_colon_introduced_quotations_are_not_imperatives(self):
        # Round-four reviewer bypasses: sentence punctuation is not an
        # imperative boundary, so colon-introduced quotations and embedded
        # instructions stay neutral. "Thanks. write a summary." falling
        # neutral is the documented false-negative cost of that choice.
        source = "Yes. It writes a summary after each run."
        value = assessment("produced", "writes a summary", "summary")
        for request in (
            'Why does the prompt say: "generate a summary"?',
            'Does it invoke this command: "write report"?',
            "The documentation says: write a summary after each run. "
            "Is that current?",
            "Thanks for checking. write a summary of it.",
        ):
            with self.subTest(request=request):
                self.assertEqual(
                    render.render(source, value, topic_source=request),
                    "Worked on summary.",
                )

    def test_bulleted_and_quoted_requests_still_render_produced(self):
        source = "Silver rain writes on the window."
        value = assessment("produced", "Silver rain writes", "poem")
        for request in (
            "things to do:\n- write a poem about rain",
            '"write a poem about rain"',
        ):
            with self.subTest(request=request):
                self.assertEqual(
                    render.render(source, value, topic_source=request),
                    "Produced the requested poem.",
                )

    def test_question_shaped_directive_still_renders_produced(self):
        source = "Roses bloom in quiet code."
        value = assessment("produced", "Roses bloom in quiet code", "poem")
        self.assertEqual(
            render.render(
                source, value, topic_source="can you write a poem?"
            ),
            "Produced the requested poem.",
        )

    def test_summary_request_still_renders_produced(self):
        source = "The sprint delivered the parser and the cache layer."
        value = assessment(
            "produced",
            "delivered the parser and the cache layer",
            "sprint summary",
        )
        self.assertEqual(
            render.render(
                source, value, topic_source="give me a summary of the sprint"
            ),
            "Produced the requested sprint summary.",
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
            "Worked on Maya access.",
        )

    def test_produced_without_specific_topic_has_safe_wording(self):
        source = "Blue light gathers where the quiet evening ends."
        value = assessment("produced", "Blue light gathers", "sonnet")
        self.assertEqual(
            render.render(source, value, topic_source="make something creative"),
            "Produced the requested content.",
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
            "Waiting on the reviewer.",
        )

    def test_state_summary_is_rendered_as_recap(self):
        source = "Current state: deployment is paused and testing remains open."
        value = assessment("recapped", "Current state", "deployment")
        self.assertEqual(
            render.render(source, value, topic_source="okay"),
            "Recapped deployment.",
        )

    def test_generic_waiting_topic_uses_status_specific_fallback(self):
        source = "The request is waiting for external approval."
        value = assessment("waiting", "waiting for external approval", "request")
        self.assertEqual(
            render.render(source, value, topic_source="I'll wait"),
            "Waiting for the next step.",
        )

    def test_waiting_requires_dependency_evidence(self):
        source = "The cursor blinks, a patient friend."
        value = assessment("waiting", "The cursor blinks", "poem")
        self.assertEqual(
            render.render(source, value, topic_source="write a poem"),
            "Worked on poem.",
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
            "Worked on deployment.",
        )

    def test_generic_recap_topic_uses_status_specific_fallback(self):
        source = "Here is a recap of the current task."
        value = assessment("recapped", "Here is a recap", "task")
        self.assertEqual(
            render.render(source, value, topic_source="thanks"),
            "Recapped the current state.",
        )

    def test_force_neutral_overrides_supported_change(self):
        source = "Grant Maya access to Okta"
        value = assessment("changed", "Grant Maya access", "Maya access to Okta")
        self.assertEqual(render.render(source, value, force_neutral=True),
                         "Worked on Maya access to Okta.")

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
        self.assertEqual(result.stdout, "Investigated Okta access.")

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
        self.assertEqual(result.stdout, "Produced the requested poem.")

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
