from __future__ import annotations

from pydantic import BaseModel, PositiveInt, Field, AliasPath


class Adapter(BaseModel):
    repo: str
    tag: PositiveInt
    base_model: str = Field(validation_alias="baseModel")
    description: str | None = Field(default=None)
    artifact_path: str | None = Field(validation_alias="adapterPath", default=None)
    finetuning_error: str | None = Field(validation_alias=AliasPath("finetuningJob", "error"), default=None)
    finetuning_job_uuid: str | None = Field(validation_alias=AliasPath("finetuningJob", "uuid"), default=None)

    @property
    def name(self) -> str:
        return f"{self.repo}/{self.tag}"
