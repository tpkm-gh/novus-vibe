from .base import ReflectionOutcome, ReflectionProvider, ReflectionVerdict
from .llm_reflection import LLMReflectionProvider
from .rule_based import RuleBasedReflectionProvider


def get_reflection_provider(name: str) -> ReflectionProvider:
    if name == "llm":
        return LLMReflectionProvider()
    return RuleBasedReflectionProvider()


__all__ = [
    "ReflectionOutcome",
    "ReflectionProvider",
    "ReflectionVerdict",
    "LLMReflectionProvider",
    "RuleBasedReflectionProvider",
    "get_reflection_provider",
]
