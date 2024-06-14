from typing import Optional

import typer

from predibase.cli_commands.utils import get_client, get_console

app = typer.Typer(no_args_is_help=True)


@app.command()
def dataset(
    file_path: str = typer.Option(
        None,
        "--file-path",
        "-f",
        prompt="Path of file to upload",
        prompt_required=True,
        help="Path of the dataset file to be uploaded",
    ),
    name: Optional[str] = typer.Option(
        None,
        "--name",
        "-n",
        prompt="Dataset name",
        prompt_required=False,
        help="Name of the dataset to be created - will be auto-generated if left unset",
    ),
):
    client = get_client()

    get_console().print(f"Uploading file at {file_path} as a dataset...")

    ds = client.upload_dataset(file_path, name)

    get_console().print(f"Created dataset {ds.name}")


if __name__ == "__main__":
    app()
