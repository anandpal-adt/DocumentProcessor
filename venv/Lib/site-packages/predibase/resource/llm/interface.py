import concurrent.futures
import functools
import os
import re
import time
from dataclasses import dataclass, field
from pprint import pprint
from string import Formatter
from typing import Any, Dict, List, Optional, TYPE_CHECKING, Union

import deprecation
from dataclasses_json import config, dataclass_json, LetterCase
from lorax import Client as LoraxClient
from lorax.types import StreamResponse

from predibase.resource import model as mdl
from predibase.resource.connection import get_dataset
from predibase.resource.dataset import Dataset
from predibase.resource.engine import Engine
from predibase.resource.llm.prompt import PromptTemplate
from predibase.resource.llm.response import GeneratedResponse
from predibase.resource.llm.template import FinetuneTemplateCollection
from predibase.resource.llm.util import get_quantization_parameters, print_events
from predibase.resource_util import build_model
from predibase.util import load_yaml
from predibase.version import __version__

if TYPE_CHECKING:
    from predibase.pql.api import Session

_PATH_HERE = os.path.abspath(os.path.dirname(__file__))
_TEMPLATE_DIR = os.path.join(_PATH_HERE, "templates")


class HuggingFaceLLM:
    def __init__(self, session: "Session", model_name: str):
        self.session = session
        self.model_name = model_name

    def get_finetune_templates(self) -> FinetuneTemplateCollection:
        return FinetuneTemplateCollection(self)

    def deploy(
        self,
        deployment_name: str,
        engine_template: Optional[str] = None,
        hf_token: Optional[str] = None,
        auto_suspend_seconds: Optional[int] = None,
        max_input_length: Optional[int] = None,
        max_total_tokens: Optional[int] = None,
        max_batch_prefill_tokens: Optional[int] = None,
        revision: Optional[str] = None,
        quantization_kwargs: Optional[Dict[str, str]] = None,
        overwrite: Optional[bool] = False,
    ) -> "LLMDeploymentJob":
        return deploy_llm(
            session=self.session,
            deployment_name=deployment_name,
            engine_template=engine_template,
            hf_token=hf_token,
            auto_suspend_seconds=auto_suspend_seconds,
            max_input_length=max_input_length,
            max_total_tokens=max_total_tokens,
            max_batch_prefill_tokens=max_batch_prefill_tokens,
            quantization_kwargs=quantization_kwargs,
            revision=revision,
            huggingface_model_name=self.model_name,
            overwrite=overwrite,
        )

    def finetune(
        self,
        prompt_template: Optional[Union[str, PromptTemplate]] = None,
        target: Optional[str] = None,
        dataset: Optional[Union[str, Dataset]] = None,
        engine: Optional[Union[str, Engine]] = None,
        config: Optional[Union[str, Dict]] = None,
        repo: Optional[str] = None,
        epochs: Optional[int] = None,
        train_steps: Optional[int] = None,
        learning_rate: Optional[float] = None,
        lora_rank: Optional[int] = None,
    ) -> "mdl.ModelFuture":
        if isinstance(prompt_template, PromptTemplate):
            prompt_template = prompt_template.render()

        if config is None:
            config = self.get_finetune_templates().default.to_config(prompt_template=prompt_template, target=target)
            # HACK(Arnav): Temporary hack to inject the right target_modules into the config for mixtral and
            # mixtral instruct. This should be removed once the Mixtral models have a default PEFT mapping for LoRA
            # target_modules. See MLX-1680: https://linear.app/predibase/issue/MLX-1680/remove-peftlora-mixtral-hack
            # -in-the-predibase-sdk # noqa
            if (
                config.get("base_model", "")
                in {
                    "mistralai/Mixtral-8x7B-v0.1",
                    "mistralai/Mixtral-8x7B-Instruct-v0.1",
                }
                and "adapter" in config
                and config.get("adapter", {}).get("target_modules", None) is None
            ):
                config["adapter"]["target_modules"] = ["q_proj", "v_proj"]
        else:
            if isinstance(config, str):
                config = load_yaml(config)

            if not isinstance(config, dict):
                raise ValueError(f"Invalid config type: {type(config)}, expected str or dict")

        # Apply first-class training parameters.
        if train_steps is not None and epochs is not None:
            raise ValueError("Cannot specify both train_steps and epochs.")
        if train_steps is not None:
            config["trainer"]["train_steps"] = train_steps
        if epochs is not None:
            config["trainer"]["epochs"] = epochs
        if learning_rate is not None:
            config["trainer"]["learning_rate"] = learning_rate
        if lora_rank is not None:
            if lora_rank not in {8, 16, 32, 64}:
                raise ValueError("LoRA rank must be one of 8, 16, 32, or 64")
            config["adapter"]["r"] = lora_rank

        if repo is None:
            # If no repo is specified, automatically construct the repo name from the dataset and model name.
            dataset_name = dataset.name if isinstance(dataset, Dataset) else dataset
            if "/" in dataset_name:
                _, dataset_name = dataset_name.split("/")

            model_name = self.model_name
            if "/" in model_name:
                _, model_name = model_name.split("/")

            repo = f"{model_name}-{dataset_name}"

        if "/" in repo:
            repo = re.sub(r"[^A-Za-z0-9_-]", "-", repo)

        repo: "mdl.ModelRepo" = get_or_create_repo(self.session, repo)
        if dataset is None:
            # Assume the dataset is the same as the repo head
            md = repo.head().to_draft()
            md.config = config
        else:
            if isinstance(dataset, str):
                conn_name = None
                if "/" in dataset:
                    conn_name, dataset = dataset.split("/")
                dataset = get_dataset(self.session, dataset, connection_name=conn_name)
            md = repo.create_draft(config=config, dataset=dataset)

        return md.train_async(engine=engine)


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class _LLMDeployment:
    id: int = field(metadata=config(field_name="id"))
    tenant_id: int = field(metadata=config(field_name="tenantID"))
    uuid: str = field(metadata=config(field_name="uuid"))
    name: str = field(metadata=config(field_name="name"))
    description: Optional[str] = field(metadata=config(field_name="description"))
    model_name: str = field(metadata=config(field_name="modelName"))
    adapter_name: Optional[str] = field(metadata=config(field_name="adapterName"))
    num_shards: Optional[int] = field(metadata=config(field_name="numShards"))
    quantize: str = field(metadata=config(field_name="quantize"))
    deployment_status: str = field(metadata=config(field_name="deploymentStatus"))

    prompt_template: str = field(metadata=config(field_name="promptTemplate"))
    min_replicas: int = field(metadata=config(field_name="minReplicas"))
    max_replicas: int = field(metadata=config(field_name="maxReplicas"))
    created: str = field(metadata=config(field_name="created"))
    updated: str = field(metadata=config(field_name="updated"))
    created_by_user_id: Optional[int] = field(metadata=config(field_name="createdByUserID"))
    scale_down_period: int = field(metadata=config(field_name="scaleDownPeriod"))
    is_shared: bool = field(metadata=config(field_name="isShared"), default=False)
    error_text: Optional[str] = field(metadata=config(field_name="errorText"), default=None)
    dynamic_adapter_loading_enabled: bool = field(
        metadata=config(field_name="dynamicAdapterLoadingEnabled"),
        default=False,
    )


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class LLMDeploymentReadyResponse:
    name: str
    ready: bool


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class LLMDeploymentScaledResponse:
    name: str
    scaled: bool


