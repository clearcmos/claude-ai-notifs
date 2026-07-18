#!/usr/bin/env python3
"""Validate a model assessment and render a conservative announcement.

The model is allowed to classify and extract, but it never writes the final
sentence. Evidence must occur in the assistant reply; topic text may occur in
the latest user request or reply. Invalid or unsupported assessments are
downgraded to neutral wording. Stdlib only.
"""

import argparse
import json
import re
import sys


STATUSES = {
    "changed",
    "investigated",
    "answered",
    "produced",
    "proposed",
    "verified",
    "waiting",
    "recapped",
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
    "waiting": re.compile(
        r"\b(?:await(?:ed|ing)?|depend(?:s|ed|ing)?|pending|until|"
        r"wait(?:ed|ing)?|when|once)\b",
        re.IGNORECASE,
    ),
}
# "produced" renders a creation claim ("produced the requested X"), so it gets
# the same deterministic treatment as "changed", keyed on the other input: the
# latest request must itself ask for content. The gate demands positive
# request grammar - the content verb or noun must be governed by an imperative
# or directive construction. Global content vocabulary combined with negative
# question detection was bypassable from both sides ("Can you explain how this
# generates a summary?" carried a directive marker that overrode question
# detection; "Explain..." was never a question). With positive grammar, any
# phrasing the regex fails to recognize downgrades to neutral "worked on"
# wording: evasions fail safe, never toward a creation claim.
#
# Base verb forms only: imperatives and to-infinitives. Third-person forms
# ("generates", "writes") describe existing behavior, never a directive, and
# were exactly the observed bypass vector.
_CONTENT_VERB = (
    r"(?:write|draft|compose|generate|summari[sz]e|translate|rewrite|"
    r"rephrase|reword|redraft|outline|brainstorm|condense|caption|"
    r"come\s+up\s+with|make\s+up|make\s+(?:me\s+)?(?:some|something))"
)
_CONTENT_NOUN = (
    r"(?:summar(?:y|ies)|poem|haiku|limerick|sonnet|slogan|tagline|lyrics|"
    r"blurb|translation|outline|draft|caption)"
)
_ARTICLE_GAP = r"(?:(?:a|an|the|some)\s+)?(?:[\w'-]+\s+){0,2}"
# Bare imperatives count ONLY at true line starts (^ under MULTILINE, with
# an optional bullet marker requiring trailing whitespace and an optional
# opening quote). Sentence punctuation is deliberately NOT a boundary:
# colon-introduced quotations ('the docs say: "generate a summary"') read as
# imperatives under any sentence-boundary rule (external review, rounds three
# and four). The cost is that "Thanks. Write a summary." falls to neutral
# wording, the direction this validator prefers. A standalone quoted phrase
# as the whole request remains irreducibly ambiguous between a request and a
# mention; it is accepted as a request by documented choice.
_IMPERATIVE_CONTENT = re.compile(
    r"^(?:[-*>]\s+)?[\"']?(?:please\s+)?(?:just\s+)?"
    + _CONTENT_VERB + r"\b",
    re.IGNORECASE | re.MULTILINE,
)
_DIRECTED_CONTENT = re.compile(
    r"\b(?:can|could|will|would)\s+you\s+(?:please\s+)?"
    + _CONTENT_VERB + r"\b"
    r"|\b(?:i|we)(?:'d\s+like|\s+would\s+like|\s+want|\s+need)\s+"
    r"(?:you\s+to\s+|to\s+)?" + _CONTENT_VERB + r"\b"
    r"|\b(?:give|send|make|get)\s+me\s+" + _ARTICLE_GAP + _CONTENT_NOUN + r"\b"
    r"|\b(?:i|we)(?:'d\s+like|\s+would\s+like|\s+want|\s+need)\s+"
    + _ARTICLE_GAP + _CONTENT_NOUN + r"\b"
    r"|\bcan\s+i\s+(?:get|have)\s+" + _ARTICLE_GAP + _CONTENT_NOUN + r"\b",
    re.IGNORECASE,
)


def content_request(request):
    """True when the latest request itself asks for content to be produced."""
    if not isinstance(request, str):
        return False
    # Collapse horizontal whitespace but keep line breaks: flattening
    # newlines (as normalize does) would erase the very boundaries that make
    # bullet and quote prefixes trustworthy.
    text = "\n".join(" ".join(line.split()) for line in request.splitlines())
    return bool(
        _IMPERATIVE_CONTENT.search(text) or _DIRECTED_CONTENT.search(text)
    )
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
_NOT_WAITING = re.compile(
    r"\b(?:not|no longer) (?:awaiting|pending|waiting)\b|\bdoes not depend\b",
    re.IGNORECASE,
)


def normalize(value):
    """Collapse whitespace for robust verbatim checks and spoken output."""
    return " ".join(value.split()) if isinstance(value, str) else ""


def occurs_in(source, candidate):
    source = normalize(source).casefold()
    candidate = normalize(candidate).casefold()
    return bool(candidate) and candidate in source


