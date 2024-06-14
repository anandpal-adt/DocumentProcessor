import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

import pandas as pd
import yaml
from rich.console import Console
from rich.table import Table

from predibase import PredibaseClient
from predibase.pql.api import Session
from predibase.resource.dataset import Dataset
from predibase.resource.engine import Engine
from predibase.resource.model import ModelRepo
from predibase.util import DEFAULT_API_ENDPOINT, get_serving_endpoint


@dataclass
class Defaults:
    repo: Optional[str] = None
    engine: Optional[str] = None
    session: Optional[Session] = None


console = Console()
defaults: Defaults = Defaults()


def get_console() -> Console:
    return console


def get_client() -> PredibaseClient:
    return PredibaseClient(session=defaults.session)


def sanitize_engine_name(name: str) -> str:
    return name.replace("/", "-")


def get_or_create_repo(repo_name: Optional[str] = None) -> ModelRepo:
    repo_name = repo_name or defaults.repo
    if repo_name is None:
        raise ValueError("Repo name is required")
    return get_client().create_model_repo(name=repo_name, exists_ok=True)


def get_repo(repo_name: Optional[str] = None) -> ModelRepo:
    repo_name = repo_name or defaults.repo
    if repo_name is None:
        raise ValueError("Repo name is required")
    return get_client().get_model_repo(name=repo_name)


def get_engine(engine_name: Optional[str] = None) -> Engine:
    engine_name = engine_name or defaults.engine
    if engine_name is None:
        raise ValueError("Engine name is required")
    return get_client().get_engine(name=engine_name)


def get_dataset(dataset_name: Optional[str] = None) -> Dataset:
    if dataset_name is None:
        raise ValueError("Dataset name is required")

    conn_name = None
    if "/" in dataset_name:
        conn_name, dataset_name = dataset_name.split("/")
    return get_client().get_dataset(dataset_name=dataset_name, connection_name=conn_name)


def set_defaults_from_settings(settings: Dict[str, Any]):
    url = settings.get("endpoint")
    if url is None:
        url = os.environ.get("PREDIBASE_GATEWAY", DEFAULT_API_ENDPOINT)

    serving_endpoint = get_serving_endpoint(url)

    global defaults
    defaults = Defaults(
        repo=settings.get("repo"),
        engine=settings.get("engine"),
        session=Session(token=settings.get("token"), url=url, serving_http_endpoint=serving_endpoint),
    )


def load_yaml(fname: str) -> Dict[str, Any]:
    with open(fname) as f:
        return yaml.safe_load(f)


def df_to_table(
    pandas_dataframe: pd.DataFrame,
    rich_table: Table,
    show_index: bool = True,
    index_name: Optional[str] = None,
) -> Table:
    """Convert a pandas.DataFrame obj into a rich.Table obj.

    Args:
        pandas_dataframe (DataFrame): A Pandas DataFrame to be converted to a rich Table.
        rich_table (Table): A rich Table that should be populated by the DataFrame values.
        show_index (bool): Add a column with a row count to the table. Defaults to True.
        index_name (str, optional): The column name to give to the index column. Defaults to None, showing no value.
    Returns:
        Table: The rich Table instance passed, populated with the DataFrame values.
    """

    if show_index:
        index_name = str(index_name) if index_name else ""
        rich_table.add_column(index_name)

    for column in pandas_dataframe.columns:
        rich_table.add_column(str(column))

    for index, value_list in enumerate(pandas_dataframe.values.tolist()):
        row = [str(index)] if show_index else []
        row += [str(x) for x in value_list]
        rich_table.add_row(*row)

    return rich_table
