import copy
import datetime
import os
import tempfile
import time
import warnings
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from functools import cached_property
from http import HTTPStatus
from threading import Event, Thread
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import urlparse

import deprecation
import pandas as pd
import requests
from dataclasses_json import config, dataclass_json, LetterCase
from dateutil import parser

from predibase.pql.api import ServerResponseError, Session
from predibase.pql.utils import get_results_df
from predibase.resource.config import ConfigSuggestion
from predibase.resource.dataset import DataField, Dataset

# if TYPE_CHECKING:  # Only imports the below statements during type checking
#     from predibase.dataset import Dataset
from predibase.resource.engine import Engine
from predibase.resource.llm import interface
from predibase.resource.user import User
from predibase.resource.viz import VisualizeType
from predibase.resource_util import build_model_repo
from predibase.util import get_url, log_info, spinner
from predibase.util.metrics import is_llm_model
from predibase.util.tensorboard import launch_tensorboard as launch_tb
from predibase.util.url import encode_url_param
from predibase.version import __version__

TRAIN_METRICS = "train_metrics"
VALIDATION_METRICS = "validation_metrics"
TEST_METRICS = "test_metrics"

MODEL_WEIGHTS = "model_weights"


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class ModelRepo:
    session: Session
    _id: str = field(metadata=config(field_name="id"))
    _uuid: str = field(metadata=config(field_name="uuid"))
    _name: str = field(metadata=config(field_name="modelName"))
    _created: str = field(metadata=config(field_name="created"))
    _updated: str = field(metadata=config(field_name="updated"))
    _description: Optional[str] = field(metadata=config(field_name="description"), default=None)
    _root_id: Optional[str] = field(metadata=config(field_name="rootID"), default=None)
    _user: Optional[User] = field(metadata=config(field_name="user"), default=None)
    _parent_id: Optional[str] = field(metadata=config(field_name="parentID"), default=None)
    # Latest dataset
    _latest_config: Optional[dict] = field(metadata=config(field_name="latestConfig"), default=None)
    _latest_dataset_id: Optional[int] = field(metadata=config(field_name="datasetID"), default=None)
    _latest_dataset: Optional[Dataset] = field(metadata=config(field_name="dataset"), default=None)

    def __repr__(self):
        return (
            f"ModelRepo(id={self.id}, name={self._name}, description={self.description}, "
            f"latest_config={{...}}, "
            f"latest_dataset={self.latest_dataset}, "
            f"created={self._created}, updated={self._updated})"
        )

    def _build_model_with_backref(self, resp):
        from predibase.resource_util import build_model

        resp["repo"] = self
        return build_model(resp, self.session)

    @property
    def id(self):
        return self._id

    @property
    def uuid(self):
        return self._uuid

    @property
    def name(self):
        return self._name

    @property
    def description(self):
        return self._description

    @property
    def latest_config(self):
        return self._latest_config

    @property
    def latest_dataset(self):
        if self._latest_dataset:
            return self._latest_dataset
        # get_model().repo.latest_dataset isn't seeded
        if self._latest_dataset_id:
            resp = self.session.get_json(f"/datasets/{self._latest_dataset_id}")
            from predibase.resource_util import build_dataset

            self._latest_dataset = build_dataset(resp, self.session)
            return self._latest_dataset
        return None

    @property
    def latest_dataset_id(self):
        return self._latest_dataset_id

    @property
    def created(self):
        return self._created

    @property
    def updated(self):
        return self._updated

    @property
    def parent_id(self):
        return self._parent_id

    @property
    def root_id(self):
        return self._root_id

    @property
    def author(self):
        return self._user.username if self._user else None

    def create_draft(
        self,
        dataset: Optional[Dataset] = None,
        target: Optional[Union[str, List[str]]] = None,
        automl: Optional[bool] = False,
        hyperopt: Optional[bool] = False,
        config: Optional[dict] = None,
        description: Optional[str] = None,
    ) -> "ModelDraft":
        dataset = dataset or self.latest_dataset
        if dataset is None:
            raise ValueError(
                "Model repo has no latest dataset, and no dataset was provided. "
                "Cannot create model draft without a dataset.",
            )

        # need target to get the default config.
        if not config and target:
            config = get_default_config(self.session, dataset, target, automl, hyperopt)
        return ModelDraft(
            session=self.session,
            repo_id=self.id,
            _repo=self,
            name=self._name,
            config=config,
            dataset=dataset,
            description=description,
        )

    def _filter_model_weights(self, filename: str) -> bool:
        return "readme" not in filename.lower()

    def upload_model(self, model_path: str, dataset: Optional[Dataset] = None) -> "Model":
        required_metadata_files = ["model_hyperparameters.json", "training_progress.json", "training_set_metadata.json"]

        dataset_id = dataset.id if dataset is not None else self.latest_dataset_id
        if dataset_id is None:
            raise ValueError("must either provide a dataset or upload to a model repo with a dataset configured")

        with tempfile.TemporaryDirectory() as tmpdir:
            # If the path specified is a local folder, no need to unzip.
            model_artifacts_path = model_path
            if not os.path.isdir(model_path):
                model_artifacts_path = tmpdir
                with zipfile.ZipFile(model_path, "r") as zf:
                    zf.extractall(path=tmpdir)

            # Some model zips may save the files of interest in a model/ sub-directory.
            if os.path.exists(os.path.join(model_artifacts_path, "model")):
                model_artifacts_path = os.path.join(model_artifacts_path, "model")

            for required_file in required_metadata_files + [MODEL_WEIGHTS]:
                if not os.path.exists(os.path.join(model_artifacts_path, required_file)):
                    raise FileNotFoundError(
                        f"required file {required_file} not found in model folder {model_artifacts_path}",
                    )

            if not os.path.exists(os.path.join(model_artifacts_path, MODEL_WEIGHTS)):
                raise FileNotFoundError(f"model_weights file(s) not found in model folder {model_artifacts_path}")

            model_weights_files = []
            if os.path.isdir(os.path.join(model_artifacts_path, MODEL_WEIGHTS)):
                for file in os.listdir(os.path.join(model_artifacts_path, MODEL_WEIGHTS)):
                    if self._filter_model_weights(file):
                        model_weights_files.append(file)
            else:
                model_weights_files = [MODEL_WEIGHTS]

            metadata_zip_path = os.path.join(tmpdir, "model_metadata.zip")
            with zipfile.ZipFile(metadata_zip_path, "w") as metadata_zip:
                for f in required_metadata_files:
                    metadata_zip.write(os.path.join(model_artifacts_path, f), arcname=f)

            with open(metadata_zip_path, "rb") as zipped_metadata:
                files = {"file": zipped_metadata}
                file_name, _ = os.path.splitext(os.path.basename(metadata_zip_path))
                s = ","
                data = {
                    "fileName": file_name,
                    "datasetID": dataset_id,
                    "repoID": self.id,
                    "modelWeightsFiles": s.join(model_weights_files),
                }
                register_model_resp = self.session.post("/models/register_uploaded_model", files=files, data=data)

            model_dict = register_model_resp["model"]
            presigned_urls = register_model_resp["modelWeightsPresignedFiles"]

            # Loop through the model weight files and upload them to blob storage.
            # Beacuse we send the list of files to upload to the backend, we should
            # be able to rely on the order of the response matching our list.
            for idx, model_weight_file in enumerate(model_weights_files):
                presigned_url = presigned_urls[idx]
                upload_url = presigned_url["url"]
                upload_required_headers = presigned_url.get("headers", {})
                if upload_required_headers is None:
                    upload_required_headers = {}

                content_type = (
                    "application/json" if model_weight_file.lower().endswith(".json") else "binary/octet-stream"
                )
                headers = {"Content-Type": content_type}
                for k, v in upload_required_headers:
                    headers[k] = v

                file_path = (
                    os.path.join(model_artifacts_path, model_weight_file)
                    if model_weight_file == MODEL_WEIGHTS
                    else os.path.join(model_artifacts_path, "model_weights", model_weight_file)
                )
                with open(file_path, "rb") as weights_file:
                    # Upload file to blob storage with pre-signed url
                    requests.put(upload_url, data=weights_file, headers=headers).raise_for_status()

            # Signal successful upload of model weights.
            self.session.post(f"/models/complete_upload_model/{model_dict['id']}")

            model_dict["status"] = "ready"
            return self._build_model_with_backref(model_dict)

    def list_models(self, df: bool = False):
        endpoint = f"/models/repo/{self._id}?withVersions=true"
        resp = self.session.get_json(endpoint)
        if df:
            return pd.DataFrame([m for m in resp["modelRepo"]["models"]])
        return [self._build_model_with_backref(m) for m in resp["modelRepo"]["models"]]

    def draft_from_latest_version(self) -> "ModelDraft":
        return ModelDraft(
            session=self.session,
            repo_id=self.id,
            _repo=self,
            name=self._name,
            config=copy.deepcopy(self.latest_config),
            dataset=self.latest_dataset,
        )

    def latest(self) -> "Model":
        return get_model(self.session, self.name)

    def head(self) -> "Model":
        return self.latest()

    def get(self, version: Optional[Union[int, str]] = None) -> "Model":
        return get_model(self.session, self.name, version)


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class ModelRunMetadata:
    _id: str = field(metadata=config(field_name="id"))
    _model_id: int = field(metadata=config(field_name="modelID"))
    _run_id: str = field(metadata=config(field_name="runID"))
    _rendered_config: dict = field(metadata=config(field_name="renderedConfig"))

    @property
    def rendered_config(self) -> dict:
        return self._rendered_config


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class Model:
    # Disable the dataclass-json violation (ref: https://predibase.slack.com/archives/C02AZ1USR1U/p1696446768000669)
    # pylint: disable=used-before-assignment
    session: Session
    _id: str = field(metadata=config(field_name="id"))
    _uuid: str = field(metadata=config(field_name="uuid"))
    _repo_id: int = field(metadata=config(field_name="repoID"))
    _repo: ModelRepo = field(metadata=config(field_name="repo"))
    _config: dict = field(metadata=config(field_name="config"))
    _dataset_id: int = field(metadata=config(field_name="datasetID"))
    _dataset: Dataset = field(metadata=config(field_name="dataset"))
    _version: str = field(metadata=config(field_name="repoVersion"))
    _status: str = field(metadata=config(field_name="status"))
    _starred: bool = field(metadata=config(field_name="starred"))
    _archived: bool = field(metadata=config(field_name="archived"))
    # _created: datetime.datetime = config(metadata=config(field_name="created"))
    _created: str = field(metadata=config(field_name="created"))
    _user: Optional[User] = field(metadata=config(field_name="user"), default=None)
    _created_by_user_id: Optional[int] = field(metadata=config(field_name="createdByUserID"), default=None)
    _engine_id: Optional[str] = field(metadata=config(field_name="engineID"), default=None)
    _engine: Optional[Engine] = field(metadata=config(field_name="engine"), default=None)
    _engine_template: Optional[Dict[str, Any]] = field(metadata=config(field_name="engineTemplate"), default=None)
    _description: Optional[str] = field(metadata=config(field_name="description"), default=None)
    _experiment_id: Optional[int] = field(metadata=config(field_name="experimentID"), default=None)
    _error_text: Optional[str] = field(metadata=config(field_name="errorText"), default=None)
    _best_run_id: Optional[str] = field(metadata=config(field_name="bestRunID"), default=None)
    _active_run_id: Optional[str] = field(metadata=config(field_name="activeRunID"), default=None)
    _completed: Optional[str] = field(metadata=config(field_name="completed"), default=None)
    _training_created: Optional[str] = field(metadata=config(field_name="trainingCreated"), default=None)
    _training_completed: Optional[str] = field(metadata=config(field_name="trainingCompleted"), default=None)
    _active_run_meta: Optional[ModelRunMetadata] = field(metadata=config(field_name="modelRun"), default=None)
    _llm_base_model_name: Optional[str] = field(metadata=config(field_name="llmBaseModelName"), default=None)

    def __repr__(self):
        dataset = f"Dataset({self._dataset.name}...)"
        repo = f"Repo({self.repo.name}...)"
        return (
            f"Model(id={self._id}, repo={repo}, description={self.description}, "
            f"dataset={dataset}, engine=Engine({self.engine.name if self.engine else None}...), "
            f"config={{...}}, version={self.version}, "
            f"status={self.status}, created={self.created}, completed={self.completed})"
        )

    @property
    def id(self):
        return self._id

    @property
    def uuid(self) -> str:
        return self._uuid

    @property
    def best_run_id(self) -> str:
        return self._best_run_id

    @property
    def description(self):
        return self._description

    @property
    def config(self):
        return self._config

    @property
    def rendered_config(self):
        if self._active_run_meta is None:
            return None
        return self._active_run_meta.rendered_config

    @property
    def version(self):
        return self._version

    @property
    def repo_id(self):
        return self._repo_id

    @property
    def author(self):
        return self._user.username if self._user else None

    @property
    def repo(self):
        return self._repo

    @property
    def dataset_id(self):
        return self._dataset_id

    @property
    def engine_id(self):
        return self._engine_id

    @property
    def engine(self):
        if self._engine:
            return self._engine
        resp = self.session.get_json(f"/engines/{self.engine_id}")
        engine = Engine.from_dict({"session": self.session, **resp})
        self._engine = engine
        return engine

    @property
    def engine_template(self):
        return self._engine_template

    @property
    def dataset(self):
        return self._dataset

    @property
    def status(self):
        return self._get()["status"]

    @property
    def error_text(self) -> Union[str, None]:
        resp = self._get()
        if "errorText" in resp:
            return resp["errorText"]
        return None

    @property
    def active_fields(self) -> List[DataField]:
        resp = self._get()
        return [DataField.from_dict({"session": self.session, **x["field"]}) for x in resp["activeFields"]]

    @property
    def starred(self) -> bool:
        return self._starred

    @property
    def archived(self) -> bool:
        return self._archived

    @property
    def created(self) -> datetime.datetime:
        return pd.to_datetime(self._created)

    @property
    def completed(self) -> datetime.datetime:
        if self._completed:
            return pd.to_datetime(self._completed)
        resp = self._get()
        if "completed" in resp:
            self._completed = resp["completed"]
            return pd.to_datetime(self._completed)
        return None

    @property
    def training_created(self) -> datetime.datetime:
        if self._training_created:
            return self._training_created
        resp = self._get()
        if "trainingCreated" in resp:
            self._training_created = resp["trainingCreated"]
            return self._training_created
        return None

    @property
    def training_completed(self) -> datetime.datetime:
        if self._training_completed:
            return self._training_completed
        resp = self._get()
        if "trainingCompleted" in resp:
            self._training_completed = resp["trainingCompleted"]
            return self._training_completed
        return None

    @cached_property
    def metrics(self) -> "ModelMetrics":
        nested_metrics = {
            TRAIN_METRICS: defaultdict(dict),
            VALIDATION_METRICS: defaultdict(dict),
            TEST_METRICS: defaultdict(dict),
        }

        global_metrics = {
            TRAIN_METRICS: defaultdict(dict),
            VALIDATION_METRICS: defaultdict(dict),
            TEST_METRICS: defaultdict(dict),
        }

        general_metrics = {}

        for metric in self.active_run.data.metrics:
            parts = metric.key.split(".")

            if len(parts) == 1:
                general_metrics[metric.key] = metric.value
                continue

            # we'd like to capture the best metrics of the run.
            if parts[0] != "best" or len(parts) < 2:
                continue

            # if this field contains metrics, its format will look like the following
            # "best.train_metrics.Survived.accuracy"
            _, split, feature, name = parts

            if feature != "combined":
                nested_metrics[split][feature][name] = metric.value
            else:
                global_metrics[split][feature][name] = metric.value

        return ModelMetrics(nested_metrics, global_metrics, general_metrics)

    @property
    def active_run(self):
        return self.runs[self._active_run_id]

    @cached_property
    def runs(self) -> Dict[str, "ModelRun"]:
        resp = self.session.get_json(f"/models/version/{self.id}?withRuns=true")
        runs: List[ModelRun] = [ModelRun.from_dict(run) for run in resp["runs"]]
        return {run.info.run_id: run for run in runs}

    @property
    def llm_base_model_name(self) -> Optional[str]:
        return self._llm_base_model_name

    def _get(self):
        endpoint = f"/models/version/{self.id}"
        resp = self.session.get_json(endpoint)
        return resp["modelVersion"]

    def update_description(self, description: str):
        endpoint = f"/models/version/{self._id}"
        self.session.put_json(
            endpoint,
            {
                "id": self.id,
                "description": description,
                "starred": self.starred,
                "archived": self.archived,
            },
        )

    def delete(self):
        return self.session.delete_json(f"/models/version/{self.id}")

    def cancel(self):
        return self.session.post_json(f"/models/version/{self.id}/cancel", {})

    def _model_download_endpoint(self, framework: str) -> str:
        endpoint = f"/models/download/{self.id}"
        return endpoint + f"?framework={framework.lower()}"

    @spinner(name="exporting model")
    def _poll_model_download(self, endpoint: str) -> Dict[str, Any]:
        while True:
            resp = self.session.get_json(endpoint)
            status = resp["status"]
            if status == "exporting":
                time.sleep(2)
            elif status == "complete":
                break
            else:
                raise ValueError(f"Error exporting model: {resp['failure_reason']}")

        return resp

    def _start_model_download(self, endpoint: str) -> Dict[str, Any]:
        try:
            self.session.post(endpoint, {})
        except ServerResponseError as e:
            raise e

        return self._poll_model_download(endpoint)

    @deprecation.deprecated(
        deprecated_in="2024.2.12",
        current_version=__version__,
        details="framework parameter is deprecated",
    )
    def download(
        self,
        name: Optional[str] = None,
        location: Optional[str] = None,
        framework: Optional[str] = None,
    ):
        """
        This method downloads the model to the specified location on your local machine.
        Args:
            name: Optional[str] - Name for the downloaded file.
            location: Optional[str] - File path to download the model to.
            framework: Optional[str] - Framework to download the model as. Default is to download as a Ludwig Model.

        Returns:
            None
        """
        if framework is None:
            framework = "ludwig"
        else:
            warnings.warn("framework parameter is deprecated and will be removed in an upcoming release.")

        if is_llm_model(self._config) and framework != "ludwig":
            raise ValueError("LLMs can only be exported using the Ludwig format.")

        if location is not None:
            if not os.path.exists(location):
                raise ValueError(f"Location {location} does not exist.")

        endpoint = self._model_download_endpoint(framework)

        log_info("Downloading model")
        try:
            resp = self.session.get_json(endpoint)
        except ServerResponseError as e:
            # Model has not been previously exported. Start process.
            if "error 400: record not found" in e.message.lower():
                log_info("Model has not been exported yet. Starting export.")
                resp = self._start_model_download(endpoint)
                pass
            else:
                raise e

        status = resp["status"]
        # Wait for model to finish exporting
        if status == "exporting":
            resp = self._poll_model_download(endpoint)
        # If model was previously exported but failed, restart process
        elif status == "failed":
            resp = self._start_model_download(endpoint)

        # Now that model is successfully exported, download it
        url = resp["url"]
        download_path = None
        if name:
            if name[-4:] == ".zip":
                download_path = name
            else:
                download_path = name + ".zip"
        else:
            download_path = os.path.basename(urlparse(url).path)

        if location is not None:
            download_path = os.path.join(location, download_path)

        resp = requests.get(url)
        with open(download_path, "wb") as f:
            f.write(resp.content)

        log_info(f"Model downloaded to {download_path}")

    @deprecation.deprecated(
        deprecated_in="2024.2.12",
        current_version=__version__,
        details="framework parameter is deprecated",
    )
    def export(
        self,
        location: str,
        connection: Optional[Union[str, int]] = None,
        framework: Optional[str] = None,
    ):
        """Export a model to an export location using the connection or target connection with the optional
        framework.

        :param location: Location as string.
        :param connection: (Optional[str, int]): Optional connection id or name for export location.
        :param framework: Optional framework, defaults to "ludwig"
        """
        connection_id = self.session.get_connection_id(connection) if connection else None
        query = f"EXPORT MODEL {self.repo.name} VERSION {self.version}"
        if framework is not None:
            warnings.warn("framework parameter is deprecated and will be removed in an upcoming release.")
            query = query + f" WITH FORMAT (framework='{framework}')"
        query = query + f" TO '{location}'"
        return self.session.execute(query, connection_id=connection_id)

    def evaluate(
        self,
        targets: Union[str, List[str]],
        source: Union[Dataset, pd.DataFrame, str],
        limit: Optional[int] = None,
        metadata: Optional[bool] = False,
    ) -> pd.DataFrame:
        """Evaluate a model given a source dataset for one or more targets.

        :param targets (Union[str, List[str], Dict[str, str]]): One or more target names to make predictions on.
        :param source (Union[Dataset, pd.DataFrame, str]): Source dataset to evaluate.
        :param metadata (Optional[bool]): Optional boolean flag to return model name and version metadata in results.
        """
        if isinstance(targets, list):
            predict_targets = ", ".join([f'"{t}"' for t in targets])
        else:
            predict_targets = f'"{targets}"'

        # create list of properties
        properties = []
        if metadata:
            properties.append("METADATA")

        if len(properties) > 0:
            predict_targets += " WITH " + ", ".join(properties)

        # Add using query for current model and the latest version
        model_name = f'"{self.repo.name}" VERSION {self.version}'

        # Source can be a dataset, dataframe, or query string.
        source, params, connection_id = self._build_source(source, limit)

        # Set session connection from dataset if not set
        if not self.session.connection_id and self.dataset:
            self.session.set_connection(self.dataset.connection_id)
        query = f"EVALUATE {predict_targets} USING {model_name} GIVEN {source}"
        return self.session.execute(query, params=params, connection_id=connection_id)

    def predict(
        self,
        targets: Union[str, List[str], Dict[str, str]],
        source: Union[Dataset, pd.DataFrame, str],
        limit: Optional[int] = None,
        explanation: Optional[Union[bool, str]] = False,
        confidence: Optional[bool] = False,
        probabilities: Optional[Union[bool, List[any]]] = False,
        metadata: Optional[bool] = False,
        engine: Optional[Engine] = None,
    ) -> pd.DataFrame:
        """Make predictions for one or more target variables given a source dataset.

        :param targets: (Union[str, List[str], Dict[str, str]]): One or more target names to make predictions on.
        Include a dictionary with key being the target and the value being an alias to return in results.
        :param source: (Union[Dataset, pd.DataFrame, str]): Source to perform predictions on.
        :param limit: Number of rows to return.
        :param explanation: (Optional[Union[bool, str]]): Optional flag to enable explanations.
        Provide a string to return explanations for a specific algorithm.  Supported values are 'ig' or 'shap'.
        :param confidence: (Optional[bool]): Optional boolean flag to return metadata in results.
        :param probabilities: (Optional[Union[bool, List[any]]]): Optional flag to return probabilities for binary of
            multi-class classificaiton.
        Provide a list of category names eg [True,False] to include a specific set of classes.
        :param metadata: (Optional[bool]): Optional boolean flag to return model name and version metadata in results.
        :param engine: (Optional[Engine]): Option to select a particular engine for executing the predict.
        """

        # Add predict targets with optional alias, list, or as simple string
        if isinstance(targets, dict):
            predict_targets = ", ".join([f'"{k}" AS "{v}"' for (k, v) in targets.items()])
        elif isinstance(targets, list):
            predict_targets = ", ".join([f'"{t}"' for t in targets])
        else:
            predict_targets = f'"{targets}"'

        # create list of properties
        properties = []
        if confidence:
            properties.append("CONFIDENCE")
        if explanation:
            # TODO: Also add an enum type here for explanation instead of just string
            if isinstance(explanation, str):
                properties.append(f"EXPLANATION (algo='{explanation}')")
            else:
                properties.append("EXPLANATION")
        if probabilities:
            categories = ""
            if isinstance(probabilities, list):
                categories = ", ".join([f"'{str(c)}'" for c in probabilities])
                categories = f" OF ({categories})"
            properties.append("PROBABILITIES" + categories)
        if metadata:
            properties.append("METADATA")

        if len(properties) > 0:
            predict_targets += " WITH " + ", ".join(properties)

        # Add using query for current model and the latest version
        model_name = f'"{self.repo.name}" VERSION {self.version}'

        # Source can be a dataset, dataframe, or query string.
        source, params, connection_id = self._build_source(source, limit)
        # If using a dataframe, use model.dataset.connection_id
        if params:
            connection_id = self.dataset.connection_id

        query = f"PREDICT {predict_targets} USING {model_name} GIVEN {source}"
        return self.session.execute(
            query,
            params=params,
            connection_id=connection_id,
            engine_id=engine.id if engine else None,
        )

    def deploy(
        self,
        deployment_name: str,
        engine_template: Optional[str] = None,
        hf_token: Optional[str] = None,
        auto_suspend_seconds: Optional[int] = None,
        max_input_length: Optional[int] = None,
        max_total_tokens: Optional[int] = None,
        max_batch_prefill_tokens: Optional[int] = None,
        revision: Optional[str] = None,
        quantization_kwargs: Optional[Dict[str, str]] = None,
        overwrite: Optional[bool] = False,
    ) -> "interface.LLMDeploymentJob":
        if not self._llm_base_model_name:
            raise NotImplementedError(
                "Support for non-LLM deployments via this API is not yet implemented. "
                "Please use predibase_client.create_deployment() instead",
            )

        return interface.deploy_llm(
            session=self.session,
            deployment_name=deployment_name,
            engine_template=engine_template,
            hf_token=hf_token,
            auto_suspend_seconds=auto_suspend_seconds,
            max_input_length=max_input_length,
            max_total_tokens=max_total_tokens,
            max_batch_prefill_tokens=max_batch_prefill_tokens,
            quantization_kwargs=quantization_kwargs,
            revision=revision,
            predibase_model_uri=f"pb://models/{self.repo.name}/{self.version}",
            overwrite=overwrite,
        )

    def visualize(
        self,
        visualize_type: Union[VisualizeType, str],
        output_feature: Optional[str] = None,
        plot_images: Optional[bool] = True,
    ) -> List[str]:
        self._wait_until_ready()

        if isinstance(visualize_type, VisualizeType):
            visualize_type = visualize_type.value
        endpoint = f"/visualize?modelID={self.id}&visualizeType={visualize_type}"
        if output_feature:
            endpoint += f"&outputFeature={output_feature}"
        resp = self.session.get_json(endpoint)
        if plot_images:
            import ipyplot

            ipyplot.plot_images(
                resp["links"],
                img_width=400,
            )
        return resp["links"]

    def get_evaluation_statistics(self):
        self._wait_until_ready()
        endpoint = f"/visualize?modelID={self.id}&visualizeType=evaluation_statistics"
        resp = self.session.get_json(endpoint)
        return resp["testStatistics"]

    def get_feature_importance(self, output_feature: Optional[str] = None) -> pd.DataFrame:
        self._wait_until_ready()

        if output_feature is None:
            output_features = [x["name"] for x in self.config["output_features"]]
            if len(output_features) == 1:
                output_feature = output_features[0]
            else:
                raise ValueError(
                    "No output feature provided and "
                    "cannot be inferred because model contains multiple output features",
                )
        endpoint = f"/visualize/explanations?modelID={self.id}&outputFeature={output_feature}"
        resp = self.session.get_json(endpoint)
        return get_results_df({"dataset": resp})

    def get_training_timeline(self) -> pd.DataFrame:
        """
        :return: Dataframe with columns [Step, Start, End, Duration], where Step in
            {Preprocessing, Training, Evaluating, etc.}
        """
        endpoint = f"/models/version/{self.id}/timeline"
        resp = self.session.get_json_until(
            endpoint=endpoint,
            success_cond=lambda resp: all(
                [resp[process]["created"] is not None and resp[process]["completed"] is not None for process in resp],
            ),
        )
        columns = ["step", "error_message", "start", "end", "duration"]
        data = []
        for process in resp:
            start = parser.parse(resp[process]["created"])
            end = parser.parse(resp[process]["completed"])
            error_message = resp[process].get("errorMessage", None)
            data.append([process, error_message, start, end, end - start])
        return pd.DataFrame(columns=columns, data=data)

    def _build_source(
        self,
        source: Union[Dataset, pd.DataFrame, str],
        limit: Optional[int] = None,
    ) -> Tuple[str, Optional[str], Optional[str]]:
        # Source can be a dataset, dataframe, or query string.
        params = None
        connection_id = None
        if isinstance(source, Dataset):
            connection_id = source.connection_id
            source = f'SELECT * FROM "{source.connection.name}"."{source.name}"'
            if limit is not None:
                source += f" LIMIT {limit}"
        elif isinstance(source, pd.DataFrame):
            params = {"sdk_df_dataset": source.to_json()}
            source = "sdk_df_dataset"
        elif not isinstance(source, str):
            raise Exception(f"unexpected source type {type(source)}")
        return source, params, connection_id

    def to_draft(self):
        return ModelDraft(
            session=self.session,
            name=self.repo.name,
            repo_id=self.repo_id,
            _repo=self._repo,
            config=copy.deepcopy(self.config),
            dataset=self.dataset,
        )

    def fork(self, name):
        return ModelDraft(
            session=self.session,
            name=name,
            config=copy.deepcopy(self.config),
            dataset=self.dataset,
            parent_id=self.repo_id,
        )

    def get_active_fields(self) -> List[DataField]:
        """
        Queries like "PREDICT <field>> GIVEN SELECT * FROM <dataset>" that don't specify an explicit model
        will use this model for each of the fields returned here
        """
        return self.active_fields

    def activate_model_for_field(self, field: DataField):
        """Sets this model as the default model used for operations on a data field. For example, if you have two
        models.

        [model_tabnet, model_concat] trained on the same dataset, you can call
        model_tabnet.set_default_for_field(DataField(id=..., name="Survived")).

        Queries like "PREDICT <field>> GIVEN SELECT * FROM <dataset>" that don't specify an explicit model
        will use the default model set here for the "Survived" field

        :param field: DataField of dataset. Obtained from dataset.get_fields()
        """
        if field.id in [x.id for x in self.active_fields]:
            raise ValueError(f"field {field.name} is already active for this model")
        return self.session.post_json("/models/activate", {"modelID": self.id, "fieldIDs": [field.id]})

    def deactivate_model_for_field(self, field: DataField):
        if field.id not in [x.id for x in self.active_fields]:
            raise ValueError(f"field {field.name} is not active for this model")
        return self.session.post_json("/models/activate", {"modelID": self.id, "fieldIDs": [field.id]})

    def _wait_until_ready(self, launch_tensorboard=False):
        """Utility function to wait until a model is fully ready, including evaluation and visualization steps.
        Certain operations may otherwise fail in a racy way.

        :param model: the Model to wait for.
        :return: None
        """
        self.session._wait_until_model_ready_with_logging(self._id, launch_tensorboard)

    def launch_tensorboard(self):
        # Check if the model has logs available or will have logs available
        model_logs = self.session.get_model_logs_urls(self._id)
        if len(model_logs.get("logfiles", [])) == 0 and not model_logs.get("moreLogsAvailable", False):
            print(
                f"Model {self._id} does not have logs available, which is likely because the model failed or was terminated before logs were created. Please check model status.",  # noqa: E501
            )
            return

        # Sync files in subthread and launch TB in main thread
        tensorboard_event = Event()
        logs_sync_thread = Thread(
            target=self.session.get_model_logs,
            args=[self._id, tensorboard_event, None],
            daemon=True,
        )
        logs_sync_thread.start()
        launch_tb(self._id)

        # Stop syncing files when TB is stopped
        tensorboard_event.set()
        logs_sync_thread.join()