def evidence_occurs_in(source, candidate):
    """Accept an exact quote or ordered exact fragments separated by ellipses."""
    if occurs_in(source, candidate):
        return True
    source = normalize(source).casefold()
    fragments = [
        normalize(part).casefold()
        for part in re.split(r"(?:\.{3,}|…)", candidate)
        if normalize(part)
    ]
    if not fragments:
        return False
    position = 0
    for fragment in fragments:
        # Tiny fragments such as punctuation around an ellipsis prove nothing.
        if len(fragment) < 4:
            continue
        found = source.find(fragment, position)
        if found < 0:
            return False
        position = found + len(fragment)
    return position > 0


def topic_occurs_in(source, candidate):
    """Allow a short extractive topic to reorder words already in the reply."""
    if occurs_in(source, candidate):
        return True
    stopwords = {
        "a", "an", "and", "about", "for", "from", "in", "of", "on", "or",
        "the", "to", "with",
    }
    token_pattern = r"[a-z0-9]+(?:[._/+-][a-z0-9]+)*"
    source_tokens = set(re.findall(token_pattern, source.casefold()))
    topic_tokens = {
        token for token in re.findall(token_pattern, candidate.casefold())
        if token not in stopwords
    }
    return bool(topic_tokens) and topic_tokens.issubset(source_tokens)


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


def safe_topic(sources, candidate):
    """Return a short extractive topic or a deterministic generic fallback."""
    candidate = normalize(candidate).strip(" \t\r\n\"'`.,:;!?-–—")
    generic = re.sub(r"^(?:a|an|the)\s+", "", candidate.casefold())
    if generic in {"issue", "reply", "request", "response", "task", "work"}:
        return "the request"
    if isinstance(sources, str):
        sources = (sources,)
    if not any(
        topic_occurs_in(source, candidate) for source in sources if source
    ):
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
    if status == "waiting":
        return bool(
            _STATUS_EVIDENCE["waiting"].search(evidence)
            and not _NOT_WAITING.search(evidence)
        )
    if status in {
        "investigated", "answered", "produced", "proposed", "verified",
        "recapped",
    }:
        # These do not assert that the user's requested mutation happened. Let
        # the constrained classifier distinguish them as long as its evidence
        # is grounded and does not explicitly negate the classified action.
        return not _NEGATED_STATUS_ACTION.search(evidence)
    pattern = _STATUS_EVIDENCE.get(status)
    if pattern is not None and not pattern.search(evidence):
        return False
    if status == "blocked":
        return not _NOT_BLOCKED.search(evidence)
    if status == "failed":
        return not _NOT_FAILED.search(evidence)
    return True


def render(source, assessment, force_neutral=False, topic_source=None):
    """Render from validated fields; return empty only for malformed JSON."""
    if not isinstance(assessment, dict):
        return ""

    status = normalize(assessment.get("status", "")).lower()
    evidence = normalize(assessment.get("evidence", ""))
    topic = safe_topic((topic_source, source), assessment.get("topic", ""))

    if status not in STATUSES:
        status = "unknown"
    if force_neutral:
        status = "unknown"
    elif status != "unknown" and not evidence_occurs_in(source, evidence):
        status = "unknown"
    elif not supported_status(status, evidence):
        status = "unknown"
    elif status == "produced" and not content_request(topic_source):
        # Reply evidence cannot distinguish supplied content from explanation,
        # so the request must establish that content was asked for at all.
        status = "unknown"

    # The voice's only possible speaker is this assistant, so templates never
    # name it (a real 2026-07-17 user preference): verb-first status readouts.
    templates = {
        "changed": "Made changes to {topic}.",
        "investigated": "Investigated {topic}.",
        "answered": "Explained {topic}.",
        "produced": "Produced the requested {topic}.",
        "proposed": "Proposed next steps for {topic}.",
        "verified": "Verified {topic}.",
        "waiting": "Waiting on {topic}.",
        "recapped": "Recapped {topic}.",
        "blocked": "Blocked on {topic}.",
        "failed": "Encountered a problem with {topic}.",
        "unknown": "Worked on {topic}.",
    }
    if status == "produced" and topic == "the request":
        return "Produced the requested content."
    if status == "waiting" and topic == "the request":
        return "Waiting for the next step."
    if status == "recapped" and topic == "the request":
        return "Recapped the current state."
    return templates[status].format(topic=topic)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("source", nargs="?", help="assistant reply used as grounding")
    parser.add_argument("--force-neutral", action="store_true")
    parser.add_argument("--topic-source",
                        help="latest user request used only to ground the topic")
    parser.add_argument("--hook-reply", action="store_true",
                        help="extract a bounded authoritative reply from hook JSON")
    args = parser.parse_args(argv)
    if args.hook_reply:
        sys.stdout.write(reply_from_hook(sys.stdin.read()))
        return 0
    if args.source is None:
        parser.error("source is required unless --hook-reply is used")
    assessment = parse_assessment(sys.stdin.read())
    sentence = render(args.source, assessment, args.force_neutral, args.topic_source)
    if sentence:
        sys.stdout.write(sentence)
    return 0


if __name__ == "__main__":
    sys.exit(main())
