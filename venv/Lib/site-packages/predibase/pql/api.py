#! /usr/bin/env python
# Copyright (c) 2021 Predibase, Inc.
import datetime
import json
import logging
import os
import platform
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Thread
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import pandas as pd
import requests
import requests.exceptions
import semantic_version
import websockets
from dateutil import parser
from dateutil.parser import ParserError
from decorator import decorator
from progress_table import ProgressTable
from tqdm import tqdm
from urllib3.util import Retry
from websockets.sync.client import connect

from predibase.pql.adapter import TimeoutHTTPAdapter
from predibase.pql.utils import get_results_df, retry
from predibase.resource.llm.util import print_events
from predibase.resource.user import User
from predibase.util import get_trace_id, log_error, log_warning
from predibase.util.json import JSONType
from predibase.util.metrics import (
    formatted_time_delta,
    get_metrics_table,
    is_llm_model,
    metricsRegex,
    model_logs_directory,
)
from predibase.version import __version__

is_ci = bool(os.getenv("PREDIBASE_CI", ""))


@decorator
def warn_outdated_sdk(fn, *args, **kwargs):
    resp = fn(*args, **kwargs)
    server_release_version = resp.headers.get("X-Predibase-Release-Version", None)
    if server_release_version is not None and not is_ci:
        if server_release_version == "" or server_release_version == "staging":
            if not __version__.startswith("0.1.1+dev") and not __version__.startswith("2999"):
                log_warning(
                    "WARN: Using a post-release / prod version of the SDK in staging can lead to unexpected "
                    "behavior. Consider installing from latest master.",
                )
        else:
            server_release_semver = semantic_version.Version(server_release_version)
            sdk_semver = semantic_version.Version(__version__)
            if sdk_semver < server_release_semver and not __version__.startswith("0.1.1+dev"):
                log_warning(
                    f"WARN: Currently installed SDK is outdated. This can lead to bugs or unexpected behavior. "
                    f"Consider upgrading to the latest version. Installed: {__version__} Latest: "
                    f"{server_release_version}.",
                )

    return resp


class PQLException(RuntimeError):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


