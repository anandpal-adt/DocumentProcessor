# pylint: disable=W0611,W0613
from typing import Any

import pandas as pd
from IPython.core.magic import cell_magic, Magics, magics_class, needs_local_scope

from predibase import pql


@magics_class
class PQLMagics(Magics):
    def __init__(self, shell):
        super().__init__(shell)

    @needs_local_scope
    @cell_magic("pql")
    def pql(self, line: str, cell: str, local_ns: Any = None) -> pd.DataFrame:
        return pql.execute(cell, params=local_ns)


def _setup_pql_notebook(ipython: Any) -> None:
    ipython.register_magics(PQLMagics)
