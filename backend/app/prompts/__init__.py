from __future__ import annotations

from importlib.resources import files


def load_prompt(name: str) -> str:
    return files("app.prompts").joinpath(name).read_text(encoding="utf-8")
