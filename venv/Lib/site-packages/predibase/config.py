from __future__ import annotations

from pydantic import BaseModel, Field, PositiveFloat, PositiveInt


class FinetuningConfig(BaseModel):
    base_model: str
    task: str | None = Field(default=None)
    epochs: PositiveInt | None = Field(default=None)
    learning_rate: PositiveFloat | None = Field(default=None)
    rank: PositiveInt | None = Field(default=None)
    target_modules: list[str] | None = Field(default=None)


class DeploymentConfig(BaseModel):
    base_model: str
    accelerator: str | None = Field(default=None)
    cooldown_time: PositiveInt | None = Field(default=None)
    hf_token: str | None = Field(default=None)
