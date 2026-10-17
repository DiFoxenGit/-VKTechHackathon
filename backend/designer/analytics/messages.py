"""Localized explanations are data files; stable codes form the API."""
import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=2)
def _catalog(locale):
    if locale not in {"ru", "en"}:
        raise ValueError("unsupported locale")
    return json.loads((Path(__file__).parent / "locales" / f"{locale}.json").read_text(encoding="utf-8"))


def message(code, locale="ru", **params):
    if locale == "ru":
        class RussianNumber(float):
            def __format__(self, spec):
                return super().__format__(spec).replace(".", ",")
        params = {k: RussianNumber(v) if isinstance(v, float) else v for k, v in params.items()}
    return _catalog(locale)[code].format(**params)


def explain(notice, locale="ru"):
    return message(notice.code, locale, **notice.params)
