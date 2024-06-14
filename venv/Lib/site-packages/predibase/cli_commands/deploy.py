import re
from typing import Optional

import typer

from predibase.cli_commands.utils import get_client, get_console

app = typer.Typer(no_args_is_help=True)


@app.command(help="Create a Large Language Model (LLM) deployment")
def llm(
    deployment_name: str = typer.Option(
        None,
        "--deployment-name",
        "-d",
        prompt="Deployment name",
        prompt_required=True,
        help="Name of the deployment",
    ),
    model_name: str = typer.Option(
        None,
        "--model-name",
        "-m",
        prompt="Model to deploy",
        prompt_required=True,
        help="Name of the model, e.g., hf://meta-llama/Llama-2-7b-hf",
    ),
    engine_template: Optional[str] = typer.Option(
        None,
        "--engine-template",
        "-e",
        prompt="Engine name",
        prompt_required=False,
        help="Optional engine template to provision for hosting the model",
    ),
    max_input_length: Optional[str] = typer.Option(
        None,
        "--max-input-length",
        prompt="Max input length of the LLM.",
        prompt_required=False,
        help="Optional max input length parameter that the LLM can accept.",
    ),
    auto_suspend_secs: Optional[int] = typer.Option(
        None,
        "--auto-suspend",
        "-s",
        prompt="Auto suspend (seconds)",
        prompt_required=False,
        help="Optional auto suspend time in seconds.  Set to zero to disable auto scaling down.",
    ),
    hf_token: Optional[str] = typer.Option(
        None,
        "--hf-token",
        prompt="HuggingFace API token",
        prompt_required=False,
        help="Optional HuggingFace API token for private models",
    ),
    wait: Optional[bool] = typer.Option(
        None,
        "--wait",
        prompt="Whether to wait until deployment finishes",
        prompt_required=False,
        help="If set, the deploy command will not return until the deployment process finishes",
    ),
):
    # raise ValueError if name is not lower case alphanumeric characters or '-'
    if re.match(r"^[a-z0-9-]+$", deployment_name) is None:
        raise ValueError("name must be lower case alphanumeric characters or '-'")

    client = get_client()

    get_console().print("Deploying an LLM with the following parameters:")
    get_console().print("\tdeployment_name:", deployment_name)
    get_console().print("\tmodel_name:", model_name)
    if engine_template:
        get_console().print("\tengine_template:", engine_template)
    if auto_suspend_secs:
        get_console().print("\tauto_suspend_seconds:", auto_suspend_secs)

    if model_name.startswith("hf://"):
        job = client.LLM(model_name).deploy(
            deployment_name,
            engine_template=engine_template,
            auto_suspend_seconds=auto_suspend_secs,
            hf_token=hf_token,
            max_input_length=max_input_length,
        )
    elif model_name.startswith("pb://models/"):
        segments = model_name[len("pb://models/") :].split("/")
        version = segments[1] if len(segments) > 1 else None
        model = client.get_model(name=segments[0], version=version)
        job = model.deploy(deployment_name)
    else:
        raise ValueError(
            f"unrecognized model name {model_name} - "
            f"expected either a Hugging Face reference (e.g., 'hf://meta-llama/Llama-2-7b-hf') "
            f"or a Predibase model reference (e.g., pb://models/<model-repo> or "
            f"pb://models/<model-repo>/<model-version>",
        )

    get_console().print("Deploy request sent.")

    if wait:
        get_console().print("Waiting for deploy to complete...")
        job.get()
        get_console().print("Deploy process finished.")


if __name__ == "__main__":
    app()
