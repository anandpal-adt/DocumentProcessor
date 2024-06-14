from __future__ import annotations

import concurrent.futures
import json
import queue
import types
from typing import TYPE_CHECKING

from lorax import AsyncClient as AsyncLoraxClient
from lorax import Client as LoraxClient

from predibase.config import DeploymentConfig
from predibase.resources.deployment import Deployment

if TYPE_CHECKING:
    from predibase import Predibase


class Deployments:
    def __init__(self, client: Predibase):
        self._client = client
        self._session = client._session

    # TODO: nameoruuid for get deployment endpoint
    def get(self, deployment_ref: str) -> Deployment:
        dep = self._client.http_get(f"/v2/deployments/{deployment_ref}")["data"]
        return Deployment.model_validate(dep)

    def client(
        self,
        deployment_ref: str | Deployment,
        force_bare_client: bool = False,
        _timeout_in_seconds: int = 600,
        _max_session_retries: int = 2,
    ) -> LoraxClient:
        if isinstance(deployment_ref, Deployment):
            deployment_ref = deployment_ref.name

        if "/" in deployment_ref:
            raise ValueError(
                f"Deployment name {deployment_ref} appears to be invalid. Are you providing a Hugging "
                f"Face path by accident? See https://docs.predibase.com/user-guide/inference/models for "
                f"a list of available deployments.",
            )

        url = (
            f"https://{self._session.serving_http_endpoint}/{self._session.tenant}/deployments/v2/llms/"
            f"{deployment_ref}"
        )

        c = LoraxClient(
            base_url=url,
            headers=self._session.get_headers(),
            timeout=_timeout_in_seconds,
            max_session_retries=_max_session_retries,
        )

        if force_bare_client:
            return c

        c._generate = c.generate
        c.generate = types.MethodType(_make_generate(self._client, deployment_ref), c)

        c._generate_stream = c.generate_stream
        c.generate_stream = types.MethodType(_make_generate_stream(self._client, deployment_ref), c)

        return c

    def async_client(self, deployment_ref: str, _timeout_in_seconds: int = 600) -> AsyncLoraxClient:
        if isinstance(deployment_ref, Deployment):
            deployment_ref = deployment_ref.name

        url = (
            f"https://{self._session.serving_http_endpoint}/{self._session.tenant}/deployments/v2/llms/"
            f"{deployment_ref}"
        )

        return AsyncLoraxClient(
            base_url=url,
            headers=self._session.get_headers(),
            timeout=_timeout_in_seconds,
        )

    def create(
        self,
        *,
        name: str,
        config: dict | DeploymentConfig,
        description: str | None = None,
    ) -> Deployment:

        if isinstance(config, DeploymentConfig):
            config = dict(config)

        self._client.http_post(
            "/v2/deployments",
            json={
                "name": name,
                "description": description,
                "params": json.dumps(config),
            },
        )

        self._session.get_llm_deployment_events_until_with_logging(
            events_endpoint=f"/llms/{name}/events?detailed=false",
            success_cond=lambda resp: "Ready" in [r.get("eventType", None) for r in resp.get("ComputeEvents", [])],
            error_cond=lambda resp: "Failed" in [r.get("eventType", None) for r in resp.get("ComputeEvents", [])]
            or resp.get("deploymentStatus", None) in ("failed", "deleted", "stopped"),
        )

        return self.get(name)

    def list(self, *, type: str | None = None) -> list[Deployment]:
        endpoint = "/v2/deployments"

        if type is not None:
            type = type.lower()
            if type not in ("serverless", "dedicated"):
                raise ValueError("Type filter must be one of `serverless` or `dedicated`")

            endpoint = f"{endpoint}?type={type}"

        resp = self._client.http_get(endpoint)
        return [Deployment.model_validate(d) for d in resp["data"]]

    def delete(self, deployment_ref: str | Deployment):
        if isinstance(deployment_ref, Deployment):
            deployment_ref = deployment_ref.name

        self._client.http_delete(f"/v2/deployments/{deployment_ref}")


def _make_generate(pb: Predibase, deployment_ref: str):
    def _lorax_generate(self, *args, **kwargs):
        def _generate_thread(q: queue.Queue):
            try:
                q.put_nowait({"type": "generate", "data": self._generate(*args, **kwargs)})
            except Exception as e:
                q.put_nowait({"type": "generate", "exception": e})

        def _status_thread(q: queue.Queue):
            try:
                q.put_nowait({"type": "status", "status": pb.deployments.get(deployment_ref).status})
            except Exception:
                # q.put_nowait({"type": "status", "exception": e})
                pass

        q = queue.Queue()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            pool.submit(_generate_thread, q)
            pool.submit(_status_thread, q)

            while True:
                resp = q.get()
                if resp["type"] == "generate":
                    if "exception" in resp:
                        raise resp["exception"]

                    return resp["data"]

                if resp["type"] == "status":
                    if resp["status"] not in ("ready", "updating"):
                        print(
                            f"Deployment {deployment_ref} is still spinning up. Your prompt may take longer than "
                            f"normal to execute.\n",
                        )

    return _lorax_generate


def _make_generate_stream(pb: Predibase, deployment_ref: str):
    def _lorax_generate_stream(self, *args, **kwargs):
        def _generate_thread(q: queue.Queue):
            try:
                for r in self._generate_stream(*args, **kwargs):
                    q.put_nowait({"type": "generate", "data": r})

                q.put_nowait(None)
            except Exception as e:
                q.put_nowait({"type": "generate", "exception": e})

        def _status_thread(q: queue.Queue):
            try:
                q.put_nowait({"type": "status", "status": pb.deployments.get(deployment_ref).status})
            except Exception as e:
                q.put_nowait({"type": "status", "exception": e})

        q = queue.Queue()
        resp_seen = False
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            pool.submit(_generate_thread, q)
            pool.submit(_status_thread, q)

            while True:
                resp = q.get()

                if resp is None:
                    break

                if resp["type"] == "generate":
                    if "exception" in resp:
                        raise resp["exception"]

                    resp_seen = True
                    yield resp["data"]
                    continue

                if resp["type"] == "status" and not resp_seen:
                    if resp["status"] not in ("ready", "updating"):
                        print(
                            f"Deployment {deployment_ref} is still spinning up. Your prompt may take longer than "
                            f"normal to execute.\n",
                        )

    return _lorax_generate_stream