class ModelFuture:
    def __init__(self, version_id: int, session: Session):
        self.version_id = version_id
        self.session = session

    def wait(self):
        self._wait_for_ready()

    def get(
        self,
        launch_tensorboard: bool = False,
    ) -> Model:
        log_info("Monitoring status of model training...")

        for _ in range(5):
            resp = self.session.get_json(f"/models/version/{self.version_id}")
            engine_template = resp.get("modelVersion", {}).get("engineTemplate", None)

            if engine_template is None:
                time.sleep(1)
                continue

            cloud = next(iter(engine_template["headNodeGroup"]["nodeType"]["clouds"]))

            node_counts = defaultdict(int)
            head_node_group_cloud = engine_template["headNodeGroup"]["nodeType"]["clouds"][cloud]
            head_node_label = head_node_group_cloud.get("publicLabel", head_node_group_cloud["label"])
            node_counts[head_node_label] += 1
            for worker_node_group in engine_template.get("workerNodeGroups", []):
                public_label = (
                    worker_node_group.get("nodeType", {}).get("clouds", {}).get(cloud, {}).get("publicLabel", "")
                )
                label = (
                    public_label
                    if public_label
                    else worker_node_group.get("nodeType", {}).get("clouds", {}).get(cloud, {}).get("label", "")
                )
                count = int(
                    worker_node_group.get("replicas", "0"),
                )
                if label:
                    node_counts[label] += count

            log_info("Compute summary:")
            for label, count in sorted(node_counts.items()):
                if count > 0:
                    log_info(f"  * {label} (x{count})")

            break

        if launch_tensorboard:
            launch_tb(self.version_id)

        resp = self._wait_for_ready(
            launch_tensorboard=launch_tensorboard,
        )

        from predibase.resource_util import build_model

        return build_model(resp["modelVersion"], self.session)

    def cancel(self):
        self.session.post_json(f"/models/version/{self.version_id}/cancel", {})

    def is_finished(self) -> bool:
        resp = self.session.get_json(f"/models/version/{self.version_id}")
        return resp["modelVersion"]["status"] in {"ready", "failed", "canceled"}

    def _wait_for_ready(self, launch_tensorboard=False) -> Dict[str, Any]:
        return self.session._wait_until_model_ready_with_logging(self.version_id, launch_tensorboard)


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class ModelDraft:
    session: Session
    dataset: Dataset
    config: dict
    description: Optional[str] = None
    repo_id: Optional[int] = None
    _repo: Optional[ModelRepo] = None
    name: Optional[str] = None
    parent_id: Optional[str] = None

    def __repr__(self):
        repo_str = f"repo=({self.repo.name}...) " if self.repo else "repo=(<new repo from fork>)"
        return (
            f"ModelDraft(name={self.name}, dataset=({self.dataset.name}...), config={{...}}, "
            f"description={self.description}, {repo_str}, parent_id={self.parent_id})"
        )

    @property
    def repo(self):
        return self._repo

    # Removed https://github.com/predibase/predibase/pull/3770
    # @spinner(name="Train Model")
    def train(self, engine: Optional[Engine] = None, launch_tensorboard: bool = False) -> Model:
        if not self.session.is_plan_expired():
            future = self.train_async(engine)
            return future.get(launch_tensorboard=launch_tensorboard)
        else:
            raise PermissionError(
                "Training models is locked for expired plans. Contact us to upgrade.",
            )

    def train_async(self, engine: Optional[Engine] = None) -> ModelFuture:
        if not self.session.is_plan_expired():
            # Retraining
            if self.repo_id:
                request = {
                    "config": self.config,
                    "datasetID": self.dataset.id,
                    "repoID": self.repo_id,
                    "engineID": engine.id if engine is not None else None,
                    "description": self.description,
                }

                resp = self.session.post_json("/models/train", request)
                model_id = resp["model"]["id"]

                # Output link to UI model page
                endpoint = f"models/version/{model_id}"
                url = get_url(self.session, endpoint)
                log_info(f"Check Status of Model Training Here: [link={url}]{url}")

                return ModelFuture(model_id, self.session)

            # Forking
            endpoint = "/models/repo"
            request = {
                "modelType": "ludwig",
                "modelName": self.name,
                "latestConfig": self.config,
                "retrainCadence": "",
                "retrainConfig": {},
                "datasetID": self.dataset.id,
                "parentID": self.parent_id,
            }
            resp = self.session.post_json(endpoint, request)
            repo_id = resp["id"]
            log_info(f"Created model repository: <{self.name}>")

            resp = self.session.post_json(
                "/models/train",
                {
                    "datasetID": self.dataset.id,
                    "config": self.config,
                    "repoID": repo_id,
                    "engineID": engine.id if engine is not None else None,
                },
            )
            model_id, model_version = resp["model"]["id"], resp["model"]["repoVersion"]
            log_info(f"Training model version {model_version} for model repository <{self.name}>...")
            return ModelFuture(model_id, self.session)
        else:
            raise PermissionError(
                "Training models is locked for expired plans. Contact us to upgrade.",
            )


