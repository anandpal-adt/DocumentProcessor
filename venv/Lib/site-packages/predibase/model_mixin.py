import copy
from concurrent.futures import as_completed, ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Union

import pandas as pd

from predibase.pql.api import ServerResponseError
from predibase.resource import model as mdl
from predibase.resource.config import ConfigSuggestion
from predibase.resource.dataset import Dataset
from predibase.resource.engine import Engine, EngineTemplate
from predibase.util import ConfigEncoder, get_url, load_yaml, log_info
from predibase.util.url import encode_url_param


class ModelMixin:
    def list_model_repos(
        self,
        name: str = None,
        description: str = None,
        df: bool = False,
        limit: Optional[int] = 999999,
    ) -> Union[pd.DataFrame, List["mdl.ModelRepo"]]:
        """
        :param name: Filter by name
        :param description: Filter by description
        :param df: Whether to return pandas dataframe or list of objects
        :param limit: max number of model repos to return
        :return: Pandas dataframe or list of model repos
        """
        endpoint = f"/models?limit={limit}"
        if name:
            endpoint += f"&searchKeys[]=modelName&searchVals[]={name}"
        if description:
            endpoint += f"&searchKeys[]=description&searchVals[]={description}"
        resp = self.session.get_json(endpoint)
        if df:
            return pd.DataFrame([m for m in resp["modelRepos"]])
        from predibase.resource_util import build_model_repo

        return [build_model_repo(m, self.session) for m in resp["modelRepos"]]

    def get_model_repo(self, name: str) -> mdl.ModelRepo:
        return mdl.get_model_repo(self.session, name)

    def create_model_repo(
        self,
        name: str,
        description: Optional[str] = None,
        engine: Optional[Engine] = None,
        exists_ok: bool = False,
    ) -> "mdl.ModelRepo":
        return mdl.create_model_repo(
            self.session,
            name,
            description=description,
            engine=engine,
            exists_ok=exists_ok,
        )

    def delete_model_repo(self, name: Optional[str] = None, repo_id: Optional[int] = None):
        if name and repo_id:
            raise ValueError("Cannot provide both repo name and repo id")
        if name:
            repo = self.get_model_repo(name)
            repo_id = repo.id
        endpoint = f"/models/repo/{repo_id}"
        return self.session.delete_json(endpoint)

    def get_model(
        self,
        name: Optional[str] = None,
        version: Optional[Union[int, str]] = None,
        model_id: Optional[int] = None,
    ) -> "mdl.Model":
        """
        :param name: name of model repo
        :param version: version in <repo_name>.<version>. If no version is specified, default to most recent
        ready/deployed/deploying/undeploying model
        :param model_id: Overrides repo name and version to get the exact model corresponding to the id
        :return:
        """
        return mdl.get_model(self.session, name, version, model_id)

    def get_suggested_configs(
        self,
        base_config: Dict[Any, str],
    ) -> List[ConfigSuggestion]:
        return mdl.get_suggested_configs(self.session, base_config)

    def show_suggested_compute(self, dataset: Dataset, config: dict) -> EngineTemplate:
        endpoint = "/models/suggested_compute"
        resp = self.session.post_json(endpoint, {"datasetID": dataset.id, "config": config})
        template = EngineTemplate.from_dict({"session": self.session, **resp})
        print(template)

    def get_most_recent_model_with_description(
        self,
        repo_name: str,
        model_description: str,
    ) -> Union["mdl.Model", None]:
        """Get the most recent model in the repo with a specific description.

        Returns None if a model with that description doesn't exist or if the repo doesn't exist.

        Args:
            repo_name: model repository name.
            model_description: model description.
        """
        try:
            repo = self.get_model_repo(repo_name)
        except ServerResponseError as e:
            if e.code == 400:
                # Model repo doesn't exist.
                return None

        models = repo.list_models()
        models.sort(key=lambda m: m.version, reverse=True)

        for model in models:
            if model.description == model_description:
                return model
        return None

    def get_default_config(
        self,
        dataset: Dataset,
        targets: Optional[Union[str, List[str]]] = None,
        automl: Optional[bool] = False,
        hyperopt: Optional[bool] = False,
    ) -> dict:
        """
        :param dataset
        :param targets: single target or list of targets. If targets are not provided, the user will
        have to manually edit config["output_features"] for training.
        :param hyperopt: whether hyperopt is enabled
        :return: Ludwig config
        """
        return mdl.get_default_config(self.session, dataset, targets, automl, hyperopt)

    def launch_tensorboard(
        self,
        model_id: int,
        model: Optional["mdl.Model"] = None,
    ) -> None:
        """Launch tensorboard for a model."""
        if model is None:
            model = self.get_model(model_id=model_id)

        model.launch_tensorboard()

    def create_model(
        self,
        repository_name: str,
        dataset: Dataset,
        config: dict,
        engine: Optional[Engine] = None,
        repo_description: Optional[str] = None,
        model_description: Optional[str] = None,
    ) -> "mdl.Model":
        if not self.session.is_plan_expired():
            if isinstance(config, str):  # assume path
                config_dict = load_yaml(config)
                self.config_fp = config
            elif config:
                config_dict = copy.deepcopy(config)
                self.config_fp = None
            repo_id = self._create_or_retrieve_repository(repository_name, repo_description, engine)
            return self._create_and_train_model(
                repo_id=repo_id,
                config=config_dict,
                dataset=dataset,
                repository_name=repository_name,
                model_description=model_description,
                engine=engine,
            )
        else:
            raise PermissionError(
                "Training models is locked for expired plans. Contact us to upgrade.",
            )

    def train_suggested_models(
        self,
        repository_name: str,
        dataset: Dataset,
        config_suggestions: List[ConfigSuggestion],
        config_suggestions_mask: Optional[List[bool]] = None,
        engine: Optional[Engine] = None,
        repository_description: Optional[str] = "",
    ) -> List["mdl.Model"]:
        """Train a number of models on list of config suggestions.

        Args:
            repository_name: name of the model repository.
            dataset: dataset object.
            config_suggestions: list of ConfigSuggestion objects.
            config_suggestions_mask: list of booleans referencing which
                config_suggestions to train on. Length must be equal to that
                of config_suggestions.
            engine: Engine object to use for training.
            repository_description: description of the repository.

        Returns:
            List of Models.
        """
        if not self.session.is_plan_expired():
            if config_suggestions_mask and len(config_suggestions_mask) != len(config_suggestions):
                raise ValueError("len(config_suggestions_mask) must be equal to len(config_suggestions).")
            if config_suggestions_mask and any([not isinstance(elem, bool) for elem in config_suggestions_mask]):
                raise ValueError("Elements of config_suggestions_mask must be all boolean.")
            if engine is not None and engine.template_id != 8:
                raise ValueError(
                    "Cannot train suggested models with this engine. Please specify a training (adaptive) engine.",
                )
            if engine is None:
                all_adaptive_engines = [eng for eng in self.list_engines() if eng.template_id == 8]
                if all_adaptive_engines:
                    engine = all_adaptive_engines[-1]
                    log_info(f"Using engine `{engine.name}` to train the suggested configs.")
                else:
                    raise ValueError(
                        "Tried to assign a training (adaptive) engine to train suggested models,"
                        "but found none. Please create a training engine.",
                    )
            if config_suggestions_mask:
                config_suggestions = [config_suggestions[i] for i, elem in enumerate(config_suggestions_mask) if elem]

            repo_id = self._create_or_retrieve_repository(repository_name, repository_description, engine)
            models = []
            with ThreadPoolExecutor() as executor:
                futures = [
                    executor.submit(
                        self._create_and_train_model,
                        repo_id,
                        suggestion.config,
                        dataset,
                        repository_name,
                        engine,
                        suggestion.description,
                    )
                    for suggestion in config_suggestions
                ]
                for future in as_completed(futures):
                    models.append(future.result())
            return models
        else:
            raise PermissionError(
                "Training models is locked for expired plans. Contact us to upgrade.",
            )

    def upload_model(self, model_path: str, repo: "mdl.ModelRepo", dataset: Optional[Dataset] = None) -> "mdl.Model":
        return repo.upload_model(model_path, dataset=dataset)

    def add_feature(self, config: dict, name: str, type: str, preprocessing: Optional[dict] = None):
        """This is a helper method for adding a feature to a model config.

        :param config: The config to add a feature to
        :param name: The name of the feature to add to the config
        :param type: The type of the feature to add to the config
        :param preprocessing: An optional preprocessing dictionary to specify preprocessing instructions for this
            particular feature.
        """
        if name in [x["name"] for x in config["input_features"]]:
            raise ValueError(f"Input Feature: '{name}' already exists")

        feature = {"name": name, "type": type}

        if preprocessing:
            feature["preprocessing"] = preprocessing

        config["input_features"].append(feature)

    def remove_feature(
        self,
        config: dict,
        name: str,
    ):
        """This is a helper method for removing a feature from a model config.

        :param config: The config to remove a feature from
        :param name: The name of the feature to remove from the config
        """
        if name not in [x["name"] for x in config["input_features"]]:
            raise ValueError(f"Input Feature: '{name}' does not exist")

        updated_features = [x for x in config["input_features"] if x["name"] != name]

        config["input_features"] = updated_features

    def _create_or_retrieve_repository(
        self,
        repo_name: str,
        repo_description: Optional[str] = None,
        engine: Optional[Engine] = None,
        exists_ok: bool = True,
    ) -> int:
        """Creates a new model repository or retrieves an existing one."""
        try:
            resp = self.session.post_json(
                "/models/repo",
                {
                    "modelType": "ludwig",
                    "description": repo_description,
                    "retrainCadence": "",
                    "retrainConfig": {},
                    "modelName": repo_name,
                    "selectedEngineID": engine.id if engine else None,
                    "parentID": None,
                },
            )
            log_info(f"Created model repository: <{repo_name}>")
            repo_id = resp["id"]
            return repo_id
        except ServerResponseError as e:
            if exists_ok and e.code == 409:
                log_info(f"Model repository {repo_name} already exists and new models will be added to it.")
                resp = self.session.get_json(f"/models/repo/name/{encode_url_param(repo_name)}")
                repo_id = resp["id"]
                return repo_id
            else:
                raise e

    def _create_and_train_model(
        self,
        repo_id: int,
        config: dict,
        dataset: Dataset,
        repository_name: str,
        engine: Optional[Engine] = None,
        model_description: Optional[str] = None,
    ):
        resp = self.session.post_json(
            "/models/train",
            {
                "datasetID": dataset.id,
                "config": ConfigEncoder().decimalize(config),
                "repoID": repo_id,
                "engineID": engine.id if engine else None,
                "description": model_description,
            },
        )
        model_id, model_version = resp["model"]["id"], resp["model"]["repoVersion"]
        log_info(f"Training model version {model_version} for model repository <{repository_name}>...")

        endpoint = f"models/version/{model_id}"
        url = get_url(self.session, endpoint)
        log_info(f"Check Status of Model Training Here: [link={url}]{url}")

        resp = self.session.get_json_until(
            f"/models/version/{model_id}",
            lambda resp: resp["modelVersion"]["completed"] is not None
            and resp["modelVersion"]["status"]
            not in (
                "failed",
                "canceled",
            ),
            lambda resp: (
                f"Failed to train model with status {resp['modelVersion']['status'].upper()} and error "
                f"{resp['modelVersion']['errorText']}"
            )
            if resp["modelVersion"]["status"] in {"failed", "canceled"}
            else None,
        )

        from predibase.resource_util import build_model

        return build_model(resp["modelVersion"], self.session)