class ServerResponseError(RuntimeError):
    def __init__(self, message, code):
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass
class Session:
    connection_id: int = None
    verbose: bool = False
    url: str = None
    serving_grpc_endpoint: str = None
    serving_http_endpoint: str = None
    tenant: str = "default"
    token: str = None
    timeout_in_seconds: int = 600  # 10 min timeout to allow for long requests to /generate endpoints
    # Use separate requests object for HTTP vs Websocket requests
    requests_session = requests.Session()
    websockets_session = requests.Session()

    def __post_init__(self):
        self._token_user_cache: Optional[Tuple[str, User]] = None

    def execute(
        self,
        statement: str,
        params: Dict[str, Any] = None,
        connection_id: Optional[int] = None,
        engine_id: Optional[int] = None,
    ) -> pd.DataFrame:
        if not self.is_plan_expired():
            if not statement.endswith(";"):
                statement += ";"

            params = params or {}
            if self.verbose:
                logging.info("-- EXECUTE:")
                logging.info(statement)

            conn = connection_id or self.connection_id
            resp = self._post(
                "/queries",
                json={
                    "connectionID": conn,
                    "rawQuery": statement,
                    "queryParams": params,
                    "engineID": engine_id,
                },
            )
            data = _to_json(resp)

            start_t = time.time()
            last_t = start_t

            query_status = data.get("queryStatus")
            if query_status:
                query_id = query_status["id"]
                while not query_status.get("completed"):
                    time.sleep(0.25)
                    query_status = self.get_query_status(query_id)
                    if self.verbose:
                        last_t = show_progress(last_t)

                status = query_status.get("status")
                if status == "completed":
                    if self.verbose:
                        logging.info(f"\n-- DONE: {round(time.time() - start_t, 2)}s")
                    # TODO: do not fetch results all at once, just return metadata like rowcount
                    return self.get_results(query_id)
                else:
                    raise PQLException(
                        f"Query completed with invalid status: {status}\n"
                        f"Query:\n{query_status['rawQuery']}\n"
                        f"Error:\n{query_status['errorText']}\n",
                    )

            raise PQLException(f"Invalid response: {data}")
        else:
            raise PermissionError(
                "Queries are locked for expired plans. Contact us to upgrade.",
            )

    @property
    def user(self) -> User:
        if self._token_user_cache is None or self._token_user_cache[0] != self.token:
            self._token_user_cache = (self.token, self.get_current_user())
        return self._token_user_cache[1]

    def get_current_user(self):
        resp = self.get_json("/users/current")
        return User.from_dict({"session": self, **resp})

    def is_free_trial(self):
        return self.user.tenant.subscription.tier == "free"

    def is_plan_expired(self):
        days_remaining = self.user.tenant.subscription.days_remaining_in_plan

        if days_remaining is None:
            return False

        return days_remaining <= 0

    @retry(times=20, exceptions=(requests.exceptions.ChunkedEncodingError,))
    def get_query_status(self, query_id: int) -> str:
        resp = self._get(f"/queries/{query_id}")
        data = _to_json(resp)
        return data["queryStatus"]

    def get_results(self, query_id: int) -> pd.DataFrame:
        retry_backoff = 10  # seconds
        max_retries = 180  # 6 retries per minute, * 30 minutes
        current_retry_count = 0

        while True:
            resp = self._get(f"/queries/{query_id}/results")
            data = _to_json(resp)

            if resp.status_code == 202:
                # This means that there was an issue w/ the request, engine status was not active
                if current_retry_count >= max_retries:
                    raise PQLException(f'Unable to fetch query results, engine status: {data["engineStatus"]}')

                current_retry_count += 1
                time.sleep(retry_backoff)
                continue

            return get_results_df(data)

    def get_dataset_id(self, name: str) -> int:
        datasets = self.get_datasets()
        matched_datasets = datasets.loc[datasets["name"] == name]
        return int(matched_datasets.iloc[-1].id)

    def set_connection(self, connection_id_or_name: Union[str, int]):
        self.connection_id = self.get_connection_id(connection_id_or_name)

    def get_connections(self) -> pd.DataFrame:
        resp = self._get("/connections")
        data = _to_json(resp).get("connections")
        if data is None:
            return pd.DataFrame()
        return pd.DataFrame.from_dict(data)

    def get_connection_id(self, connection_id_or_name: Union[str, int]):
        if isinstance(connection_id_or_name, str):
            endpoint = f"/connections/name/{connection_id_or_name}"
            resp = self.get_json(endpoint)
            return int(resp["id"])
        return connection_id_or_name

    def get_datasets(self) -> pd.DataFrame:
        resp = self._get("/data/datasets/fetch/allowed_only")
        data = _to_json(resp).get("datasets")
        if data is None:
            return pd.DataFrame()
        return pd.DataFrame.from_dict(data)

    def head(self, endpoint) -> requests.Response:
        return self._http().head(self.url + endpoint, headers=self.get_headers())

    def post(self, endpoint, data: Any = None, json: Any = None, **kwargs):
        resp = self._post(endpoint, data=data, json=json, **kwargs)
        return _to_json(resp)

    def post_json(self, endpoint: str, json: Any, **kwargs):
        resp = self._post(endpoint, json=json, **kwargs)
        return _to_json(resp)

    def post_json_serving(self, endpoint: str, json: Any, **kwargs):
        resp = self._post_serving(endpoint, json=json, **kwargs)
        return _to_json(resp)

    def get_json_serving(self, endpoint: str, params: dict = None):
        resp = self._get_serving(endpoint, params=params)
        return _to_json(resp)

    def put_json(self, endpoint: str, json: Any):
        resp = self._put(endpoint, json)
        return _to_json(resp)

    def delete_json(self, endpoint: str):
        res = self._delete(endpoint)
        # Handle errors / print out the trace
        return _to_json(res)

    def get_json_until(
        self,
        endpoint: str,
        success_cond: Callable,
        error_cond: Optional[Callable] = None,
    ):
        while True:
            resp = self.get_json(endpoint)
            if success_cond(resp):
                return resp
            if error_cond is not None:
                base_err = error_cond(resp)
                if base_err:
                    err_text = resp.get("modelVersion", {}).get("errorText", "Unknown")
                    error_msg = f"{base_err}\n\n" f"Remote error:\n\n{err_text}\n"
                    raise RuntimeError(error_msg)

            time.sleep(1.0)

    def get_model_logs_urls(
        self,
        model_id: int,
    ) -> List[Dict[str, str]]:
        """Get the logs associated with this model for all runs.

        Args:
            model_id: The model ID.

        Returns:
            List of a tuple Ludwig Log Files and a presigned URL to download them.
            [{
                "filepath": "ludwig_logs/2021-05-27T18:50:13.000Z/2021-05-27T18:50:13.000Z.log",
                "url": "https://s3.amazonaws.com/2021-05-27T18:50:13.000Z/2021-05-27T18:50:13.000Z.log?AWSAccessKeyId=AKIAJ2...", # noqa E501
            }]
        """
        try:
            resp = self.get_json(
                f"/models/version/{model_id}/logs",
            )

            return resp
        except ServerResponseError as e:
            raise e

    def get_model_logs(
        self,
        model_id: int,
        sync_event: Event,
        active_run_id: Optional[str] = None,
        parent_dir: [str] = "",
    ) -> None:
        """Sync the logs associated with this model for all runs.

        Args:
            model_id: The model ID.
            sync_event: The event to use to indicate when to stop syncing logs between the client and blob storage.
            active_run_id: The run ID to sync. If None, sync all runs.
            parent_dir: The parent directory to sync the logs to. If None, sync relative to where the command is run.
        """

        def _download_logs(logfiles):
            for logfile in logfiles:
                log_file_path = os.path.join(parent_dir, logs_dir_name, logfile["filepath"])
                Path(os.path.dirname(log_file_path)).mkdir(parents=True, exist_ok=True)
                try:
                    urllib.request.urlretrieve(logfile["url"], log_file_path)
                except Exception:
                    # TODO: is there a way to safely print errors without breaking the progress table?
                    # print(f"Failed to sync {logfile['url']}: {e}")
                    pass

        logfiles = []
        moreLogsAvailable = True
        logs_dir_name = model_logs_directory(model_id)
        Path(logs_dir_name).mkdir(exist_ok=True)
        # Shorten Active Run ID to match UI and response from API
        if active_run_id is not None:
            active_run_id = active_run_id[:6]

        # When a model moves into training, there can be a considerable delay before the logs are available.
        # We need to wait for the logs to be available before we can sync them.
        # This should occur after the first batch/step has finished.
        while moreLogsAvailable and not sync_event.is_set():
            logs = self.get_model_logs_urls(model_id)
            logfiles = logs.get("logfiles", [])
            moreLogsAvailable = logs.get("moreLogsAvailable", False)

            if active_run_id is not None:
                # Filter the list of logfiles to only include the active run
                logfiles = [logfile for logfile in logfiles if f"{active_run_id}/" in logfile["filepath"]]

            if len(logfiles) > 0:
                _download_logs(logfiles)

            # The model is in a terminal state, so we can stop syncing logs
            if not moreLogsAvailable:
                break

            time.sleep(30)

    def _get_elapsed(self, curr_status: str, timeline_resp: Dict[str, Any]):
        start_time = None
        try:
            created = timeline_resp.get(curr_status, {}).get("created", None)
            start_time = parser.parse(created)
        except ParserError:
            start_time = None

        if start_time is None:
            return "{elapsed}"

        elapsed = datetime.datetime.utcnow() - start_time.replace(tzinfo=None)
        elapsed = elapsed - datetime.timedelta(microseconds=elapsed.microseconds)

        return str(elapsed)

    def _wait_until_model_ready_with_logging(
        self,
        model_id: int,
        launch_tensorboard: bool,
    ):
        launch_tb_parameter = f"{launch_tensorboard}".lower()
        runs_endpoint = f"/models/version/{model_id}?withRuns={launch_tb_parameter}"
        timeline_endpoint = f"/models/version/{model_id}/timeline"

        success_cond = lambda resp: (
            resp["modelVersion"]["status"] == "ready"
            or resp["modelVersion"]["status"] == "deploying"
            or resp["modelVersion"]["status"] == "deployed"
            or resp["modelVersion"]["status"] == "undeploying"
            or resp["modelVersion"]["status"] == "canceled"
        )
        error_cond = lambda resp: (
            (
                f"Failed to train model with status {resp['modelVersion']['status'].upper()} and error "
                f"{resp['modelVersion']['errorText']}"
            )
            if resp["modelVersion"]["status"] in {"failed"}
            else None
        )

        last_status = None

        pbar = None
        pbars = []
        training_pbar = None
        metrics_thread = None
        tensorboard_thread = None
        tensorboard_event = Event()

        def update_last_pbar(last_status: str, timeline_resp: Dict[str, Any]):
            if pbars:
                pbars[-1].bar_format = "✓ " + pbar.desc + f" {self._get_elapsed(last_status, timeline_resp)}"
                pbars[-1].close()

        while True:
            resp = self.get_json(runs_endpoint)
            timeline_resp = self.get_json(timeline_endpoint)

            if success_cond(resp):
                curr_status = resp["modelVersion"]["status"]
                update_last_pbar(last_status, timeline_resp)

                curr_status = curr_status.capitalize()
                pbar = tqdm(
                    None,
                    bar_format=curr_status.capitalize(),
                    desc=curr_status.capitalize(),
                    ncols=0,
                    miniters=1,
                )
                pbar.update()
                pbar.close()
                return resp
            if error_cond is not None:
                base_err = error_cond(resp)
                if base_err:
                    curr_status = resp["modelVersion"]["status"].capitalize()
                    pbar = tqdm(
                        None,
                        bar_format=curr_status.capitalize(),
                        desc=curr_status.capitalize(),
                        ncols=0,
                    )
                    pbar.update()
                    pbar.close()

                    err_text = resp.get("modelVersion", {}).get("errorText", "Unknown")
                    error_msg = f"{base_err}\n\n" f"Remote error:\n\n{err_text}\n"
                    raise RuntimeError(error_msg)
            curr_status = resp["modelVersion"]["status"]
            config = resp["modelVersion"]["config"]
            if curr_status != last_status:
                update_last_pbar(last_status, timeline_resp)
                last_status = curr_status
                if curr_status != "training":
                    pbar = tqdm(
                        None,
                        bar_format="  "
                        + curr_status.capitalize()
                        + f"... {self._get_elapsed(curr_status, timeline_resp)}",
                        desc=curr_status.capitalize(),
                        ncols=0,
                    )
                    pbars.append(pbar)
                elif not metrics_thread:
                    training_pbar = tqdm(
                        None,
                        bar_format=f"  Setting up training run... {self._get_elapsed(curr_status, timeline_resp)}",
                        desc=curr_status.capitalize(),
                        ncols=0,
                        leave=False,
                    )

                    start_time = datetime.datetime.now()
                    model_id = resp["modelVersion"]["id"]
                    metrics_thread = Thread(
                        target=self._stream_model_metrics,
                        args=(model_id, config, get_metrics_table(), training_pbar, start_time, 10),
                        daemon=True,
                    )
                    metrics_thread.start()

                # Stop threads if we're no longer training
                if tensorboard_thread and curr_status != "training":
                    tensorboard_event.set()
                    tensorboard_thread.join()
                    tensorboard_thread = None

            # Start a thread to sync the logs after TensorBoard so it's not blocking
            # We have to wait until the model is both training and has an active run
            if curr_status == "training":
                # Runs is not populated until the pre-training calcs are complete
                run_id = None
                runs = resp["runs"]
                if runs is not None and len(runs) > 0:
                    run_id = runs[0].get("info", {}).get("run_id", None)
                if tensorboard_thread is None and run_id is not None:
                    tensorboard_thread = Thread(
                        target=self.get_model_logs,
                        args=[model_id, tensorboard_event, run_id],
                        daemon=True,
                    )
                    tensorboard_thread.start()
            if pbars:
                pbars[-1].bar_format = (
                    "  " + curr_status.capitalize() + f"... {self._get_elapsed(curr_status, timeline_resp)}"
                )
                pbars[-1].refresh()
                pbars[-1].update()
            if training_pbar is not None and not training_pbar.disable:
                training_pbar.bar_format = (
                    f"  Setting up training run... {self._get_elapsed(curr_status, timeline_resp)}"
                )
                training_pbar.refresh()
                training_pbar.update()

            time.sleep(1.0)

    def get_llm_deployment_events_until_with_logging(
        self,
        events_endpoint: str,
        success_cond: Callable,
        error_cond: Optional[Callable] = None,
    ):
        print_header = True
        existing_events = []
        while True:
            events = self.get_json(events_endpoint)
            print_events(events=events, print_header=print_header, existing_events=existing_events)
            print_header = False
            existing_events = [(event["eventType"], event["timestamp"]) for event in events.get("ComputeEvents", [])]
            if success_cond(events):
                return
            if error_cond(events):
                return
            time.sleep(2)
        pass

    def get_llm_deployment_until_with_logging(
        self,
        endpoint: str,
        success_cond: Callable,
        error_cond: Optional[Callable] = None,
    ):
        last_status = None
        pbars = []

        while True:
            resp = self.get_json(endpoint)
            if success_cond(resp):
                if pbars:
                    pbars[-1].close()
                curr_status = resp["deploymentStatus"].capitalize()
                pbar = tqdm(None, bar_format=curr_status.capitalize(), desc=curr_status.capitalize(), ncols=0)
                pbar.update()
                pbar.close()
                return resp
            if error_cond is not None:
                base_err = error_cond(resp)
                if base_err:
                    curr_status = resp["deploymentStatus"].capitalize()
                    pbar = tqdm(None, bar_format=curr_status.capitalize(), desc=curr_status.capitalize(), ncols=0)
                    pbar.update()
                    pbar.close()

                    # TODO(hungcs): Add back when we get deployment errors
                    # err_text = resp.get("modelVersion", {}).get("errorText", "Unknown")
                    # error_msg = f"{base_err}\n\n" f"Remote error:\n\n{err_text}\n"
                    raise RuntimeError(base_err)
            curr_status = resp["deploymentStatus"]
            if curr_status != last_status:
                if pbars:
                    pbar = pbars[-1]
                    pbar.bar_format = pbar.desc + " {elapsed}"
                    pbar.close()
                last_status = curr_status
                pbar = tqdm(
                    None,
                    bar_format=curr_status.capitalize() + "... {elapsed}",
                    desc=curr_status.capitalize(),
                    ncols=0,
                )
                pbars.append(pbar)
            if pbars:
                pbars[-1].update()
            time.sleep(1.0)

    def wait_for_dataset(self, endpoint, until_fully_connected: bool = False):
        while True:
            resp = self.get_json(endpoint)
            if "lastError" in resp and resp["lastError"]:
                raise ValueError("Error waiting for dataset", resp["lastError"])
            if until_fully_connected:
                if resp["status"] == "connected":
                    return resp
            else:
                return resp
            time.sleep(1.0)

    def get_json(self, endpoint: str, params: dict = None):
        resp = self._get(endpoint, params=params)
        return _to_json(resp)

    def get_websocket(self, endpoint: str) -> websockets.sync.client.ClientConnection:
        ws_url = self.url.replace("https://", "wss://").replace("http://", "ws://")
        return connect(ws_url + endpoint, additional_headers=self.get_headers())

    def _http(self):
        """Returns a http requests configured with back off and timeout. Will timeout after 20 seconds, and will
        sleep for time based on:

        {backoff factor} * (2 ** ({number of total retries} - 1))
        """
        # see: https://findwork.dev/blog/advanced-usage-python-requests-timeouts-retries-hooks/
        retry_strategy = Retry(
            total=4,
            backoff_factor=2,
            status_forcelist=[104, 429, 500, 502, 503, 504],  # Exclude bad request
            allowed_methods=["HEAD", "GET", "PUT", "PATCH", "POST", "OPTIONS"],
        )
        http = self.requests_session if self.requests_session else requests.Session()
        adapter = TimeoutHTTPAdapter(
            max_retries=retry_strategy,
            timeout=self.timeout_in_seconds,
        )
        http.mount("https://", adapter)
        http.mount("http://", adapter)
        return http

    # def _ws(self):
    #     http = requests.Session()
    #     http.mount("wss://", adapter)
    #     http.mount("ws://", adapter)
    #     return http

    def get_headers(self):
        return {
            "Authorization": "Bearer " + self.token,
            "User-Agent": f"predibase-sdk/{__version__} ({platform.version()})",
        }

    @warn_outdated_sdk
    def _post_serving(self, endpoint: str, data: Any = None, json: Any = None, **kwargs):
        return self._http().post(
            "https://" + self.serving_http_endpoint + endpoint,
            data=data,
            json=json,
            headers=self.get_headers(),
            **kwargs,
        )

    @warn_outdated_sdk
    def _get_serving(self, endpoint: str, params: dict = None):
        return self._http().get(
            "https://" + self.serving_http_endpoint + endpoint,
            headers=self.get_headers(),
            timeout=(self.timeout_in_seconds, self.timeout_in_seconds),
        )

    @warn_outdated_sdk
    def _post(self, endpoint: str, data: Any = None, json: Any = None, **kwargs):
        return self._http().post(self.url + endpoint, data=data, json=json, headers=self.get_headers(), **kwargs)

    @warn_outdated_sdk
    def _get(self, endpoint: str, params: dict = None):
        return self._http().get(
            self.url + endpoint,
            headers=self.get_headers(),
            params=params,
            timeout=(self.timeout_in_seconds, self.timeout_in_seconds),
        )

    @warn_outdated_sdk
    def _get_ws(self, endpoint: str):
        ws_url = self.url.replace("https://", "wss://").replace("http://", "ws://")
        ws_session = self.websockets_session if self.websockets_session else requests.Session()
        return ws_session.get(ws_url + endpoint, headers=self.get_headers(), timeout=None, stream=True)

    @warn_outdated_sdk
    def _delete(self, endpoint: str):
        return self._http().delete(
            self.url + endpoint,
            headers=self.get_headers(),
            timeout=(self.timeout_in_seconds, self.timeout_in_seconds),
        )

    @warn_outdated_sdk
    def _put(self, endpoint: str, json_data: Any):
        return self._http().put(self.url + endpoint, json=json_data, headers=self.get_headers())

    def _stream_model_metrics(
        self,
        model_id: str,
        config: Dict,
        table: ProgressTable,
        training_pbar: tqdm,
        start_time: datetime,
        max_attempts: int = 10,
    ):
        ws = None
        ws_data = []
        attempts = 0

        def print_progress_bar(resp: Dict):
            if "steps" in resp["meta"] and resp["meta"]["steps"] > 0:
                table.progress_bar_active = True
                total_steps = resp["meta"]["total_steps"]
                steps = resp["meta"]["steps"]

                table._print_progress_bar(
                    steps,
                    total_steps,
                    show_before=f" {steps}/{total_steps} steps ",
                )

        while True:
            try:
                if ws is None:
                    attempts += 1
                    ws = self.get_websocket(f"/models/metrics/history/stream/{model_id}")
                resp = ws.recv()
                resp = json.loads(resp)

                if "steps" in resp["meta"] and resp["meta"]["steps"] > 0:
                    if not training_pbar.disable:
                        training_pbar.close()
                        time.sleep(0.5)  # stops race conditions with steps progress bar

                    if not table.header_printed:
                        table._print_header(top=True)

                print_progress_bar(resp)
                metrics_data = resp["data"]
                if len(metrics_data) > 0:
                    table.progress_bar_active = False
                    table._print_row()

                    ws_data.append(metrics_data)
                    run_ids = metrics_data.keys()
                    if resp["meta"]["is_hyperopt"]:
                        run_id = max(run_ids, key=lambda rid: metrics_data[rid][-1]["epoch"])
                    else:
                        run_id = next(iter(run_ids))

                    table.progress_bar_active = False
                    for epoch_data in metrics_data[run_id]:
                        # table.next_row()
                        epoch_in_data = epoch_data["epoch"]
                        table["epochs"] = epoch_in_data
                        table["time"] = formatted_time_delta(datetime.datetime.now(), start_time)

                        filtered_epoch_data = {
                            k: epoch_data[k]
                            for k in epoch_data
                            if k.startswith(("train_metrics", "validation_metrics", "test_metrics"))
                        }

                        # https://predibase.slack.com/archives/C04L07442JU/p1695772621939679?thread_ts=1695750475.580479&cid=C04L07442JU
                        if is_llm_model(config):
                            llm_filtered_epoch_data = {}
                            metrics_to_keep = ["loss", "next_token_perplexity", "perplexity", "word_error_rate", "bleu"]
                            for k in filtered_epoch_data:
                                match = metricsRegex.match(k)
                                if match:
                                    metric_name = match[3]
                                    if any(m == metric_name for m in metrics_to_keep):
                                        llm_filtered_epoch_data[k] = filtered_epoch_data[k]
                            filtered_epoch_data = llm_filtered_epoch_data

                        metrics_dict = {}
                        for full_metric_name in filtered_epoch_data.keys():
                            match = metricsRegex.match(full_metric_name)
                            if match:
                                split, feature, metric_name = match[1], match[2], match[3]
                                if feature not in metrics_dict:
                                    metrics_dict[feature] = {}
                                if metric_name not in metrics_dict[feature]:
                                    metrics_dict[feature][metric_name] = {}
                                metrics_dict[feature][metric_name][split] = filtered_epoch_data[full_metric_name]
                        last_feature = None
                        features = sorted(
                            metrics_dict.keys(),
                            key=lambda x: metrics_to_keep.index(x) if x in metrics_to_keep else 100,
                        )
                        for i, feature in enumerate(features):
                            for j, metric_name in enumerate(metrics_dict[feature]):
                                if feature != last_feature:
                                    last_feature = feature
                                    table["feature"] = feature
                                table["metric"] = metric_name
                                table["train"] = metrics_dict[feature][metric_name]["train_metrics"]
                                if "validation_metrics" in metrics_dict[feature][metric_name]:
                                    table["val"] = metrics_dict[feature][metric_name]["validation_metrics"]
                                table["test"] = metrics_dict[feature][metric_name]["test_metrics"]

                                is_final_row_in_epoch = i == len(features) - 1 and j == len(metrics_dict[feature]) - 1
                                table.next_row(split=is_final_row_in_epoch)
                    table.progress_bar_active = True
                    time.sleep(0.5)  # stops race conditions with steps progress bar
                if resp["meta"]["is_completed"]:
                    print_progress_bar(resp)
                    # Close the websocket and table connections before returning.
                    table.close()
                    ws.close()
                    return

            except websockets.exceptions.ConnectionClosedError:
                if 0 < max_attempts <= attempts:
                    print(
                        f"Model metrics streaming failed due to a connection error after {max_attempts} attempts. The "
                        f"training run is still ongoing and is NOT affected. You can monitor progress in the UI.",
                    )
                    # Close the websocket and table connections before returning.
                    table.close()
                    ws.close()
                    return

                # If we still have attempts remaining, reset the websocket object and keep going
                ws = None
                continue

            except websockets.exceptions.ConnectionClosedOK:
                return

            # TODO (hungcs): Handle specific error types
            except Exception:
                continue


def show_progress(last_t):
    t = time.time()
    if t - last_t > 1:
        sys.stdout.write("")
        sys.stdout.flush()
        return t
    return last_t


def _to_json(resp: requests.Response) -> JSONType:
    if resp.status_code != 200:
        if resp.status_code == 202:
            # Processing in progress
            return {}
        trace_id = get_trace_id(resp)
        raise ServerResponseError(
            f"Error {resp.status_code}: {_get_error(resp)}. Trace ID: {trace_id}",
            resp.status_code,
        )
    if resp.content:
        try:
            data = resp.json()
            if data:
                if type(data) is dict:
                    error_message = data.get("errorMessage")
                    if error_message:
                        # TODO: very strange to call these PQLExceptions.
                        raise PQLException(error_message)
            return data
        except requests.exceptions.JSONDecodeError:
            log_error(f"Failed to decode payload as JSON. Payload text: \n{resp.text}\n")
            raise

    return {}


def _get_error(resp):
    try:
        data = resp.json()
        if data is None:
            return "Unknown server error"
        if "error" in data:
            return data["error"]
        return resp.reason
    except requests.exceptions.JSONDecodeError:
        return f"Failed to decode payload as JSON. Payload text: \n{resp.text}\n"
