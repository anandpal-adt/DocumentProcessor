from typing import Any, Dict, List, Optional, Union

import pandas as pd

from predibase.connection_mixin import ConnectionMixin
from predibase.resource.query import Query


class QueryMixin(ConnectionMixin):
    def query_history(
        self,
        offset: int = 0,
        limit: int = 10,
        raw_query: Optional[str] = None,
        df: bool = False,
    ) -> Union[pd.DataFrame, List[Query]]:
        """
        :param offset
        :param limit
        :param raw_query: query text to search on
        :param df: Whether to return pandas dataframe or list of objects
        :return: Pandas dataframe or list of modelRepos
        """
        endpoint = f"/queries?offset={offset}&limit={limit}"
        if raw_query:
            endpoint += f"&searchKeys[]=rawQuery&searchVals[]={raw_query}"
        resp = self.session.get_json(endpoint)
        queries = [x for x in resp["queryHistory"]]
        if df:
            return pd.DataFrame(queries)
        return [Query.from_dict({"session": self.session, **x}) for x in queries]

    # def get_queries_by_text(self, raw_text: str) -> List[Query]:
    #     resp = self.get(f"/queries?searchKeys[]=rawText,searchVals[]={raw_text}?limit=999999999")
    #     return [Query({"session": self.session, **q}) for q in resp["queryHistory"]]

    def set_query_connection(self, connection_name: str):
        conn = self.get_connection(connection_name)
        self.session.connection_id = conn.id

    def execute_query(
        self,
        query: str,
        params: Optional[Dict[str, Any]] = None,
        connection_name: Optional[str] = None,
    ) -> pd.DataFrame:
        if not self.session.is_plan_expired():
            if connection_name:
                self.set_query_connection(connection_name)
            return self.session.execute(query, params)
        else:
            raise PermissionError(
                "Queries are locked for expired plans. Contact us to upgrade.",
            )
