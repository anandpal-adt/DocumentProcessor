from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, AliasPath, GetCoreSchemaHandler, PositiveInt
from pydantic_core import CoreSchema, core_schema, from_json, to_json


class FinetuningJobParams(BaseModel):
    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: Any, handler: GetCoreSchemaHandler) -> CoreSchema:

        validate = core_schema.no_info_plain_validator_function(cls.load_as_json)

        return core_schema.json_or_python_schema(
            json_schema=validate,
            python_schema=validate,
            serialization=core_schema.plain_serializer_function_ser_schema(lambda x: to_json(x)),
        )

    @classmethod
    def load_as_json(cls, value: Any):
        if isinstance(value, str):
            return from_json(value)
        return value


class FinetuningJob(BaseModel):
    uuid: str
    base_model: str = Field(validation_alias="baseModel")
    dataset: str = Field(validation_alias="datasetName")
    description: str | None = Field(default=None)
    target_repo: str = Field(validation_alias="targetRepoName")
    target_version_tag: PositiveInt = Field(validation_alias="targetVersionTag")
    accelerator: str = Field(validation_alias=AliasPath("accelerator", "id"))
    status: str
    params: dict
    # duration TODO needs calc


class _FinetuningMetricsData(BaseModel):
    batch_size: int | None = Field(default=None)
    best_eval_metric_checkpoint_number: int | None = Field(default=None)
    best_eval_metric_epoch: int | None = Field(default=None)
    best_eval_metric_steps: int | None = Field(default=None)
    best_train_metrics_loss: float | None = Field(default=None)
    best_valid_metric: float | None = Field(default=None)
    best_validation_metrics_loss: float | None = Field(default=None)
    checkpoint_number: int | None = Field(default=None)
    epoch: int | None = Field(default=None)
    last_improvement_steps: int | None = Field(default=None)
    learning_rate: float | None = Field(default=None)
    steps: int | None = Field(default=None)
    total_tokens_used: int | None = Field(default=None)
    train_metrics_loss: float | None = Field(default=None)
    validation_metrics_loss: float | None = Field(default=None)


class _FinetuningMetricsMeta(BaseModel):
    is_completed: bool
    job_uuid: str = Field(validation_alias="model_uuid")
    run_id: str
    steps: int
    steps_per_epoch: int
    total_steps: int


class _FinetuningMetrics(BaseModel):
    data: _FinetuningMetricsData
    meta: _FinetuningMetricsMeta
