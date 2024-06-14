import concurrent.futures
from abc import abstractmethod
from typing import Dict, List, Optional, Union

import deprecation
import pandas as pd
from tabulate import tabulate

from predibase.pql.api import Session
from predibase.resource.connection import Connection
from predibase.resource.dataset import Dataset
from predibase.resource.llm import interface
from predibase.resource.llm.prompt import PromptTemplate
from predibase.version import __version__


class LlmMixin:
    session: Session

    def LLM(self, uri: str) -> Union["interface.HuggingFaceLLM", "interface.LLMDeployment"]:
        if uri.startswith("pb://deployments/"):
            return interface.LLMDeployment(self.session, uri[len("pb://deployments/") :])

        if uri.startswith("hf://"):
            return interface.HuggingFaceLLM(self.session, uri[len("hf://") :])

        raise ValueError(
            "must provide either a Hugging Face URI (hf://<...>) "
            "or a Predibase deployments URI (pb://deployments/<name>).",
        )

    def prompt_template(self, template_str: str) -> PromptTemplate:
        return PromptTemplate(template_str)

    def get_supported_llms(self):
        """Returns a list of supported HuggingFace LLMs."""
        data = self.session.get_json("/supported_llms")
        return data

    _simple_table_keys = ["name", "modelName", "deploymentStatus", "isShared"]

    def _rename_table_keys(self, key: str):
        return "deploymentName" if key == "name" else key

    def list_llm_deployments(self, active_only=False, print_as_table=True) -> Union[List[Dict], None]:
        """Fetches the current list of all LLM deployments regardless of status. Can either return this list or
        print it as a concise table. Can also optionally filter by active deployments.

        Returns: List of LLMDeployment objects or None
        """
        llms: List[Dict] = self.session.get_json(f'/llms?activeOnly={"true" if active_only else "false"}')
        if print_as_table:
            compressed_llms = [{self._rename_table_keys(k): llm[k] for k in self._simple_table_keys} for llm in llms]
            print(tabulate(compressed_llms, headers="keys", tablefmt="fancy_grid"))
        else:
            return llms

    @abstractmethod
    def get_dataset(self) -> Dataset:
        pass

    @abstractmethod
    def list_connections(self) -> List[Connection]:
        pass

    # TODO: remove this... again.
    @deprecation.deprecated(
        deprecated_in="2023.5.8",  # TODO: what was meant to be the date here
        current_version=__version__,
        details="Use the LLMDeployment().prompt method instead",
    )
    def prompt(
        self,
        templates: Union[str, List[str]],
        deployment_names: Union[str, List[str]],
        index: Optional[Union[str, Dataset]] = None,
        dataset: Optional[Union[str, Dataset]] = None,
        limit: Optional[int] = 10,
        options: Optional[Dict[str, float]] = None,
    ) -> pd.DataFrame:
        if not (index or dataset):
            # talk directly to the LLM, bypassing Temporal and the engines.
            return self.generate(templates=templates, deployment_names=deployment_names, options=options)

        # Set the connection if we have a dataset or index
        conn_id = None
        if isinstance(dataset, Dataset):
            conn_id = dataset.connection_id
        elif isinstance(index, Dataset):
            conn_id = index.connection_id
        resp = self.session.post_json(
            "/prompt",
            json={
                "connectionID": conn_id,
                "deploymentNames": [deployment_names] if isinstance(deployment_names, str) else deployment_names,
                "templates": [templates] if isinstance(templates, str) else templates,
                "options": options,
                "limit": limit,
                "indexName": index.name if isinstance(index, Dataset) else index,
                "datasetName": dataset.name if isinstance(dataset, Dataset) else dataset,
            },
            timeout=300,  # increase timeout to 5 minutes for this request
        )
        responses = [interface.GeneratedResponse(**r) for r in resp["responses"]]
        return interface.GeneratedResponse.to_pandas(responses)

    # TODO: remove this... again.
    @deprecation.deprecated(
        deprecated_in="2023.5.8",  # TODO: what was meant to be the date here
        current_version=__version__,
        details="Use the LLMDeployment().prompt method instead",
    )
    def generate(
        self,
        templates: Union[str, List[str]],
        deployment_names: Union[str, List[str]],
        options: Optional[Dict[str, float]] = None,
    ) -> pd.DataFrame:
        deployment_names = [deployment_names] if isinstance(deployment_names, str) else deployment_names
        templates = [templates] if isinstance(templates, str) else templates

        resp_list, future_to_args = [], dict()
        with concurrent.futures.ThreadPoolExecutor() as executor:
            futures = []
            for input_text in templates:
                for deployment_name in deployment_names:
                    endpoint = f"/{self.session.tenant}/deployments/v2/llms/{deployment_name}/generate"
                    post_func = self.session.post_json_serving
                    future = executor.submit(
                        post_func,
                        endpoint,
                        {
                            "inputs": input_text,
                            "parameters": options,
                        },
                    )
                    future_to_args[future] = (deployment_name, input_text)
                    futures.append(future)

            for future in concurrent.futures.as_completed(futures):
                try:
                    deployment_name, input_text = future_to_args[future]
                    res = future.result()
                    res = interface.GeneratedResponse(
                        prompt=input_text,
                        response=res["generated_text"],
                        model_name=deployment_name,
                        generated_tokens=res["details"]["generated_tokens"],
                    )
                    resp_list.append(res)
                except Exception as exc:
                    print("ERROR:", exc)
        return interface.GeneratedResponse.to_pandas(resp_list)
