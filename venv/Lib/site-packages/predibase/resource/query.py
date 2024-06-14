# CREATE_MODEL_TEMPLATE = """
#     CREATE MODEL {model_name} FROM {dataset}
#     CONFIG {config};
# """
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import pandas as pd
from dataclasses_json import config, dataclass_json, LetterCase

from predibase.pql.api import Session
from predibase.resource.user import User


class QueryStatus(Enum):
    CREATED = "created"
    QUEUED = "queued"
    TRAINING = "training"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELED = "canceled"
    FAILED = "failed"

    def __str__(self):
        return str(self.value)

    @staticmethod
    def is_terminal_status(status: str) -> bool:
        return status in [QueryStatus.COMPLETED, QueryStatus.CANCELED, QueryStatus.FAILED]


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class Query:
    session: Session
    _id: int = field(metadata=config(field_name="id"))
    _raw_query: str = field(metadata=config(field_name="rawQuery"))
    _created: str = field(metadata=config(field_name="created"))
    _status: QueryStatus = field(metadata=config(field_name="status"))
    _results_url: Optional[str] = field(metadata=config(field_name="errorText"), default=None)
    _error_text: Optional[str] = field(metadata=config(field_name="errorText"), default=None)
    _created_by_user_id: Optional[int] = field(metadata=config(field_name="createdByUserID"), default=None)
    _status_text: Optional[str] = field(metadata=config(field_name="statusText"), default=None)
    _connection_id: Optional[int] = field(metadata=config(field_name="connectionID"), default=None)
    _completed: Optional[str] = field(metadata=config(field_name="completed"), default=None)
    _user: Optional[User] = field(metadata=config(field_name="user"), default=None)

    def __repr__(self):
        return (
            f"Query(id={self.id}, raw_query={self._raw_query}, status={self.status}, author={self.author}, "
            f"results_url={{...}}, error_text={self._error_text}, "
            f"created={self._created}, completed={self.completed})"
        )

    @property
    def id(self):
        return self._id

    @property
    def raw_query(self):
        return self._raw_query

    @property
    def created(self):
        return self._created

    @property
    def completed(self):
        return self._completed

    @property
    def author(self):
        return self._user.username if self._user else None

    @property
    def status(self):
        if QueryStatus.is_terminal_status(self._status):
            return self._status
        return self._get()["status"]

    def _get(self):
        return self.session.get_json(f"/queries/{self.id}")["queryStatus"]

    """Returns a link to a gzipped CSV file containing the results of the query."""

    def export_results(self) -> str:
        resp = self.session.get_json(f"queries/{self.id}/results/exported")
        return resp

    def get_results(self) -> pd.DataFrame:
        resp = self.session.get_json(f"/queries/{self.id}/results")
        if "errorMessage" in resp:
            raise RuntimeError(resp["errorMessage"])

        dataset = resp["dataset"]
        if "data" not in dataset:
            return pd.DataFrame()
        return pd.DataFrame(
            data=dataset["data"],
            columns=dataset["columns"],
            index=dataset.get("index"),
        )

    def cancel(self):
        self.session.post_json(f"/queries/{self.id}/cancel", {})
