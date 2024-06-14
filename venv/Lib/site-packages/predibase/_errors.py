import logging
import os
from warnings import warn

import semantic_version
from decorator import decorator

from predibase.version import __version__

logger = logging.getLogger(__name__)


class PredibaseError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class PredibaseResponseError(PredibaseError):
    def __init__(self, message: str, code: int):
        super().__init__(message)
        self.code = code


class PredibaseServerError(PredibaseError):
    def __init__(self, message: str):
        super().__init__(message)


class FinetuningError(PredibaseError):
    def __init__(self, message: str):
        super().__init__(message)


is_ci = bool(os.getenv("PREDIBASE_CI", ""))


@decorator
def warn_outdated_sdk(fn, *args, **kwargs):
    resp = fn(*args, **kwargs)
    server_release_version = resp.headers.get("X-Predibase-Release-Version", None)
    if server_release_version is not None and not is_ci:
        if server_release_version == "" or server_release_version == "staging":
            if not __version__.startswith("0.1.1+dev") and not __version__.startswith("v2999"):
                warn(
                    "Using a post-release / prod version of the SDK in staging can lead to unexpected behavior. "
                    "Consider installing from latest master."
                )
        else:
            server_release_semver = semantic_version.Version(server_release_version)
            sdk_semver = semantic_version.Version(__version__)
            if sdk_semver < server_release_semver and not __version__.startswith("0.1.1+dev"):
                warn(
                    f"Currently installed SDK is outdated. This can lead to bugs or unexpected behavior. "
                    f"Consider upgrading to the latest version. Installed: {__version__} Latest: "
                    f"{server_release_version}."
                )

    return resp
