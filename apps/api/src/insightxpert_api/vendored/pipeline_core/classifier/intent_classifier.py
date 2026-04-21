"""Rule-based intent classification for Text-to-SQL questions.

Classifies natural-language questions into one or more intent categories
so that only the relevant SQL generation rules are injected into the prompt.
This eliminates contradictions between rules designed for different query types.
"""
from __future__ import annotations

import re
import logging

logger = logging.getLogger(__name__)

# All recognised intent labels.
ALL_INTENTS: frozenset[str] = frozenset({
    "date_time",
    "ranking",
    "aggregation",
    "comparison",
    "math",
    "categorical",
    "existence",
    "listing",
})

# Intent -> list of compiled regex patterns.  A question matches an intent
# if *any* pattern in the list fires on the lowercased question+evidence text.
_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "date_time": [
        re.compile(r"\b(year|month|date|day|week|when|after|before|since|during|between)\b"),
        re.compile(r"\b(19|20)\d{2}s?\b"),          # 4-digit years / decades
        re.compile(r"\b(oldest|newest|earliest|latest|recent)\b"),
        re.compile(r"\b(quarter|semester|season)\b"),
        re.compile(r"\b(time|lap\s*time|duration)\b"),
        re.compile(r"\d+:\d+"),                       # time patterns like "0:01:27"
        re.compile(r"\b(age|born|birthday)\b"),
    ],
    "ranking": [
        re.compile(r"\b(highest|lowest|top|bottom|most|least|best|worst|largest|smallest|greatest|fewest)\b"),
        re.compile(r"\b(rank|ranking|ranked)\b"),
        re.compile(r"\b(maximum|minimum|max|min)\b"),
        re.compile(r"\btop\s*\d+\b"),                # "top 5", "top 10"
        re.compile(r"\b(youngest|oldest|tallest|shortest|heaviest|lightest|richest|poorest)\b"),
        re.compile(r"\b(higher|lower|bigger|smaller|longer|shorter|faster|slower)\b"),
    ],
    "aggregation": [
        re.compile(r"\b(average|avg|total|sum|count|how\s+many|number\s+of)\b"),
        re.compile(r"\b(mean|median|aggregate)\b"),
        re.compile(r"\b(tally|tallied)\b"),
    ],
    "comparison": [
        re.compile(r"\b(more\s+than|less\s+than|greater\s+than|fewer\s+than)\b"),
        re.compile(r"\bhow\s+many\s+times\s+(more|less|as)\b"),
        re.compile(r"\b(ratio|compared\s+to|versus|vs)\b"),
        re.compile(r"\b(exceed|surpass|outperform)\b"),
        re.compile(r"\b(difference\s+between|differ)\b"),
    ],
    "math": [
        re.compile(r"\b(percentage|percent)\b"),
        re.compile(r"%"),
        re.compile(r"\b(rate|proportion|fraction)\b"),
        re.compile(r"\b(increase|decrease|growth|decline|change)\b"),
        re.compile(r"\bper\s+(unit|capita|person|student|game|match|order)\b"),
        re.compile(r"\bhow\s+old\b"),                 # age calculation
    ],
    "categorical": [
        re.compile(r"\b(named|called|titled|labeled|labelled)\b"),
        re.compile(r"\b(type\s+is|type\s+of|category|genre|status\s+is|status\s+of)\b"),
        re.compile(r"\b(whose\s+name|with\s+the\s+name)\b"),
        re.compile(r"""['"][A-Z]"""),                  # quoted proper nouns hint at exact match
        re.compile(r"\bof\s+type\b"),                  # "of type Creature"
        re.compile(r"\bin\s+(french|english|german|spanish|japanese|chinese|korean)\b"),  # language filters
        re.compile(r"\bnationality\s+in\b"),
    ],
    "existence": [
        re.compile(r"\b(is\s+there|are\s+there|does\s+.+\s+have|do\s+.+\s+have)\b"),
        re.compile(r"\b(yes\s+or\s+no|true\s+or\s+false)\b"),
        re.compile(r"\b(if\s+any|if\s+available|whether)\b"),
        re.compile(r"\b(without\s+any|missing|absent|lack)\b"),
        re.compile(r"\bdid\s+.+\s+(attend|appear|play|participate|win|lose|enter|join)\b"),
        re.compile(r"\bdoesn'?t\s+have\b"),
    ],
    "listing": [
        re.compile(r"\b(list\s+all|list\s+the|list\s+every|show\s+all|show\s+the|show\s+every)\b"),
        re.compile(r"\b(which\s+\w+\s+are|which\s+\w+\s+were|which\s+\w+\s+have)\b"),
        re.compile(r"\b(all\s+\w+\s+that|all\s+\w+\s+who|all\s+\w+\s+which)\b"),
        re.compile(r"\b(give\s+me\s+all|find\s+all|name\s+all|identify\s+all)\b"),
        re.compile(r"\b(list\s+out|state\s+all|state\s+the)\b"),
        re.compile(r"\bwhat\s+(elements|items|tags|things)\s+(are|were)\b"),
    ],
}


class IntentClassifier:
    """Deterministic, regex-based multi-label intent classifier."""

    ALL_INTENTS = ALL_INTENTS

    def classify(self, question: str, evidence: str = "") -> set[str]:
        """Return the set of intent labels that apply to the question.

        If no patterns match, returns an empty set.  The caller should
        treat an empty set as "use all rules" (safe fallback).
        """
        text = f"{question} {evidence}".lower()
        intents: set[str] = set()
        for intent, patterns in _PATTERNS.items():
            if any(p.search(text) for p in patterns):
                intents.add(intent)
        logger.debug("Intent classification for %r: %s", question[:80], intents or "ALL (fallback)")
        return intents
