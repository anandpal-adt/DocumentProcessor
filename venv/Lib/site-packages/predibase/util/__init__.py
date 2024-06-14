import os
import traceback
from decimal import Decimal

import yaml
from rich.console import Console
from requests import Response

DEFAULT_API_ENDPOINT = "https://api.app.predibase.com/v1"

DEBUG = os.environ.get("PREDIBASE_DEBUG") is not None


_console = Console()
_error_console = Console(stderr=True, style="bold red")
_info_console = Console(stderr=True, style="bold blue")
_warning_console = Console(stderr=True, style="bold magenta")


def load_yaml(yaml_fp):
    with open(yaml_fp) as f:
        return yaml.safe_load(f)


def spinner(name):
    def decorator(fn):
        def wrap_fn(*args, **kwargs):
            with _console.status(f"{name}...", spinner="material"):
                try:
                    res = fn(*args, **kwargs)
                    _console.print(f"✅ {name}")
                    return res
                except Exception as e:
                    _console.print(f"💥 {name}")
                    raise

        return wrap_fn

    return decorator


def get_trace_id(response: Response):
    # Gets the trace ID from the http response, if it exists.
    return response.headers.get("b3", "0-0-0").split("-")[0]


def get_error_message(e: Exception) -> str:
    return f"{type(e).__name__}: {str(e)}" if not DEBUG else traceback.format_exc()


# TODO: rename to avoid confusion between loggging vs. printing.
def log_info(v: str):
    _info_console.print(v)


def log_error(v: str):
    _error_console.print(v)


def log_warning(v: str):
    _warning_console.print(v)


def get_url(session, endpoint: str) -> str:
    if "localhost" in session.url:
        root_url = "http://localhost:8000"
    else:
        url = session.url
        if "api." in url:
            url = url.replace("api.", "").replace("/v1", "")
        root_url = url
    from urllib.parse import urljoin

    return urljoin(root_url, endpoint)


def get_serving_endpoint(gateway_endpoint: str) -> str:
    # Repliace scheme and the rest of the endpoint
    serving_endpoint = gateway_endpoint.replace("https://", "").replace("http://", "").replace("/v1", "")
    # Replace the first part ("api") with "serving"
    serving_endpoint_parts = serving_endpoint.split(".")
    serving_endpoint_parts[0] = "serving"
    serving_endpoint = ".".join(serving_endpoint_parts)
    return serving_endpoint


class JSONFloat(float):
    def __repr__(self):
        return format(Decimal(self), "f")


class ConfigEncoder:
    def decimalize(self, val):
        if isinstance(val, dict):
            return {k: self.decimalize(v) for k, v in val.items()}

        if isinstance(val, (list, tuple)):
            return type(val)(self.decimalize(v) for v in val)

        if isinstance(val, float):
            return JSONFloat(val)

        return val
