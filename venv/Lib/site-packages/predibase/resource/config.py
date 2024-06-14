from dataclasses import dataclass, field
from typing import Any, Dict

import yaml
from dataclasses_json import dataclass_json, LetterCase


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class ConfigSuggestion:
    """Describes a ludwig configuration suggestion."""

    # Why this configuration is useful or interesting to try.
    description: str = ""

    # The raw ludwig config, without backend or execution-specific parameters.
    config: Dict[str, Any] = field(default_factory=dict)

    # The model category this config is designed for, i.e. TABULAR, IMAGE, TEXT, TEXT_TABULAR, MULTI_MODAL, etc, largely
    # describes the nature of the model's input features.
    model_category: str = "UNKNOWN"

    # Whether the config includes a hyperopt section, and should run a hyperparameter search.
    contains_hyperopt: bool = False

    # Whether the config uses a pretrained model.
    uses_pretrained_model: bool = False

    def __repr__(self) -> str:
        return yaml.dump(self.to_dict())
