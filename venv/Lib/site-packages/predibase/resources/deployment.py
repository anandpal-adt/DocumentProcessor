from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, AliasPath, ConfigDict, NonNegativeInt

if TYPE_CHECKING:
    pass


class DeploymentArgs(BaseModel):
    model_config = ConfigDict(extra="allow")


class Deployment(BaseModel):
    name: str
    uuid: str
    description: str | None
    type: str
    status: str
    cooldown_time: NonNegativeInt | None = Field(validation_alias="cooldownTime")
    context_window: NonNegativeInt = Field(validation_alias=AliasPath("model", "maxInputLength"))
    accelerator: str = Field(validation_alias=AliasPath("accelerator", "id"))
    model: str = Field(validation_alias=AliasPath("model", "name"))
