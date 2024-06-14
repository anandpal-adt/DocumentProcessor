from typing import Optional

import typer

from predibase.cli_commands.utils import get_client, get_console, get_dataset, get_engine, get_or_create_repo, load_yaml
from predibase.resource.model import ModelRepo

app = typer.Typer(no_args_is_help=True)


@app.command()
def model(
    config: Optional[str] = None,
    dataset: Optional[str] = None,
    repo: Optional[str] = None,
    engine: Optional[str] = None,
    message: Optional[str] = typer.Option(None, "--message", "-m"),
    watch: bool = False,
):
    config = load_yaml(config)
    engine = get_engine(engine)
    repo: ModelRepo = get_or_create_repo(repo)

    if dataset is None:
        # Assume the dataset is the same as the repo head
        md = repo.head().to_draft()
        md.config = config
    else:
        dataset = get_dataset(dataset)
        md = repo.create_draft(config=config, dataset=dataset)

    if message is not None:
        md.description = message

    result = md.train_async(engine=engine)
    get_console().print("Started model training")
    if watch:
        try:
            result.get()
        except KeyboardInterrupt:
            cancel = typer.confirm("Do you wish to cancel the current model training job?")
            if cancel:
                result.cancel()


@app.command()
def engine(
    name: str = typer.Option(
        None,
        "--name",
        "-n",
        prompt="Name of the engine",
        prompt_required=True,
        help="Name of the engine",
    ),
    template: Optional[str] = typer.Option(
        None,
        "--template",
        "-t",
        prompt="Engine template",
        prompt_required=False,
        help="Template for the engine to be created",
    ),
):
    client = get_client()

    get_console().print(f"Creating engine {name} from template {template}")
    client.create_engine(name, template)


if __name__ == "__main__":
    app()
