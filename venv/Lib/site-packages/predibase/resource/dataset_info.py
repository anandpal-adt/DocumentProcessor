from dataclasses import dataclass, field
from typing import List

from dataclasses_json import config, dataclass_json, LetterCase

# Copied from https://github.com/ludwig-ai/ludwig/blob/master/ludwig/automl/base_config.py


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class FieldInfo:
    name: str
    dtype: str
    key: str = None
    distinct_values: List = None
    distinct_values_balance: float = 1.0
    num_distinct_values: int = 0
    nonnull_values: int = 0
    image_values: int = 0
    audio_values: int = 0
    avg_words: int = None


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class DatasetInfo:
    fields: List[FieldInfo]
    row_count: int
    size_bytes: int = -1


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class DatasetInfoWrapper:
    dataset_id: int = field(metadata=config(field_name="datasetID"))
    info: DatasetInfo = field(metadata=config(field_name="info"))
