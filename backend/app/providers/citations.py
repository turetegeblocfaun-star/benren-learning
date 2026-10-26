from __future__ import annotations

import re

# Only remove groups made entirely of source aliases. Keep ordinary parenthetic
# explanations such as (Part) and scientific notation such as (O2).
_CITATION_GROUP = re.compile(
    r"[（(\[【]\s*(?:来源|依据|sources?|refs?)?\s*[:：]?\s*"
    r"(S[1-9]\d*(?:\s*[,，、;；]\s*S[1-9]\d*)*)\s*[）)\]】]",
    re.IGNORECASE,
)
_SOURCE_ALIAS = re.compile(r"(?<![A-Za-z0-9_])S[1-9]\d*(?![A-Za-z0-9_])", re.IGNORECASE)


def clean_tutor_citations(message: str) -> tuple[str, list[str]]:
    aliases: list[str] = []

    def remove(match: re.Match[str]) -> str:
        aliases.extend(alias.upper() for alias in _SOURCE_ALIAS.findall(match.group(1)))
        return ""

    cleaned = _CITATION_GROUP.sub(remove, message)

    # Alias-only citations must not appear in learner-facing prose. Retain a
    # readable reference phrase if the model put a known citation inline.
    def inline(match: re.Match[str]) -> str:
        aliases.append(match.group(0).upper())
        return "所引材料"

    cleaned = _SOURCE_ALIAS.sub(inline, cleaned)
    cleaned = re.sub(r"[ \t]+([，。；！？,.!?;])", r"\1", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()
    return cleaned, list(dict.fromkeys(aliases))