class FeatureMetrics:
    def __init__(self, values: Dict[str, float]):
        for k, v in values.items():
            setattr(self, k, v)


class SplitMetrics:
    def __init__(
        self,
        nested_metrics: Dict[str, Dict[str, float]],
        global_metrics: Dict[str, float],
    ):
        for k, v in nested_metrics.items():
            setattr(self, k, FeatureMetrics(v))
        for k, v in global_metrics.items():
            setattr(self, k, v)


class ModelMetrics:
    def __init__(
        self,
        nested_metrics: Dict[str, Dict[str, Dict[str, float]]],
        global_metrics: Dict[str, Dict[str, float]],
        general_metrics: Dict[str, int],
    ):
        # General metrics includes things like epochs, batch_size, etc.
        self.general_metrics = general_metrics
        self.train = SplitMetrics(nested_metrics[TRAIN_METRICS], global_metrics[TRAIN_METRICS])
        self.validation = SplitMetrics(nested_metrics[VALIDATION_METRICS], global_metrics[VALIDATION_METRICS])
        self.test = SplitMetrics(nested_metrics[TEST_METRICS], global_metrics[TEST_METRICS])


# TODO(travis): Consider moving these off of MLFlow format
@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class ModelRunMetric:
    key: str
    step: int
    timestamp: float
    value: float


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class ModelRunParam:
    key: str
    value: str


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class ModelRunTag:
    key: str
    value: str


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class ModelRunInfo:
    artifact_uri: str
    experiment_id: str
    lifecycle_stage: str  # active
    run_id: str
    run_uuid: str
    status: str
    user_id: str
    end_time: Optional[float] = field(metadata=config(field_name="EndTime"), default=None)
    start_time: Optional[float] = field(metadata=config(field_name="StartTime"), default=None)


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class ModelRunData:
    metrics: List[ModelRunMetric]
    params: List[ModelRunParam]
    tags: List[ModelRunTag]


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class ModelRun:
    # https://www.mlflow.org/docs/latest/_modules/mlflow/entities/run_data.html
    data: ModelRunData

    # https://www.mlflow.org/docs/latest/_modules/mlflow/entities/run_info.html#RunInfo
    info: ModelRunInfo


