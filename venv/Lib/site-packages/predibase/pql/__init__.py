#! /usr/bin/env python
# Copyright (c) 2021 Predibase, Inc.

import logging
import os
from typing import Any, Dict, Optional

import pandas as pd

from predibase.pql.api import Session
from predibase.pql.utils import remove_trailing_slash
from predibase.util import DEFAULT_API_ENDPOINT, get_serving_endpoint, log_info
from predibase.util.settings import load_settings

_session = Session()
logger = logging.getLogger(__name__)


def start_session(gateway: str = None, token: str = None, serving_endpoint: str = None) -> Session:
    # Always starts a new session
    session = Session()
    if session.url is None:
        connect_session(session, url=gateway, serving_endpoint=serving_endpoint, token=token)

    # Return message upon successful client connection
    try:
        user = session.get_current_user()

        if user is not None:
            log_info(f"Connected to Predibase as {user}")

    except Exception as e:
        raise ValueError(f"Unable to connect to Predibase: {e}")

    _session = session
    return _session


def connect_session(
    session: Session,
    url: Optional[str] = None,
    serving_endpoint: Optional[str] = None,
    token: Optional[str] = None,
    verbose: Optional[bool] = None,
):
    settings = load_settings()
    token = token or settings.get("token")
    url = url or settings.get("endpoint")

    if url is None:
        url = os.environ.get("PREDIBASE_GATEWAY", DEFAULT_API_ENDPOINT)

    if serving_endpoint is None:
        serving_endpoint = get_serving_endpoint(url)

    url = remove_trailing_slash(url)
    serving_endpoint = remove_trailing_slash(serving_endpoint)

    if token is None:
        token = os.environ.get("PREDIBASE_API_TOKEN")
        if token is None:
            raise ValueError("Set the PREDIBASE_API_TOKEN environment variable to use the Python SDK")

    session.url = url
    session.serving_http_endpoint = serving_endpoint
    session.serving_grpc_endpoint = serving_endpoint
    session.token = token

    if not token.startswith("pb_"):
        logger.warning(
            "The `PREDIBASE_API_TOKEN` long format you're using will be deprecated on April 15, 2024. "
            "Please upgrade your token by going to the Predibase UI and generating a new one.",
        )

    session.tenant = session.get_current_user()._tenant.short_code
    if verbose is not None:
        session.verbose = verbose


def get_session(gateway: str = None, token: str = None, serving_endpoint: str = None) -> Session:
    if _session.url is None:
        connect(url=gateway, serving_endpoint=serving_endpoint, token=token)

    # Return message upon successful client connection
    try:
        user = _session.get_current_user()

        if user is not None:
            log_info(f"Connected to Predibase as {user}")

    except Exception as e:
        raise ValueError(f"Unable to connect to Predibase: {e}")

    return _session


def set_verbose(value: bool):
    _session.verbose = value


def connect(
    url: Optional[str] = None,
    serving_endpoint: Optional[str] = None,
    token: Optional[str] = None,
    verbose: Optional[bool] = None,
):
    connect_session(_session, url, serving_endpoint, token, verbose)


def set_connection(source_id):
    if _session.url is None:
        connect()
    _session.set_connection(source_id)


def get_connections():
    if _session.url is None:
        connect()
    return _session.get_connections()


def execute(statement: str, params: Dict[str, Any] = None) -> pd.DataFrame:
    if _session.url is None:
        connect()
    return _session.execute(statement, params)
