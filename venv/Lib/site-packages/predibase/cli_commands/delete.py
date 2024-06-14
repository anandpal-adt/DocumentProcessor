import typer

from predibase.cli_commands.utils import get_client, get_console

app = typer.Typer(no_args_is_help=True)


@app.command(help="Delete Large Langage Model (LLM) deployments")
def llm(
    deployment_name: str = typer.Option(
        None,
        "--deployment-name",
        "-d",
        prompt="Deployment name",
        prompt_required=True,
        help="Name of the deployment",
    ),
):
    client = get_client()

    get_console().print(f"Deleting LLM with deployment name: {deployment_name}")

    client.LLM(f"pb://deployments/{deployment_name}").delete()
    get_console().print("Delete request sent.")


if __name__ == "__main__":
    app()
