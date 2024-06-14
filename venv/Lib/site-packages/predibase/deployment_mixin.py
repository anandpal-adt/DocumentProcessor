from typing import Any, Dict, List, Optional, Union

import pandas as pd

from predibase.pql.api import PQLException, Session
from predibase.resource import model as mdl
from predibase.resource.deployment import Deployment
from predibase.util import spinner


class DeploymentMixin:
    session: Session

    @spinner(name="Create Deployment")
    def create_deployment(
        self,
        name: str,
        model: "mdl.Model",
        engine_name: Optional[str] = None,
        replace: bool = False,
        exists_ok: bool = False,
        comment: Optional[str] = None,
    ) -> Union[pd.DataFrame, Deployment]:
        """Creates a deployment.

        :param str name: Name of deployment.
        :param Model model: Model object to deploy.
        :param str engine_name: Optional serving engine name to deploy to (Default None).
        :param bool replace: Optional flag replace a deployment (default False).
        :param bool exists_ok: Optional flag to only create deployment if not exists (default False).
        :param str comment: Optional comment for the deployment (default None).
        :return: pandas DataFrame or list of Deployment objects.
        """
        if self.session.is_free_trial():
            raise PermissionError(
                "Deployments are locked during the trial period. Contact us to upgrade or if you would like a demo",
            )
        elif self.session.is_plan_expired():
            raise PermissionError(
                "Deployments are locked for expired plans. Contact us to upgrade or if you would like a demo",
            )
        else:
            conditions = []
            if replace:
                conditions.append("OR REPLACE")
            conditions.append("DEPLOYMENT")
            if exists_ok:
                conditions.append("IF NOT EXISTS")
            conditions.append(f'"{name}"')

            if engine_name is not None:
                conditions.append(f'TO "{engine_name}"')
            conditions.append(f'USING "{model.repo.name}" VERSION {model.version}')
            if comment is not None:
                conditions.append(f"COMMENT '{comment}'")

            query = f"CREATE {' '.join(conditions)}"
            result = self.session.execute(query)
            deployments = self._format_deployment_result_df(result)

            if len(deployments) == 1:
                return Deployment.from_dict({"session": self.session, **deployments[0]})
            else:
                raise ValueError(
                    "Error creating deployment",
                )

    @spinner(name="Delete Deployment")
    def delete_deployment(
        self,
        name: str,
        if_exists: bool = False,
        df: bool = False,
    ) -> Union[pd.DataFrame, List[Deployment]]:
        """Deletes a deployment.

        :param str name: required name of deployment.
        :param bool if_exists: Optional flag to only delete deployment if it exists (default False).
        :param bool df: Optional flag to return the result as a dataframe (Default False).
        :return: pandas DataFrame or list of Deployment objects.
        """
        conditions = []
        conditions.append("DROP DEPLOYMENT")
        if if_exists:
            conditions.append("IF EXISTS")
        conditions.append(f'"{name}"')

        query = f"{' '.join(conditions)}"
        try:
            result = self.session.execute(query)
            deployments = self._format_deployment_result_df(result)
            if df:
                return pd.DataFrame(deployments)
            return [Deployment.from_dict({"session": self.session, **x}) for x in deployments]
        except PQLException as e:
            print(
                f"Deleting deployment {name} failed. If this was"
                "an LLM delpoyment use the `llm.delete()` method instead.",
            )
            raise e

    def list_deployments(
        self,
        deployment_name_pattern: Optional[str] = None,
        repo_name: Optional[str] = None,
        model_version: Optional[str] = None,
        df: bool = False,
    ) -> Union[pd.DataFrame, List[Deployment]]:
        """Lists (and optionally filters) Deployments.

        :param str deployment_name_pattern: Optional filter for deployment name (Default None).
        :param str engine_name: Optional filter by engine name (Default None).
        :param str repo_name: Optional filter by model repository name (Default None).
        :param str model_version: Optional filter by model version (Default None).
        :param bool df: Optional flag to return the result as a dataframe (Default False).
        :return: pandas DataFrame or list of Deployment objects.
        """
        endpoint = "/deployments"
        deployment_results = self.session.get_json(endpoint)
        assert isinstance(deployment_results, list)

        if deployment_name_pattern:
            deployment_results = [d for d in deployment_results if deployment_name_pattern in d["Name"]]

        if repo_name:
            deployment_results = [d for d in deployment_results if repo_name == d["HeadVersion"]["RepoName"]]

        if model_version:
            deployment_results = [
                d for d in deployment_results if model_version == str(d["HeadVersion"]["ModelVersion"])
            ]

        deployments = self._format_deployment_result(deployment_results)
        if df:
            return pd.DataFrame(deployments)
        return [Deployment.from_dict({"session": self.session, **x}) for x in deployments]

    def _format_deployment_result(self, result: List[Dict]) -> List[Dict[str, Any]]:
        deployments = [
            {
                "session": self.session,
                "name": d["Name"],
                "deploymentUrl": d["URL"],
                "deploymentVersion": d["HeadVersion"]["VersionNumber"],
                "engineName": d["HeadVersion"]["EngineName"],
                "modelName": f'{d["HeadVersion"]["RepoName"]}',
                "modelVersion": str(d["HeadVersion"]["ModelVersion"]),
                "comment": d["HeadVersion"]["Comment"],
                "errorText": d["HeadVersion"]["ErrorText"],
            }
            for d in result
        ]
        return deployments

    def _format_deployment_result_df(self, result: pd.DataFrame) -> List[Dict[str, Any]]:
        deployments = [
            {
                "session": self.session,
                "name": row["name"],
                "deploymentUrl": row["url"],
                "deploymentVersion": row["head_version_number"],
                "engineName": row["head_version_engine_name"],
                "modelName": row["head_version_model_name"],
                "modelVersion": row["head_version_model_version"],
                "comment": row["head_version_comment"],
                "errorText": row["head_version_error_text"],
            }
            for row in result.to_dict(orient="records")
        ]
        return deployments

    def get_deployment(self, name: str) -> Deployment:
        """Gets a deployment.

        :param str name: Name of deployment.
        :return: Deployment object.
        """
        deployments = self.list_deployments()
        if len(deployments) > 0:
            for d in deployments:
                if d.name == name:
                    return d
        raise ValueError(f"Deployment '{name}' not found.")
