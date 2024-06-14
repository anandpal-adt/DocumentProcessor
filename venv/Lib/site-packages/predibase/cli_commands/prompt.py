from typing import List, Optional

import pandas as pd
import typer
from rich import box
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from predibase.cli_commands.utils import df_to_table, get_client, get_console

app = typer.Typer(no_args_is_help=True)


@app.command(help="Query a Large Language Model (LLM)")
def llm(
    data: List[str] = typer.Argument(
        default=None,
        help="A single string or a space-separated list of <field_name>=<field_value> pairs",
    ),
    deployment_name: str = typer.Option(
        None,
        "--deployment-name",
        "-m",
        prompt="Deployment to prompt",
        prompt_required=True,
        help="The name of the deployment to prompt",
    ),
    adapter_name: Optional[str] = typer.Option(
        None,
        "--adapter-name",
        "-a",
        prompt="Optional fine-tuned adapter model",
        prompt_required=False,
        help="Reference to a fine-tuned adapter model with the same base model type",
    ),
    dataset_name: Optional[str] = typer.Option(
        None,
        "--dataset-name",
        "-d",
        prompt_required=False,
        help="Optional dataset for batch inference",
    ),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", prompt_required=False, help="Optional results limit"),
):
    if len(data) == 1:
        data = data[0]
    else:
        dd = {}
        for s in data:
            k, v = s.split("=", 1)
            dd[k] = v
        data = dd

    client = get_client()
    dep = client.LLM(f"pb://deployments/{deployment_name}")

    if adapter_name:
        if adapter_name.startswith("hf://"):
            model = client.LLM(adapter_name)
        elif adapter_name.startswith("pb://models/"):
            segments = adapter_name[len("pb://models/") :].split("/")
            version = segments[1] if len(segments) > 1 else None
            model = client.get_model(name=segments[0], version=version)
        else:
            raise ValueError(
                f"unrecognized model name {adapter_name} - "
                f"expected either a Hugging Face reference (e.g., 'hf://meta-llama/Llama-2-7b-hf') "
                f"or a Predibase model reference (e.g., pb://models/<model-repo> or "
                f"pb://models/<model-repo>/<model-version>",
            )

        dep = dep.with_adapter(model)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
    ) as progress:
        progress.add_task(description="Querying LLM...", total=None)
        response = dep.prompt(data)
        df = pd.DataFrame([response.to_dict()])

    table = Table(show_header=True, header_style="bold magenta")

    # Modify the table instance to have the data from the DataFrame
    table = df_to_table(df, table)

    # Update the style of the table
    table.row_styles = ["none", "dim"]
    table.box = box.SIMPLE_HEAD

    get_console().print(table)


if __name__ == "__main__":
    app()
