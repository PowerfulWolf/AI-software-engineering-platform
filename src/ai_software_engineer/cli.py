"""Command-line delivery adapter for ai-software-engineer."""

from typing import Annotated

import typer

from ai_software_engineer import __version__

app = typer.Typer(
    name="ase",
    help="Run the artifact-driven AI software engineering platform.",
    add_completion=False,
    no_args_is_help=False,
    pretty_exceptions_show_locals=False,
)


def _version_callback(show_version: bool) -> None:
    if show_version:
        typer.echo(f"ase {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def cli(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show the installed version and exit.",
        ),
    ] = False,
) -> None:
    """Run the artifact-driven AI software engineering platform."""
    del version
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


def main() -> None:
    """Execute the console entry point."""
    app()


if __name__ == "__main__":
    main()
