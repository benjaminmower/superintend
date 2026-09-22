"""Typer entrypoints only; no business logic lives here."""

from __future__ import annotations

import typer

from tracker_agent.config import load_settings
from tracker_agent.gspread_client import GspreadClient
from tracker_agent.sheets import NoWeeklyTabFoundError, latest_weekly_tab

app = typer.Typer(no_args_is_help=True)


@app.command()
def inspect(demo: bool = typer.Option(True, help="Use SHEET_ID_DEMO instead of SHEET_ID.")) -> None:
    """List tabs, headers, row count, and 3 sample rows. Read-only.

    Sample rows are printed to the terminal only, never saved to disk.
    """
    settings = load_settings()
    sheet_id = settings.sheet.id_demo if demo else settings.sheet.id
    if not sheet_id:
        var = "SHEET_ID_DEMO" if demo else "SHEET_ID"
        typer.echo(f"{var} is not set (check .env).", err=True)
        raise typer.Exit(1)

    client = GspreadClient(sheet_id)

    try:
        latest = latest_weekly_tab(client)
        typer.echo(f"Latest weekly tab: {latest}\n")
    except NoWeeklyTabFoundError:
        typer.echo("No weekly tab (\"wk M/D\") found yet.\n", err=True)

    for tab in client.tab_names():
        headers = client.headers(tab)
        rows = client.read_rows(tab)
        typer.echo(f"# {tab} ({len(rows)} rows)")
        for header in headers:
            typer.echo(f"  - {header}")
        typer.echo("  sample rows:")
        for row in rows[:3]:
            typer.echo(f"    {row}")


@app.command()
def summarize(dry_run: bool = typer.Option(False, "--dry-run")) -> None:
    """Phase 1: write short summaries to the AI summary column."""
    typer.echo("Not implemented yet: Phase 1 (see SPEC.md).", err=True)
    raise typer.Exit(1)


@app.command()
def flag(dry_run: bool = typer.Option(False, "--dry-run")) -> None:
    """Phase 2: flag at-risk rows."""
    typer.echo("Not implemented yet: Phase 2 (see SPEC.md).", err=True)
    raise typer.Exit(1)


@app.command()
def digest(dry_run: bool = typer.Option(False, "--dry-run")) -> None:
    """Phase 3: send (or print) the weekly digest email."""
    typer.echo("Not implemented yet: Phase 3 (see SPEC.md).", err=True)
    raise typer.Exit(1)


@app.command()
def ingest() -> None:
    """Phase 4: index Drive docs for RAG."""
    typer.echo("Not implemented yet: Phase 4 (see SPEC.md).", err=True)
    raise typer.Exit(1)


@app.command()
def ask(question: str) -> None:
    """Phase 4: answer a question from indexed project documents."""
    typer.echo("Not implemented yet: Phase 4 (see SPEC.md).", err=True)
    raise typer.Exit(1)


@app.command()
def watch() -> None:
    """Phase 4: poll the Ask tab and answer new questions."""
    typer.echo("Not implemented yet: Phase 4 (see SPEC.md).", err=True)
    raise typer.Exit(1)


@app.command()
def eval() -> None:
    """Phase 5: run the RAG eval set."""
    typer.echo("Not implemented yet: Phase 5 (see SPEC.md).", err=True)
    raise typer.Exit(1)


@app.command()
def stats() -> None:
    """Phase 5: print metrics from the run log."""
    typer.echo("Not implemented yet: Phase 5 (see SPEC.md).", err=True)
    raise typer.Exit(1)


if __name__ == "__main__":
    app()
