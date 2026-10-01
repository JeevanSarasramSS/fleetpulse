"""Copilot guardrails: prompt-injection screening and output grounding. Pure functions (unit-tested)."""
import re

INJECTION = re.compile(
    r"(ignore (all |any )?(previous|prior|above) (instructions|rules)|system prompt|you are now|"
    r"developer mode|disregard .*instructions|reveal .*(secret|key|password)|drop table|delete from|"
    r";\s*--|other tenant|all tenants)", re.I)
VIN_IN_TEXT = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b", re.I)


def screen(question: str) -> str | None:
    """Return a refusal reason, or None if the question may proceed."""
    if INJECTION.search(question):
        return "The request looks like an attempt to override safety rules or reach other tenants' data."
    if len(question) > 500:
        return "Question too long."
    return None


def vins_in(text: str) -> list[str]:
    return [v.upper() for v in VIN_IN_TEXT.findall(text)]


def grounded(answer: str, allowed_vins: set[str]) -> bool:
    """Every VIN the answer mentions must come from tool results (no hallucinated vehicles)."""
    return all(v in allowed_vins for v in vins_in(answer))
