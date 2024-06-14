import os
import sys
import subprocess
import tempfile
from threading import Event, Thread
from typing import Optional

import typer
from rich import box
from rich.table import Table

# from predibase.cli_commands import run
from predibase.cli_commands import create, delete, deploy, download, finetune, list_resources, prompt, settings, upload
from predibase.cli_commands.utils import df_to_table, get_client, get_console, set_defaults_from_settings
from predibase.util.metrics import model_logs_directory
from predibase.util.settings import load_settings, save_global_settings, save_local_settings

if not os.getenv("PREDIBASE_ENABLE_TRACEBACK"):
    sys.tracebacklimit = 0

app = typer.Typer(help="Predibase CLI commands", no_args_is_help=True)

app.add_typer(create.app, name="create", help="Create Predibase resources")
app.add_typer(deploy.app, name="deploy", help="Deploy Predibase resources")
app.add_typer(delete.app, name="delete", help="Delete Predibase resources")
app.add_typer(list_resources.app, name="list", help="List Predibase resources")
app.add_typer(prompt.app, name="prompt", help="Prompt Predibase models")
app.add_typer(settings.app, name="settings", help="Configure Predibase settings")
app.add_typer(upload.app, name="upload", help="Upload to Predibase")
app.add_typer(finetune.app, name="finetune", help="Finetune a model")
app.add_typer(download.app, name="download", help="Download an artifact")


@app.command(help="Get Predibase SDK version")
def version():
    import predibase

    get_console().print(f"Predibase SDK, version: '{predibase.__version__}'")


@app.command(help="Login to Predibase using API token")
def login(
    token: Optional[str] = typer.Option(
        None,
        "--token",
        "-t",
        help="The optional api token",
        prompt="API Token",
        hide_input=True,
    ),
):
    settings = load_settings()
    settings["token"] = token
    save_global_settings(settings)
    set_defaults_from_settings(settings)

    try:
        user = get_client().get_current_user()
        get_console().print(f"\n🚀 Welcome to Predibase, '{user.username}'!")
    except Exception:
        raise RuntimeError("❌ Unable to login to Predibase! Is your API token correct?")


@app.command(help="Initialize a profile to store default model repository and engine")
def init_profile(
    repository_name: Optional[str] = typer.Option(
        None,
        "--repository-name",
        "-r",
        help="The optional model repository name",
    ),
    engine_name: Optional[str] = typer.Option(None, "--engine-name", "-e", help="The optional engine name"),
    quiet: bool = False,
):
    save_local_settings({k: v for k, v in dict(repo=repository_name or "", engine=engine_name or "").items() if v})


@app.command(help="Train a new model from a Ludwig config")
def train(
    config: Optional[str] = None,
    dataset: Optional[str] = None,
    repo: Optional[str] = None,
    engine: Optional[str] = None,
    message: Optional[str] = typer.Option(None, "--message", "-m"),
    watch: bool = False,
):
    create.model(config, dataset, repo, engine, message, watch)


@app.command(help="Predict using a trained model")
def predict(
    model_name: str = typer.Option(
        None,
        "--model-name",
        "-m",
        prompt="Name of the model to predict with",
        prompt_required=True,
        help="Name of the model to predict with",
    ),
    target: str = typer.Option(
        None,
        "--target",
        prompt="Prediction target",
        prompt_required=True,
        help="Prediction target column",
    ),
    input_csv: Optional[str] = typer.Option(
        None,
        "--input-csv",
        prompt="CSV file containing data to predict on",
        prompt_required=True,
        help="CSV file containing data to predict on",
    ),
    engine_name: Optional[str] = typer.Option(
        None,
        "--engine",
        "-e",
        prompt="Engine name",
        prompt_required=False,
        help="Engine to use for running the predict",
    ),
):
    client = get_client()

    if "/" in model_name:
        repo, version = model_name.split("/")
        model = client.get_model(repo, version)
    else:
        model = client.get_model(model_name)

    engine = client.get_engine(engine_name) if engine_name is not None else None

    import pandas as pd

    df = pd.read_csv(input_csv)

    res = model.predict(targets=target, source=df, engine=engine)

    table = Table(show_header=True, header_style="bold magenta")

    # Modify the table instance to have the data from the DataFrame
    table = df_to_table(res, table)

    # Update the style of the table
    table.row_styles = ["none", "dim"]
    table.box = box.SIMPLE_HEAD

    get_console().print(table)


@app.command(help="Launch a TensorBoard instance")
def tensorboard(
    model_id: int = typer.Option(
        None,
        "--model-id",
        "-m",
        prompt="Model ID",
        prompt_required=True,
        help="The model ID to launch a TensorBoard for",
    ),
):
    client = get_client()

    get_console().print(f"Launching TensorBoard for Model {model_id}")

    # Check if the model has logs available or will have logs available
    model_logs = client.session.get_model_logs_urls(model_id)
    if len(model_logs.get("logfiles", [])) == 0 and not model_logs.get("moreLogsAvailable", False):
        get_console().print(
            f"Model {model_id} does not have logs available, which is likely because the model failed or was terminated before logs were created. Please check model status.",  # noqa: E501
        )
        return

    with tempfile.TemporaryDirectory() as tmpdir:
        logs_dir_name = os.path.join(tmpdir, model_logs_directory(model_id))
        tensorboard_event = Event()
        logs_sync_thread = Thread(
            target=client.session.get_model_logs,
            args=[model_id, tensorboard_event, None, logs_dir_name],
            daemon=True,  # TODO: Figure out why Signal isn't working...
        )
        logs_sync_thread.start()

        subprocess.run(["tensorboard", f"--logdir={logs_dir_name}"])

        # Stop syncing logs when TensorBoard is closed
        tensorboard_event.set()
        logs_sync_thread.join()


def main():
    set_defaults_from_settings(load_settings())
    app()


if __name__ == "__main__":
    main()
