from __future__ import annotations

import logging
import os
import platform
from http import HTTPStatus
from typing import Any

import requests
import websockets
from urllib3 import Retry
from websockets.sync.client import connect

from predibase._errors import PredibaseError, PredibaseResponseError, PredibaseServerError, warn_outdated_sdk
from predibase.pql import start_session, get_session
from predibase.pql.adapter import TimeoutHTTPAdapter
from predibase.resources.adapters import Adapters
# from predibase.resources.completions import Completions
from predibase.resources.datasets import Datasets
from predibase.resources.deployments import Deployments
from predibase.resources.finetuning_jobs import Finetuning
# from predibase.resources.models import Models
from predibase.resources.repos import Repos
from predibase.util import get_serving_endpoint
from predibase.util.settings import load_settings
# from predibase.util.json import JSONType
from predibase.util.util import remove_suffix
from predibase.version import __version__

_DEFAULT_API_GATEWAY = "https://api.app.predibase.com"

logger = logging.getLogger(__name__)


class Predibase:
    def __init__(
        self,
        *,
        api_token: str | None = None,
    ):
        """Create a new Predibase client instance.

        If not provided, optional params will be set by, in order of precedence:
        * Current environment variables
        * Hard-coded defaults

        :param api_token: The authentication token for the Predibase API.
        """
        # TODO: this is still rather buggy in notebooks.
        # if os.getenv("PREDIBASE_DEBUG") != "":
        #     ipython = None
        #     try:
        #         ipython = get_ipython()  # noqa
        #     except NameError:
        #         # We're not in a notebook; use standard tracebacklimit instead.
        #         # IMPORTANT: setting this to a value <= 1 breaks colab horribly and has no effect in Jupyter.
        #         sys.tracebacklimit = 0
        #
        #     # https://stackoverflow.com/a/61077368
        #     if ipython:
        #
        #         def hide_traceback(
        #             exc_tuple=None, filename=None, tb_offset=None, exception_only=False, running_compiled_code=False
        #         ):
        #            etype, value, tb = sys.exc_info()
        #            return ipython._showtraceback(etype, value, ipython.InteractiveTB.get_exception_only(etype, value))
        #
        #         ipython.showtraceback = hide_traceback

        api_token = api_token or os.environ.get("PREDIBASE_API_TOKEN") or load_settings().get("token")
        api_gateway = os.environ.get("PREDIBASE_GATEWAY") or _DEFAULT_API_GATEWAY
        api_gateway = remove_suffix(api_gateway, "/v1")
        api_gateway = remove_suffix(api_gateway, "/v2")

        if not api_token:
            raise PredibaseError(
                "An api_token must either be explicitly provided or set via the PREDIBASE_API_TOKEN "
                "environment variable.",
            )

        if not api_gateway:
            raise PredibaseError("PREDIBASE_GATEWAY cannot be empty.")

        if not api_gateway.startswith("https://") and not api_gateway.startswith("http://"):
            logger.info(
                f"No HTTP scheme provided for PREDIBASE_GATEWAY (got: {api_gateway}), defaulting to `https://`.",
            )
            api_gateway = f"https://{api_gateway}"

        serving_endpoint = get_serving_endpoint(api_gateway)

        self.api_token = api_token
        self.api_gateway = api_gateway
        self.serving_http_endpoint = serving_endpoint

        self._session = start_session(self.api_gateway, self.api_token, self.serving_http_endpoint)

        self.adapters = Adapters(self)
        # self.completions = Completions(self)
        self.datasets = Datasets(self)
        self.deployments = Deployments(self)
        # self.models = Models(self._session)
        self.repos = Repos(self)
        self.finetuning = Finetuning(self)

    @property
    def default_headers(self) -> dict[str, str]:
        return {
            "Authorization": "Bearer " + self.api_token,
            "User-Agent": f"predibase-sdk/{__version__} ({platform.version()})",
        }

    @property
    def _http(self):
        """Returns a http requests configured with back off and timeout. Will timeout after 10 minutes, and will
        sleep for time based on:

        {backoff factor} * (2 ** ({number of total retries} - 1))
        """
        # see: https://findwork.dev/blog/advanced-usage-python-requests-timeouts-retries-hooks/
        retry_strategy = Retry(
            total=4,
            backoff_factor=2,
            status_forcelist=[104, 429, 500, 502, 503, 504],  # Exclude bad request
            allowed_methods=["HEAD", "GET", "PUT", "PATCH", "POST", "OPTIONS"],
            raise_on_status=False,  # Get the last response (which may contain useful error info) instead of unhelpful
            # retry error (e.g., "too many 500 responses").
        )
        session = self._session if self._session else get_session()
        http = session.requests_session
        adapter = TimeoutHTTPAdapter(
            max_retries=retry_strategy,
            timeout=600,
        )
        http.mount("https://", adapter)
        http.mount("http://", adapter)
        return http

    def http_get(self, endpoint: str, params: dict | None = None, **kwargs) -> dict:
        @warn_outdated_sdk
        def do():
            return self._http.get(self.api_gateway + endpoint, headers=self.default_headers, params=params, **kwargs)

        return _to_json(do())

    def http_post(self, endpoint: str, data: Any | None = None, json: Any | None = None, **kwargs) -> dict:
        @warn_outdated_sdk
        def do():
            return self._http.post(
                self.api_gateway + endpoint,
                data=data,
                json=json,
                headers=self.default_headers,
                **kwargs,
            )

        return _to_json(do())

    def http_delete(self, endpoint: str) -> dict:
        @warn_outdated_sdk
        def do():
            return self._http.delete(self.api_gateway + endpoint, headers=self.default_headers)

        return _to_json(do())

    def http_put(self, endpoint: str, json: Any | None) -> dict:
        @warn_outdated_sdk
        def do():
            return self._http.put(self.api_gateway + endpoint, json=json, headers=self.default_headers)

        return _to_json(do())

    def listen_websocket(self, endpoint: str, max_attempts: int = 10) -> websockets.Data:
        ws_url = self.api_gateway.replace("https://", "wss://").replace("http://", "ws://")

        attempts = 0
        conn = None
        while attempts < max_attempts:
            attempts += 1
            try:
                conn = connect(ws_url + endpoint, additional_headers=self.default_headers)

                while True:
                    try:
                        yield conn.recv()
                    except websockets.exceptions.ConnectionClosedError:
                        break
                    except websockets.exceptions.ConnectionClosedOK:
                        return

            finally:
                if conn is not None:
                    conn.close()

        raise RuntimeError("TODO populate")


def _to_json(resp: requests.Response) -> dict:
    if 200 <= resp.status_code < 400:
        return {} if resp.status_code == 204 else payload_json(resp)

    if 400 <= resp.status_code < 500:
        payload = payload_json(resp)
        raise RuntimeError(
            f"Bad request. Response status code {resp.status_code}. Error: " f"{payload.get('error', 'Unknown')}",
        )

    if 500 <= resp.status_code < 600:
        payload = payload_json(resp)
        raise PredibaseServerError(
            f"Server error. Response status code {resp.status_code}. Error: " f"{payload.get('error', 'Unknown')}",
        )

    raise PredibaseResponseError(f"Unexpected response code: {resp.status_code}", resp.status_code)


def payload_json(r) -> dict:
    try:
        data = r.json()

        if not isinstance(data, dict):
            # New APIs should always return a JSON object.
            raise PredibaseResponseError(
                f"Invalid response payload - expected a JSON object, got {data}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

        return data

    except requests.exceptions.JSONDecodeError as e:
        raise PredibaseResponseError(
            f"Failed to decode payload as JSON. Response status code: "
            f"{r.status_code}. Raw payload text: \n{r.text}. Error: {e}\n",
            r.status_code,
        ) from e
