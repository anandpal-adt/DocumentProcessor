from typing import Optional

import typer

from predibase.cli_commands.utils import get_client

app = typer.Typer(no_args_is_help=True)


@app.command(help="Create a Large Language Model (LLM) deployment")
def model(
    repo_name: str = typer.Option(
        None,
        "--repo-name",
        "--model-name",
        "-r",
        "-m",
        prompt="Name of the model",
        prompt_required=True,
        help="Name of the model or model repo",
    ),
    version: Optional[int] = typer.Option(
        None,
        "--version",
        "-v",
        prompt="Model version",
        prompt_required=False,
        help="Optionally specify the exact version to download, otherwise defaults to latest",
    ),
    file_name: Optional[str] = typer.Option(
        None,
        "--name",
        "-n",
        prompt="Name of the downloaded file",
        prompt_required=False,
        help="Name of the downloaded file",
    ),
    location: Optional[str] = typer.Option(
        None,
        "--location",
        "-l",
        prompt="Path to save the downloaded file to",
        prompt_required=False,
        help="Path to save the downloaded file to",
    ),
):
    client = get_client()
    m = client.get_model(repo_name, version)
    m.download(name=file_name, location=location)


if __name__ == "__main__":
    app()
