from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

import requests
from pydantic import BaseModel, Field, field_validator

from predibase._errors import FinetuningError
from predibase.config import FinetuningConfig
from predibase.resources.adapter import Adapter
from predibase.resources.dataset import Dataset
from predibase.resources.repo import Repo

# from predibase.resources.model import PretrainedHuggingFaceLLM, FinetunedLLMAdapter

if TYPE_CHECKING:
    from predibase import Predibase

_PATH_HERE = os.path.abspath(os.path.dirname(__file__))
_TEMPLATE_DIR = os.path.join(_PATH_HERE, "../resource/llm/templates")
_CONFIG_FILENAME = "config.yaml"  # Name of config file for loading templates.


class Adapters:
    def __init__(self, client: Predibase):
        self._client = client
        self._session = client._session  # Directly using the session in the short term as we transition to v2.

    def create(
        self,
        *,
        config: FinetuningConfig | dict,
        dataset: str | Dataset,
        repo: str | Repo,
        description: str | None = None,
        # show_tensorboard: bool = False,
    ) -> Adapter:

        # Always blocking since `watch` hardcoded to True.
        job = self._client.finetuning.jobs.create(
            config=config,
            dataset=dataset,
            repo=repo,
            description=description,
            watch=True,
            # show_tensorboard=show_tensorboard,
        )

        adapter_version_resp = self._client.http_get(f"/v2/repos/{job.target_repo}/version/{job.target_version_tag}")
        adapter = Adapter.model_validate(adapter_version_resp)

        if not adapter.artifact_path:
            raise FinetuningError(adapter.finetuning_error)

        return adapter

    def get(self, adapter_id: str) -> Adapter:
        adapter_version_resp = self._fetch(adapter_id)
        adapter = Adapter.model_validate(adapter_version_resp)

        if adapter_version_resp["status"] not in ("completed", "errored", "canceled"):
            # Training is still ongoing, so watch the progress and refetch after.
            print(f"Adapter {adapter_id} is not yet ready.")
            self._client.finetuning.jobs.watch(adapter.finetuning_job_uuid)

            adapter_version_resp = self._fetch(adapter_id)
            adapter = Adapter.model_validate(adapter_version_resp)

        if not adapter.artifact_path:
            raise FinetuningError(adapter.finetuning_error or "Unknown error - adapter not available.")

        return adapter

    def cancel(self, adapter_id: str):
        adapter_version_resp = self._fetch(adapter_id)
        adapter = Adapter.model_validate(adapter_version_resp)

        if not adapter.finetuning_job_uuid:
            raise RuntimeError(f"Adapter {adapter_id} is not associated with a cancelable finetuning job.")

        self._client.finetuning.jobs.cancel(adapter.finetuning_job_uuid)

    def download(self, adapter_id: str, dest: os.PathLike | None = None):
        repo, version_tag = self._parse_id(adapter_id)

        if dest is None:
            dest = os.path.join(os.getcwd(), f"{version_tag}.zip")

        if os.path.isdir(dest):
            dest = os.path.join(dest, f"{version_tag}.zip")

        print(f"Downloading adapter {adapter_id} as {dest}...")
        with self._client._http.get(
            self._client.api_gateway + f"/v2/repos/{repo}/version/{version_tag}/download",
            headers=self._client.default_headers,
        ) as r:
            try:
                r.raise_for_status()
                with open(dest, "wb") as f:
                    f.write(r.content)
                print("Done!")
            except requests.HTTPError as e:
                try:
                    response_text_obj = json.loads(r.text)
                    if "error" in response_text_obj:
                        if "message" in response_text_obj["error"]:
                            raise RuntimeError(response_text_obj["error"]["message"]) from e
                    raise e
                except json.JSONDecodeError as je:
                    raise ValueError(f"Encountered unexpected problem while decoding error: {r.text}") from je

    def upload(self, local_dir: str, repo: str, base_model: str) -> Adapter:
        if not os.path.isdir(local_dir):
            raise ValueError(f"{local_dir} does not exist or is not a directory.")

        if not os.path.isfile(os.path.join(local_dir, "adapter_config.json")):
            raise ValueError("Required file adapter_config.json is missing or is not a file.")

        if not os.path.isfile(os.path.join(local_dir, "adapter_model.bin")) and not os.path.isfile(
            os.path.join(local_dir, "adapter_model.safetensors"),
        ):
            raise ValueError("At least one of adapter_model.bin or adapter_model.safetensors is required.")

        begin_resp = self._client.http_post(
            "/v2/adapters/upload",
            json={
                "repo": repo,
                "baseModel": base_model,
            },
        )
        upload_info = _BeginAdapterUploadResponse.model_validate(begin_resp)

        print(f"Uploading adapter to repo {repo}...")
        for model_file in ("adapter_config.json", "adapter_model.bin", "adapter_model.safetensors"):
            # Fine to skip here since we've already validated the necessary set of files above.
            # TODO: consider refactoring for clarity
            if not os.path.exists(os.path.join(local_dir, model_file)):
                continue

            presigned_url = upload_info.presigned_urls[model_file]
            headers = {
                "Content-Type": "application/octet-stream",
                **upload_info.required_headers,
            }

            with open(os.path.join(local_dir, model_file), "rb") as f:
                requests.put(presigned_url, data=f, headers=headers).raise_for_status()

        complete_resp = self._client.http_put(
            "/v2/adapters/upload/",
            json={
                "uploadToken": upload_info.upload_token,
            },
        )
        print("Done!")
        return Adapter.model_validate(complete_resp)

    @staticmethod
    def _parse_id(adapter_id: str):
        segments = adapter_id.split("/", 1)
        if len(segments) != 2:
            raise ValueError("Expected adapter reference of the format <repo>/<version>.")

        return segments

    def _fetch(self, adapter_id: str):
        repo, version_tag = self._parse_id(adapter_id)
        adapter_version_endpoint = f"/v2/repos/{repo}/version/{version_tag}"

        return self._client.http_get(adapter_version_endpoint)


class _BeginAdapterUploadResponse(BaseModel):
    presigned_urls: dict[str, str] = Field(validation_alias="presignedUrls")
    upload_token: str = Field(validation_alias="uploadToken")
    required_headers: dict[str, str] = Field(default_factory=dict, validation_alias="requiredHeaders")

    @field_validator("presigned_urls")
    @classmethod
    def all_presigned_urls_present(cls, v: dict[str, str]) -> dict[str, str]:
        for k in ("adapter_config.json", "adapter_model.bin", "adapter_model.safetensors"):
            if k not in v:
                raise ValueError(f"Missing upload URL for required file {k}")
        return v
