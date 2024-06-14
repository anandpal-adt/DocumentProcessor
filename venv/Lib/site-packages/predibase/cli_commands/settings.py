from typing import Any

import typer
from rich import print

from predibase.util.settings import load_global_settings, load_local_settings, load_settings, save_global_settings

app = typer.Typer(no_args_is_help=True)


@app.command(help="Show global settings")
def show_global():
    settings = load_global_settings()
    print(settings)


@app.command(help="Show local settings")
def show_local():
    settings = load_local_settings()
    print(settings)


@app.command(help="Show local and global settings")
def show_all():
    settings = load_settings()
    print(settings)


@app.command(help="Set default repository name")
def set_repo(repository_name: str = typer.Argument(..., help="The model repository name")):
    _set_setting("repo", repository_name)


@app.command(help="Set default engine name")
def set_engine(engine_name: str = typer.Argument(..., help="The engine name")):
    _set_setting("engine", engine_name)


@app.command(help="Set api token")
def set_api_token(token: str = typer.Argument(..., help="The api token")):
    _set_setting("token", token)


@app.command(help="Set default endpoint url")
def set_endpoint(endpoint: str = typer.Argument(..., help="The endpoint url")):
    _set_setting("endpoint", endpoint)


def _set_setting(setting: str, value: Any):
    settings = load_global_settings()
    settings[setting] = value
    save_global_settings(settings)
