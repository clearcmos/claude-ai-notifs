#!/usr/bin/env python3
"""Validate a model assessment and render a conservative announcement.

The model is allowed to classify and extract, but it never writes the final
sentence.  Evidence and topic text must occur in the assistant reply; invalid
or unsupported assessments are downgraded to neutral wording.  Stdlib only.
"""

import argparse
import json
import re
import sys


STATUSES = {
    "changed",
    "investigated",
    "answered",
    "proposed",
    "verified",
    "blocked",
    "failed",
    "unknown",
}

# A "changed" classification is the risky case: accepting it can turn research
# into a claim that something happened. Require explicit, completed-action
# language in the quoted evidence. False negatives deliberately fall back to
# "worked on"; a less exciting notification is better than a false one.
_CHANGE_VERBS = (
    "added|applied|changed|committed|configured|corrected|created|deleted|"
    "deployed|disabled|enabled|fixed|granted|implemented|installed|merged|"
    "migrated|modified|patched|refactored|removed|renamed|replaced|resolved|"
    "restored|revoked|saved|updated|wrote"
)
_EXPLICIT_CHANGE = re.compile(
    rf"(?:\b(?:I|we)\s+(?:have\s+)?(?:{_CHANGE_VERBS})\b|"
    rf"\b(?:has|have)\s+been\s+(?:{_CHANGE_VERBS})\b|"
    rf"\b(?:was|were)\s+(?:{_CHANGE_VERBS})\b|"
    rf"^\s*(?:successfully\s+)?(?:{_CHANGE_VERBS})\b)",
    re.IGNORECASE,
)
_NEGATION_OR_UNCERTAINTY = re.compile(
    r"\b(?:did(?:n't| not)|not|never|would|could|should|might|may|"
    r"investigat(?:e|ed|ing)|research(?:ed|ing)?|looked into|"
    r"plan(?:ned|ning)?|propos(?:e|ed|ing)|recommend(?:ed|ing)?)\b",
    re.IGNORECASE,
)
_STATUS_EVIDENCE = {
    "investigated": re.compile(
        r"\b(?:analy[sz](?:e|ed|ing)|audit(?:ed|ing)?|explor(?:e|ed|ing)|"
        r"inspect(?:ed|ing)?|investigat(?:e|ed|ing)|looked into|research(?:ed|ing)?|"
        r"review(?:ed|ing)?|traced?)\b",
        re.IGNORECASE,
    ),
    "answered": re.compile(
        r"\b(?:answer(?:ed|ing)?|clarif(?:y|ied|ying)|describ(?:e|ed|ing)|"
        r"determin(?:e|ed|ing)|explain(?:ed|ing)?|found|identified|show(?:ed|ing)?)\b|"
        r"\bhere (?:are|is)\b",
        re.IGNORECASE,
    ),
    "proposed": re.compile(
        r"\b(?:plan(?:ned|ning)?|propos(?:e|ed|ing)|recommend(?:ed|ing)?|"
        r"suggest(?:ed|ing)?|next steps?|could|should)\b",
        re.IGNORECASE,
    ),
    "verified": re.compile(
        r"\b(?:check(?:ed|ing)?|confirm(?:ed|ing)?|pass(?:ed|ing)?|test(?:ed|ing)?|"
        r"validat(?:e|ed|ing)|verif(?:y|ied|ying))\b",
        re.IGNORECASE,
    ),
    "blocked": re.compile(
        r"\b(?:blocked|cannot until|can't until|need(?:ed|s)? (?:input|permission)|"
        r"waiting for)\b",
        re.IGNORECASE,
    ),
    "failed": re.compile(
        r"\b(?:could not|couldn't|error|fail(?:ed|ure)?|problem|unable|unsuccessful)\b",
        re.IGNORECASE,
    ),
}
_NEGATED_STATUS_ACTION = re.compile(
    r"\b(?:could not|couldn't|did not|didn't|failed to|never|not|unable to)\s+"
    r"(?:analy[sz](?:e|ed)|answer(?:ed)?|audit(?:ed)?|check(?:ed)?|clarif(?:y|ied)|"
    r"confirm(?:ed)?|describ(?:e|ed)|determin(?:e|ed)|explain(?:ed)?|explor(?:e|ed)|"
    r"inspect(?:ed)?|investigat(?:e|ed)|pass(?:ed)?|propos(?:e|ed)|recommend(?:ed)?|"
    r"research(?:ed)?|review(?:ed)?|suggest(?:ed)?|test(?:ed)?|trac(?:e|ed)|"
    r"validat(?:e|ed)|verif(?:y|ied))\b",
    re.IGNORECASE,
)
_NOT_BLOCKED = re.compile(r"\b(?:not|never|no longer) blocked\b|\bunblocked\b",
                          re.IGNORECASE)