def get_suggested_configs(
    session: Session,
    base_config: Dict[Any, str],
) -> List[ConfigSuggestion]:
    """Gets config suggestions given a base config."""
    resp = session.post_json(
        "/config/suggest",
        {
            "config": base_config,
        },
    )
    config_suggestions = resp["configs"]
    return [ConfigSuggestion.from_dict(suggestion) for suggestion in config_suggestions]


def get_default_config(
    session: Session,
    dataset: Dataset,
    targets: Optional[Union[str, List[str]]] = None,
    automl: Optional[bool] = False,
    hyperopt: Optional[bool] = False,
) -> dict:
    endpoint = f"/config/detect/{dataset.id}"
    resp = session.get_json(endpoint)
    config = resp["config"]

    if targets:
        if isinstance(targets, str):
            targets = [targets]
        output_features = [x for x in config["input_features"] if x["name"] in targets]
        config["input_features"] = [x for x in config["input_features"] if x["name"] not in targets]
        config["output_features"] = output_features
    if not automl:
        if "combiner" in config:
            del config["combiner"]
        if "trainer" in config:
            del config["trainer"]
    if not hyperopt:
        if "hyperopt" in config:
            del config["hyperopt"]
    return config


def get_model(
    session: Session,
    name: Optional[str] = None,
    version: Optional[Union[int, str]] = None,
    model_id: Optional[int] = None,
) -> Model:
    if not (name or model_id):
        raise ValueError("Must provide either model_name or model_id")
    if name and model_id:
        raise ValueError("Cannot provide both model name and model_id")
    if version:
        if model_id:
            raise ValueError("Cannot provide both model version and model_id")

    if model_id:
        endpoint = f"/models/version/{model_id}"
        resp = session.get_json(endpoint)["modelVersion"]
    else:
        endpoint = f"/models/version/name/{name}"
        endpoint += f"?version={version}" if version else ""
        resp = session.get_json(endpoint)

    from predibase.resource_util import build_model

    return build_model(resp, session)


def get_model_repo(session: Session, name: str) -> ModelRepo:
    resp = session.get_json(f"/models/repo/name/{encode_url_param(name)}")

    return build_model_repo(resp, session)


def create_model_repo(
    session: Session,
    name: str,
    description: Optional[str] = None,
    engine: Optional[Engine] = None,
    exists_ok: bool = False,
) -> ModelRepo:
    if not session.is_plan_expired():
        try:
            session.post_json(
                "/models/repo",
                {
                    "modelName": name,
                    "description": description,
                    "modelType": "ludwig",
                    "retrainCadence": "",
                    "retrainConfig": {},
                    "parentID": None,
                    "selectedEngineID": engine.id if engine else None,
                },
            )
            log_info(f"Created model repository: <{name}>")
        except ServerResponseError as e:
            if e.code == HTTPStatus.CONFLICT and exists_ok:
                log_info(f"Model repository {name} already exists and new models will be added to it.")
            else:
                raise e

        # TODO(travis): would be more efficient to return model repo data in CREATE response.
        return get_model_repo(session, name)
    else:
        raise PermissionError(
            "Creating Model Repos is locked for expired plans. Contact us to upgrade or if you would like a demo",
        )