class LLMDeployment:
    def __init__(
        self,
        session: "Session",
        name: str,
        # adapter can be a HuggingFaceLLM or mdl.Model
        adapter: Optional[Union["mdl.Model", HuggingFaceLLM]] = None,
        deployment_metadata: Optional[_LLMDeployment] = None,
    ):
        self.session = session
        self.name = name

        # Before trying to deserialize the LLM, if the response is empty,
        # then we should raise an error telling the user the LLM does not exist.
        llm_json = self.session.get_json(f"/llms/{self.name}")
        if not llm_json:
            raise RuntimeError(f"Could not find LLM {name}")

        self.data = _LLMDeployment.from_dict(llm_json) if deployment_metadata is None else deployment_metadata

        if adapter:
            if not self.data.dynamic_adapter_loading_enabled:
                raise RuntimeError(f"Base deployment {self.name} is not configured to support LoRAX")

            # TODO: (magdy) check base model compatibility for hf based adapters here
            # (Delayed now since we need to do a roundtrip to hf) (INFRA-2052)
            # Directly import `Model` here to avoid cyclic import issues.
            from predibase.resource.model import Model

            if isinstance(adapter, Model) and not self._is_adapter_compatible(adapter):
                raise RuntimeError(
                    f"base deployment {self.name} does not match the adapter's base model. "
                    f"Expected base deployment model to be: {adapter.llm_base_model_name}. "
                    f"Actual: {self.data.model_name}",
                )

        self._adapter = adapter
        self.lorax_client = LoraxClient(
            base_url=self.deployment_url,
            headers=self.session.get_headers(),
            timeout=self.session.timeout_in_seconds,
        )

    @property
    def deployment_url(self):
        return f"https://{self.session.serving_http_endpoint}/{self.session.tenant}/deployments/v2/llms/{self.name}"

    def _is_adapter_compatible(self, adapter: Optional[Union["mdl.Model", HuggingFaceLLM]]) -> bool:
        if self.data.model_name == adapter.llm_base_model_name:
            return True

        # It is possible that the base deployment's model name is not the same as the name of the base
        # model the adapter was trained on. This can happen if the adapter was trained on a model that
        # was subsequently renamed, or in the case where we're allowing users to LoRAX over dequantized
        # upscaled shared LLMs in Predibase.
        return self.session.get_json(
            "/llms/validate_adapter_compatibility",
            params={
                "deploymentBaseModelName": self.data.model_name,
                "adapterBaseModelName": adapter.llm_base_model_name,
            },
        )["compatible"]

    @property
    def adapter(self) -> Optional[Union["mdl.Model", HuggingFaceLLM]]:
        return self._adapter

    def with_adapter(self, model: Union["mdl.Model", HuggingFaceLLM]) -> "LLMDeployment":
        return LLMDeployment(
            session=self.session,
            name=self.name,
            adapter=model,
            deployment_metadata=self.data,
        )

    def _override_adapter_options(self, options: Dict[str, Union[str, float]]) -> Dict[str, Union[str, float]]:
        if self._adapter:
            if isinstance(self._adapter, HuggingFaceLLM):
                options["adapter_id"] = self._adapter.model_name
                options["adapter_source"] = "hub"
            else:
                options[
                    "adapter_id"
                ] = f"{self._adapter.uuid}/{self._adapter.best_run_id}/artifacts/model/model_weights/"
                options["adapter_source"] = "s3"
        return options

    def generate_stream(
        self,
        prompt: str,
        options: Optional[Dict[str, Union[str, float]]] = None,
    ) -> StreamResponse:
        if not options:
            options = dict()
        options = self._override_adapter_options(options)
        return self.lorax_client.generate_stream(prompt=prompt, **options)

    def generate(
        self,
        prompt: str,
        options: Optional[Dict[str, Union[str, float]]] = None,
    ) -> GeneratedResponse:
        if not options:
            options = dict()

        # Need to do this since the lorax client sets this to True by default
        if "details" not in options:
            options["details"] = False
        options = self._override_adapter_options(options)
        res = self.lorax_client.generate(prompt=prompt, **options)

        if res.details:
            return GeneratedResponse(
                prompt=prompt,
                response=res.generated_text,
                model_name=self.name,
                generated_tokens=res.details.generated_tokens,
                prefill=res.details.prefill,
                tokens=res.details.tokens,
                finish_reason=res.details.finish_reason,
                seed=res.details.seed,
                best_of_sequences=res.details.best_of_sequences,
            )

        return GeneratedResponse(
            prompt=prompt,
            response=res.generated_text,
            model_name=self.name,
        )

    def generate_batch(
        self,
        prompts: List[str],
        options: Optional[Dict[str, Union[str, float]]] = None,
    ) -> List[GeneratedResponse]:
        if not isinstance(prompts, list):
            raise ValueError("`prompts` must be a List[str]")

        options = options if isinstance(options, dict) else dict()
        resp_list = []
        with concurrent.futures.ThreadPoolExecutor() as executor:
            futures = []
            for prompt in prompts:
                future = executor.submit(self.generate, prompt=prompt, options=options)
                futures.append(future)

            for future in concurrent.futures.as_completed(futures):
                try:
                    res = future.result()
                    resp_list.append(res)
                except Exception as exc:
                    print("ERROR:", exc)

        if len(resp_list) == 0:
            raise RuntimeError("LLM failed to generate a response. Please try again later.")
        return resp_list

    def prompt_batch(
        self,
        data_list: Union[List[str], List[Dict[str, Any]]],
        temperature: float = 0.1,
        max_new_tokens: Optional[int] = 128,
        bypass_system_prompt: bool = False,
    ):
        if not isinstance(data_list, list):
            raise ValueError("`prompts` must be a List[str]")

        resp_list = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=1000) as executor:
            futures = []
            for data in data_list:
                future = executor.submit(
                    self.prompt,
                    data=data,
                    temperature=temperature,
                    max_new_tokens=max_new_tokens,
                    bypass_system_prompt=bypass_system_prompt,
                )
                futures.append(future)

            for future in concurrent.futures.as_completed(futures):
                res = None
                try:
                    res = future.result()
                except Exception as exc:
                    print("ERROR:", exc)
                finally:
                    resp_list.append(res)

        if len(resp_list) == 0:
            raise RuntimeError("LLM failed to generate a response. Please try again later.")
        return resp_list

    def prompt(
        self,
        data: Union[str, Dict[str, Any]],
        temperature: float = 0.1,
        max_new_tokens: Optional[int] = 128,
        bypass_system_prompt: bool = False,
    ) -> GeneratedResponse:
        template = self.default_prompt_template
        if template is None:
            if isinstance(data, str):
                template = "{__pbase_data_input__}"
            elif len(data) == 1:
                template = f"{{{next(iter(data))}}}"
            else:
                raise RuntimeError(
                    "Unable to interpolate multiple keys in data into prompt " "- no default_prompt_template exists",
                )

        fields_in_template = {tpl[1] for tpl in Formatter().parse(template) if tpl[1] is not None}

        if isinstance(data, str):
            if len(fields_in_template) > 1:
                raise RuntimeError(
                    "Only a single string was provided as prompt input, but there are multiple "
                    "interpolation fields in the `default_prompt_template`.",
                )

            # Coerce data into a 1-element dict matching the single interpolation field
            # in the prompt template.
            data = {next(iter(fields_in_template)): data}

        if len(fields_in_template.symmetric_difference(data.keys())) > 0:
            raise RuntimeError(
                f"Fields in prompt template do not match fields in data: "
                f"template: {fields_in_template}, data: {data.keys()}",
            )

        template = template.format(**data)

        deployment_ready = self.is_ready()
        if not deployment_ready:
            print(
                f"Target LLM deployment `{self.name}` is not active yet. This "
                f"call will block until the LLM is in a ready state.",
            )
            if self.data.is_shared:
                print("This might take a few seconds.")
            else:
                print(
                    "This might take a few minutes. Call `LLMDeployment.get_events()` "
                    "to get the status of your deployment.",
                )

            # block to wait for the LLM to spin up.
            self.wait_for_ready(timeout_seconds=1500)

        # If there is an adapter and bypass_system_prompt is True, print a warning message to the user
        # letting them know that bypass_system_prompt is being ignored.
        if self.adapter and self.data.prompt_template:
            if bypass_system_prompt:
                print(
                    "Warning: `bypass_system_prompt=True` is being ignored because the LLM deployment has an adapter."
                    " Using the system prompt with a fine-tuned model leads to suboptimal results.",
                )
            else:
                bypass_system_prompt = True

        # Wrap with the system prompt template if one exists
        if not self.adapter and self.data.prompt_template and not bypass_system_prompt:
            template = self.data.prompt_template % template

        # talk directly to the LLM, bypassing Temporal and the engines.
        return self.generate(template, options={"temperature": temperature, "max_new_tokens": max_new_tokens})

    @functools.cached_property
    def default_prompt_template(self) -> Optional[str]:
        if self._adapter:
            # Dynamic adapter deployment case
            from predibase.resource.model import Model

            if isinstance(self._adapter, Model):
                adapter: Model = self._adapter
                return adapter.config.get("prompt", {}).get("template", None)
            else:
                # Some arbitrary HuggingFace adapter is being used.
                return None
        elif self.data.adapter_name:
            # Dedicated fine-tuned deployment case
            # Adapter name is actually the path to the model weights and has the form:
            # "<model_uuid>/<model_best_run_id>/artifacts/model/model_weights/"
            model_uuid = self.data.adapter_name.split("/")[0]
            try:
                resp = self.session.get_json(f"/models/version/uuid/{model_uuid}")
                model = build_model(resp, self.session)
                return model.config.get("prompt", {}).get("template", None)
            except Exception as e:
                raise RuntimeError("Failed to get info on registered adapter") from e
        else:
            # Base OSS LLM deployment case
            return None

    def delete(self):
        print(f"Requested deletion of llm deployment: `{self.name}` ...")
        endpoint = f"/llms/{self.name}"
        self.session.delete_json(endpoint)

        while True:
            try:
                llm_deployment = self.session.get_json(endpoint)
                if llm_deployment is None:
                    print(f"Successfully deleted llm deployment: `{self.name}`")
                    break
            except Exception as e:
                raise RuntimeError(f"Error while deleting deployment `{self.name}`: {e} {type(e)}.")
            time.sleep(1.0)

    def is_ready(self) -> bool:
        try:
            self.session.get_json_serving(f"/{self.session.tenant}/deployments/v2/llms/{self.name}/health")
            return True
        except Exception:
            return False

    def wait_for_ready(self, timeout_seconds: int = 600, poll_interval_seconds: int = 5) -> bool:
        start = time.time()
        while int(time.time() - start) < timeout_seconds:
            if self.is_ready():
                return True
            time.sleep(poll_interval_seconds)
        return False

    def is_scaled(self) -> bool:
        resp = self.session.get_json(f"/llms/{self.name}/scaled")
        return LLMDeploymentScaledResponse.from_dict(resp).scaled

    @deprecation.deprecated(
        deprecated_in="2023.12.8",
        current_version=__version__,
        details="Use the LLMDeployment().get_events method instead to get information about the deployment.",
    )
    def get_status(self) -> str:
        resp = _LLMDeployment.from_dict(self.session.get_json(f"/llms/{self.name}"))
        return resp.deployment_status

    def get_events(self, detailed: Optional[bool] = False):
        detailed = str(detailed).lower()
        events = self.session.get_json(f"/llms/{self.name}/events?detailed={detailed}")
        if detailed == "false":
            print_events(events, print_header=True)
        return events


