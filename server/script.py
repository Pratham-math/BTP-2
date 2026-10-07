"""Canonical lesson schema; legacy scripts may omit visual plans."""

from pydantic import BaseModel, ConfigDict, Field, field_validator
from server.visuals import VisualSpec


class Scene(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=3, max_length=60)
    bullets: list[str] = Field(min_length=1, max_length=3)
    narration: str = Field(min_length=120, max_length=900)
    # Older saved scripts have no visual and still use the Pillow path on retry.
    visual: VisualSpec | None = None

    @field_validator("bullets")
    @classmethod
    def check_bullets(cls, bullets: list[str]) -> list[str]:
        if any(not bullet.strip() or len(bullet) > 100 for bullet in bullets):
            raise ValueError("Each bullet must contain 1 to 100 characters")
        return bullets

    @field_validator("narration")
    @classmethod
    def check_narration_words(cls, narration: str) -> str:
        count = len(narration.split())
        if not 35 <= count <= 110:
            raise ValueError("Narration must contain 35 to 110 words")
        return narration


class VideoScript(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=3, max_length=70)
    scenes: list[Scene] = Field(min_length=3, max_length=3)


class AnimatedScene(Scene):
    visual: VisualSpec


class AnimatedVideoScript(VideoScript):
    scenes: list[AnimatedScene] = Field(min_length=3, max_length=3)


