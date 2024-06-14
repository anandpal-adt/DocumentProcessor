import os
import sys
from typing import Optional, Union

from predibase.connection_mixin import ConnectionMixin
from predibase.dataset_mixin import DatasetMixin
from predibase.deployment_mixin import DeploymentMixin
from predibase.engine_mixin import EngineMixin
from predibase.llm_mixin import LlmMixin
from predibase.model_mixin import ModelMixin
from predibase.permission_mixin import PermissionMixin
from predibase.pql import start_session
from predibase.pql.api import Session
from predibase.query_mixin import QueryMixin


class PredibaseClient(
    QueryMixin,
    ConnectionMixin,
    DatasetMixin,
    EngineMixin,
    ModelMixin,
    DeploymentMixin,
    PermissionMixin,
    LlmMixin,
):
    def __init__(self, session: Optional[Session] = None, gateway: str = None, token: str = None):
        self._session = session or start_session(gateway, token)
        if not os.getenv("PREDIBASE_ENABLE_TRACEBACK"):
            ipython = None
            try:
                ipython = get_ipython()  # noqa
            except NameError:
                # We're not in a notebook; use standard tracebacklimit instead.
                # IMPORTANT: setting this to a value <= 1 breaks colab horribly and has no effect in Jupyter.
                sys.tracebacklimit = 0

            # https://stackoverflow.com/a/61077368
            if ipython:

                def hide_traceback(
                    exc_tuple=None, filename=None, tb_offset=None, exception_only=False, running_compiled_code=False
                ):
                    etype, value, tb = sys.exc_info()
                    return ipython._showtraceback(etype, value, ipython.InteractiveTB.get_exception_only(etype, value))

                ipython.showtraceback = hide_traceback

    @property
    def session(self) -> Session:
        return self._session

    def set_connection(self, connection: Union[str, int]):
        """This method sets the default connection to use for any method requiring a connection argument.

        :param connection: The desired connection name or id
        """
        self.session.set_connection(connection)