class LLMDeploymentJob:
    def __init__(self, deployment_name: str, session: "Session"):
        self._deployment_name = deployment_name
        self._uri = f"pb://jobs/deploy::{deployment_name}"
        self._session = session

    def get(self) -> LLMDeployment:
        self._session.get_llm_deployment_events_until_with_logging(
            events_endpoint=f"/llms/{self._deployment_name}/events?detailed=false",
            success_cond=lambda resp: "Ready" in [r.get("eventType", None) for r in resp.get("ComputeEvents", [])],
            error_cond=lambda resp: "Failed" in [r.get("eventType", None) for r in resp.get("ComputeEvents", [])]
            or resp.get("deploymentStatus", None) in ("failed", "deleted", "stopped"),
        )
        resp = self._session.get_json(f"/llms/{self._deployment_name}")
        return LLMDeployment(self._session, self._deployment_name, deployment_metadata=_LLMDeployment.from_dict(resp))

    def cancel(self):
        return self._session.post_json(f"/llms/{self._deployment_name}/cancel", {})


def get_or_create_repo(session: "Session", repo_name: str) -> "mdl.ModelRepo":
    return mdl.create_model_repo(session, name=repo_name, exists_ok=True)


def deploy_llm(
    session: "Session",
    deployment_name: str,
    engine_template: Optional[str] = None,
    hf_token: Optional[str] = None,
    auto_suspend_seconds: Optional[int] = None,
    max_input_length: Optional[int] = None,
    max_total_tokens: Optional[int] = None,
    max_batch_prefill_tokens: Optional[int] = None,
    quantization_kwargs: Optional[Dict[str, str]] = None,
    huggingface_model_name: Optional[str] = None,
    revision: Optional[str] = None,
    predibase_model_uri: Optional[str] = None,
    overwrite: Optional[bool] = False,
) -> "LLMDeploymentJob":
    """Deploy a base or fine-tuned LLM using specified parameters.

    Args:
        session (Session): The session object for interacting with the server.
        deployment_name (str): The name of the deployment in Predibase (e.g. 'my-llama-deployment').
        engine_template (Optional[str]): The engine template to use for deployment.
        hf_token (Optional[str]): Huggingface API token.
        auto_suspend_seconds (Optional[int]): Number of seconds before autoscaling down (0 for no autoscaling).
        max_input_length (Optional[int]): Maximum input length for the LLM.
        max_total_tokens (Optional[int]): This is the token budget that the model will have per request.
            As an example, if `max_total_tokens` is 1000 tokens and the prompt length (in tokens) is 800,
            the model will only be able to generate new 200 tokens. Since this is a per-request parameter,
            the larger this value, the larger amount each request will take in the GPU, and the less effective
            batching can be as larger values will allow for fewer batches.
        max_batch_prefill_tokens (Optional[int]): An upper bound on the number of tokens for the prefill operation.
        quantization_kwargs (Optional[Dict[str, str]]): Quantization parameters for model.
            See `get_quantization_parameters` for more details on the format.
        revision (Optional[str]): Huggingface model revision.
        huggingface_model_name (Optional[str]): Huggingface model name (e.g. 'meta-llama/Llama-2-7b-hf').
        predibase_model_uri (Optional[str]): Predibase model URI for deployment (e.g. pb://models/my_repo/2).

    Returns:
        LLMDeploymentJob: An object representing an LLM deployment job.

    Raises:
        ValueError:
            - If exactly one of 'huggingface_model_name' and 'predibase_model_uri' is not provided.
            - If 'quantization_kwargs' are not valid per 'get_quantization_parameters'.
    """
    # TODO: if model is an adapter add the base model from the adapter_config.json
    # Validate that exactly one of them is non-None
    if bool(huggingface_model_name) != bool(predibase_model_uri):
        if huggingface_model_name is not None:
            print(f"Deploying Huggingface model: {huggingface_model_name}")
        else:
            print(f"Deploying Predibase model: {predibase_model_uri}")
    else:
        raise ValueError("Exactly one of 'huggingface_model_name' and 'predibase_model_uri' must be provided.")

    # Extract quantization parameters from user-provided dictionary.
    quantize, environment_variables = get_quantization_parameters(quantization_kwargs)

    # Parse the generation parameters into customArgs.
    custom_args = [
        [arg[0], str(arg[1])]
        for arg in [
            ("--max-input-length", max_input_length or 1024),
            ("--max-total-tokens", max_total_tokens or 2048),  # TODO: User can shoot themselves in the foot here
            ("--max-batch-prefill-tokens", max_batch_prefill_tokens or 4096),
        ]
        if arg[1] is not None
    ]
    custom_args = [element for sublist in custom_args for element in sublist]

    # Put together the deployment parameters.
    auto_suspend_seconds = 0 if auto_suspend_seconds is None else auto_suspend_seconds

    model_params = {
        "name": deployment_name,
        "modelName": huggingface_model_name,
        "modelUri": predibase_model_uri,
        "engineTemplate": engine_template,
        "scaleDownPeriod": auto_suspend_seconds,
        "source": "huggingface",
        "customArgs": custom_args,
        "quantize": quantize,
        "environmentVariables": environment_variables,
        "hfToken": hf_token,
        "modelRevision": revision,
    }
    # filter None params as those can't be decoded by the server.
    model_params = {key: value for key, value in model_params.items() if value is not None}

    if overwrite:
        # Make the put request to update the deployment.
        llm_deployment_params = session.put_json(f"/llms/{deployment_name}", json=model_params)
    else:
        # Make the post request to create the deployment.
        llm_deployment_params = session.post_json("/llms", json=model_params)

    # Print information to the user.
    base_msg = "Important: This is a dedicated LLM deployment for which Predibase charges per hour of usage."
    if auto_suspend_seconds == 0:
        msg = "It will remain active until you choose to delete the deployment."
    else:
        msg = (
            f"It will remain active until the autoscaling scales it down after {auto_suspend_seconds} "
            f"seconds of inactivity. You can also delete the deployment to completely shut it down."
        )
    print(base_msg + " " + msg + "\n")
    print("Deploying the model with the following params:")
    pprint(llm_deployment_params)

    # Return LLMDeploymentJob.
    return LLMDeploymentJob(deployment_name, session)
