from pydantic import BaseModel, ConfigDict, field_validator


class ResearchBrief(BaseModel):
    """Human-authored research brief (D-2 §5)."""

    model_config = ConfigDict(str_strip_whitespace=False)

    thesis: str
    title_suggestion: str | None = None
    outline: list[str] | None = None
    key_references: list[str] | None = None
    constraints: str | None = None
    target_venue: str | None = None
    domain: str | None = None

    @field_validator("thesis")
    @classmethod
    def thesis_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("thesis must be non-empty")
        if len(v) > 10_000:
            raise ValueError("thesis exceeds 10_000 character limit")
        return v

    @field_validator("key_references")
    @classmethod
    def refs_not_empty(cls, v: list[str] | None) -> list[str] | None:
        if v is not None:
            for ref in v:
                if not ref.strip():
                    raise ValueError("key_references items must be non-empty strings")
        return v
