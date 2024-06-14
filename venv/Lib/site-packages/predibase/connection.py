#! /usr/bin/env python
# Copyright (c) 2021 Predibase, Inc.

import os
from typing import Optional, Sequence

import pandas as pd

from predibase.pql.api import Session

# See: https://www.python.org/dev/peps/pep-0249/
from predibase.util import DEFAULT_API_ENDPOINT


def connect(
    url: Optional[str] = None,
    token: Optional[str] = None,
    connection: Optional[str] = None,
    verbose: bool = False,
):
    if url is None:
        url = os.environ.get("PREDIBASE_GATEWAY", DEFAULT_API_ENDPOINT)

    if token is None:
        token = os.environ.get("PREDIBASE_API_TOKEN")
        if token is None:
            raise ValueError("Set the PREDIBASE_API_TOKEN environment variable to use the Python SDK")

    session = Session(url=url, token=token, verbose=verbose)
    if connection:
        session.set_connection(connection)
    return Connection(session)


class Connection:
    def __init__(self, session: Session):
        self._cursor = Cursor(session)

    def close(self):
        pass

    def commit(self):
        pass

    def rollback(self):
        pass

    def cursor(self):
        return self._cursor


class Cursor:
    def __init__(self, session: Session):
        self._session = session
        self._results_df = pd.DataFrame()
        self.arraysize = 10
        self._offset = 0

    @property
    def description(self):
        pass

    @property
    def rowcount(self):
        return len(self._results_df)

    def close(self):
        pass

    def execute(self, statement: str, *params) -> pd.DataFrame:
        # TODO: implement params
        self._results_df = self._session.execute(statement)
        self._offset = 0

    def executemany(self, statement: str, seq_of_parameters: Sequence):
        for params in seq_of_parameters:
            self.execute(statement, params)

    def fetchone(self):
        df = self._results_df[self._offset : self._offset + 1]
        self._offset += 1
        return df

    def fetchmany(self, size=None):
        size = size or self.arraysize
        df = self._results_df[self._offset : self._offset + size]
        self._offset += size
        return df

    def fetchall(self):
        df = self._results_df[self._offset :]
        self._offset = len(self._results_df)
        return df

    def setinputsizes(self, sizes):
        pass

    def setoutputsize(self, size, column):
        pass
