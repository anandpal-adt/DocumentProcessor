from __future__ import annotations

from pydantic import BaseModel, Field


class Repo(BaseModel):
    uuid: str
    name: str
    description: str | None = Field(default=None)
