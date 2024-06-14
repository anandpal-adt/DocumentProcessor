import copy
import os
from dataclasses import dataclass, field
from typing import Optional, Tuple, Union

import yaml
from tabulate import tabulate

from predibase.resource import model as mdl
from predibase.resource.dataset import Dataset
from predibase.resource.llm import interface

_PATH_HERE = os.path.abspath(os.path.dirname(__file__))
_TEMPLATE_DIR = os.path.join(_PATH_HERE, "templates")
_CONFIG_FILENAME = "config.yaml"

LLM_FINETUNE_TEMPLATES_INFO = {}


@dataclass
class FinetuneTemplate:
    llm: "interface.HuggingFaceLLM"
    filename: str
    _meta: Optional[dict] = field(default=None, init=False)
    _raw_template_str: Optional[str] = field(default=None, init=False)
    _cfg: Optional[dict] = field(default=None, init=False)

    @property
    def name(self) -> str:
        if self._meta is None:
            self._load()
        return self._meta["name"]

    @property
    def description(self) -> str:
        if self._meta is None:
            self._load()
        return self._meta["description"]

    def run(
        self,
        prompt_template: str,
        target: str,
        dataset: Optional[Union[str, Dataset]] = None,
        repo: Optional[str] = None,
        epochs: Optional[int] = None,
        train_steps: Optional[int] = None,
        learning_rate: Optional[float] = None,
    ) -> "mdl.ModelFuture":
        return self.llm.finetune(
            dataset=dataset,
            config=self.to_config(prompt_template, target),
            repo=repo,
            epochs=epochs,
            train_steps=train_steps,
            learning_rate=learning_rate,
        )

    def to_config(
        self,
        prompt_template: str = "__PROMPT_TEMPLATE_PLACEHOLDER__",
        target: str = "__TARGET_PLACEHOLDER__",
    ) -> dict:
        if self._cfg is None:
            self._cfg = yaml.safe_load(
                self._raw_template_str.format(
                    base_model=self.llm.model_name,
                    prompt_template=prompt_template,
                    target=target,
                ),
            )
            del self._cfg["template_meta"]

        return copy.deepcopy(self._cfg)

    def _load(self):
        with open(os.path.join(_TEMPLATE_DIR, self.filename)) as f:
            self._raw_template_str = f.read()

        self._meta = yaml.safe_load(self._raw_template_str)["template_meta"]


class FinetuneTemplateCollection(dict):
    def __init__(self, llm: "interface.HuggingFaceLLM"):
        super().__init__()

        self.llm = llm
        for filename in os.listdir(_TEMPLATE_DIR):
            if not filename.endswith(".yaml"):
                continue

            if filename == _CONFIG_FILENAME:
                with open(os.path.join(_TEMPLATE_DIR, _CONFIG_FILENAME)) as config_file:
                    self._config = yaml.safe_load(config_file)
            else:
                tmpl = FinetuneTemplate(llm, os.path.join(_TEMPLATE_DIR, filename))
                self[tmpl.name] = tmpl

    @property
    def default(self) -> FinetuneTemplate:
        default_name = self._config.get("default", "")
        tmpl = self.get(default_name, None)
        if tmpl is None:
            raise RuntimeError(f"the default template '{default_name}' was not found")

        return tmpl

    def compare(self):
        print(self)

    def __str__(self):
        def make_row(key) -> Tuple[str, str, str]:
            tmpl = self[key]
            default_indicator = "------>" if tmpl.name == self._config["default"] else ""
            return default_indicator, key, tmpl.description

        return tabulate(
            (make_row(k) for k in sorted(self.keys())),
            tablefmt="simple_grid",
            headers=["Default", "Name", "Description"],
            colalign=["center"],
        )