_NOT_FAILED = re.compile(
    r"\b(?:no|without) (?:errors?|failures?|problems?)\b|"
    r"\b(?:did not|didn't|never) fail(?:ed)?\b|\b(?:succeeded|successful)\b",
    re.IGNORECASE,
)


def normalize(value):
    """Collapse whitespace for robust verbatim checks and spoken output."""
    return " ".join(value.split()) if isinstance(value, str) else ""


def occurs_in(source, candidate):
    source = normalize(source).casefold()
    candidate = normalize(candidate).casefold()
    return bool(candidate) and candidate in source


def parse_assessment(raw):
    """Decode plain or fenced JSON, tolerating a short model preamble."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        value = json.loads(raw)
    except ValueError:
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            value = json.loads(raw[start:end + 1])
        except ValueError:
            return None
    return value if isinstance(value, dict) else None


def reply_from_hook(raw, limit=2600):
    """Return the authoritative Stop reply, preserving head and conclusion."""
    try:
        hook = json.loads(raw)
    except ValueError:
        return ""
    reply = hook.get("last_assistant_message", "")
    if not isinstance(reply, str):
        return ""
    reply = reply.strip()
    if len(reply) <= limit:
        return reply
    head = limit // 2
    tail = limit - head
    return reply[:head] + "\n[...middle omitted...]\n" + reply[-tail:]


def safe_topic(source, candidate):
    """Return a short extractive topic or a deterministic generic fallback."""
    candidate = normalize(candidate).strip(" \t\r\n\"'`.,:;!?-–—")
    if not occurs_in(source, candidate):
        return "the request"
    words = candidate.split()
    if not words or len(words) > 8 or len(candidate) > 90:
        return "the request"
    # Keep a generated topic from smuggling a second completion claim into an
    # otherwise neutral template. These forms are safe to lose conservatively.
    if re.search(rf"\b(?:{_CHANGE_VERBS})\b", candidate, re.IGNORECASE):
        return "the request"
    return candidate


def supported_change(evidence):
    return bool(
        _EXPLICIT_CHANGE.search(evidence)
        and not _NEGATION_OR_UNCERTAINTY.search(evidence)
    )


def supported_status(status, evidence):
    if status == "changed":
        return supported_change(evidence)
    pattern = _STATUS_EVIDENCE.get(status)
    if pattern is not None and not pattern.search(evidence):
        return False
    if status in {"investigated", "answered", "proposed", "verified"}:
        return not _NEGATED_STATUS_ACTION.search(evidence)
    if status == "blocked":
        return not _NOT_BLOCKED.search(evidence)
    if status == "failed":
        return not _NOT_FAILED.search(evidence)
    return True


def render(source, assessment, force_neutral=False):
    """Render from validated fields; return empty only for malformed JSON."""
    if not isinstance(assessment, dict):
        return ""

    status = normalize(assessment.get("status", "")).lower()
    evidence = normalize(assessment.get("evidence", ""))
    topic = safe_topic(source, assessment.get("topic", ""))

    if status not in STATUSES:
        status = "unknown"
    if force_neutral:
        status = "unknown"
    elif status != "unknown" and not occurs_in(source, evidence):
        status = "unknown"
    elif not supported_status(status, evidence):
        status = "unknown"

    templates = {
        "changed": "Claude made changes to {topic}.",
        "investigated": "Claude investigated {topic}.",
        "answered": "Claude explained {topic}.",
        "proposed": "Claude proposed next steps for {topic}.",
        "verified": "Claude verified {topic}.",
        "blocked": "Claude was blocked on {topic}.",
        "failed": "Claude encountered a problem with {topic}.",
        "unknown": "Claude worked on {topic}.",
    }
    return templates[status].format(topic=topic)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("source", nargs="?", help="assistant reply used as grounding")
    parser.add_argument("--force-neutral", action="store_true")
    parser.add_argument("--hook-reply", action="store_true",
                        help="extract a bounded authoritative reply from hook JSON")
    args = parser.parse_args(argv)
    if args.hook_reply:
        sys.stdout.write(reply_from_hook(sys.stdin.read()))
        return 0
    if args.source is None:
        parser.error("source is required unless --hook-reply is used")
    assessment = parse_assessment(sys.stdin.read())
    sentence = render(args.source, assessment, args.force_neutral)
    if sentence:
        sys.stdout.write(sentence)
    return 0


if __name__ == "__main__":
    sys.exit(main())
