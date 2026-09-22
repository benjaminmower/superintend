"""Typer entrypoints only; no business logic lives here."""

from __future__ import annotations

import datetime as dt

import typer

from tracker_agent import flags as flags_module
from tracker_agent.config import load_settings, load_sheet_config
from tracker_agent.sources.base import TrackerSource
from tracker_agent.sources.gsheets.client import GspreadClient
from tracker_agent.sources.gsheets.raw import (
    AiColumnWriteError,
    NoWeeklyTabFoundError,
    classify_tab,
    is_changelog_tab,
    latest_weekly_tab,
)
from tracker_agent.sources.gsheets.source import GSheetsSource

app = typer.Typer(no_args_is_help=True)


def _resolve_source(project: str | None) -> tuple[TrackerSource, str, GspreadClient]:
    """The only place that resolves the active adapter (guardrail 0: feature
    code never imports a source directly). Also returns the raw gspread
    client since `inspect` needs tab-level access `TrackerSource` doesn't expose.
    """
    sheet_config = load_sheet_config()

    spreadsheet = sheet_config.spreadsheets[0]
    if project:
        matches = [s for s in sheet_config.spreadsheets if s.project_id == project]
        if not matches:
            typer.echo(f"No spreadsheet with project_id={project!r} in sheet.yaml.", err=True)
            raise typer.Exit(1)
        spreadsheet = matches[0]

    sheet_id = spreadsheet.sheet_id()
    if not sheet_id:
        typer.echo(f"{spreadsheet.sheet_id_env} is not set (check .env).", err=True)
        raise typer.Exit(1)

    client = GspreadClient(sheet_id)
    source = GSheetsSource(client, sheet_config)
    return source, spreadsheet.project_id, client


@app.command()
def inspect(
    project: str = typer.Option(None, help="project_id from sheet.yaml; defaults to the first."),
) -> None:
    """List tabs, classify each, and report the latest weekly tab. Read-only."""
    source, project_id, client = _resolve_source(project)
    sheet_config = load_sheet_config()

    typer.echo(f"# {project_id}\n")

    for tab in client.tab_names():
        role = classify_tab(tab, sheet_config)
        if role == "other" and is_changelog_tab(client, tab, sheet_config):
            role = "changelog"
        typer.echo(f"{tab!r}: {role}")

    try:
        latest = latest_weekly_tab(client, sheet_config, start_year=dt.date.today().year)
        typer.echo(f"\nLatest weekly tab: {latest}")
    except NoWeeklyTabFoundError as exc:
        typer.echo("\nNo weekly tab found.", err=True)
        raise typer.Exit(1) from exc

    result = source.items(project_id)
    groups = {item.group for item in result.items}
    typer.echo(f"Header row: found; {len(result.items)} items across {len(groups)} subcontractors")
    for warning in result.warnings:
        typer.echo(f"  warning: {warning.location}: {warning.message}", err=True)

    changes = source.history(project_id)
    changelog_names = [t for t in client.tab_names() if is_changelog_tab(client, t, sheet_config)]
    if changelog_names:
        typer.echo(f"Change log: {len(changes)} rows in {changelog_names[0]!r}")
    else:
        typer.echo("Change log: not found", err=True)


@app.command()
def flag(
    project: str = typer.Option(None, help="project_id from sheet.yaml; defaults to the first."),
    dry_run: bool = typer.Option(False, "--dry-run"),
    no_llm: bool = typer.Option(False, "--no-llm", help="Run the rules only; skip next actions."),
    as_of: str = typer.Option(
        None, "--as-of", help="Evaluate as of this date (YYYY-MM-DD) instead of today."
    ),
) -> None:
    """Phase 1: AI Flag + AI Next Action on the latest weekly tab."""
    source, project_id, _client = _resolve_source(project)
    settings = load_settings()
    today = dt.date.fromisoformat(as_of) if as_of else dt.date.today()

    try:
        report = flags_module.run_flag(
            source, project_id, settings, today=today, dry_run=dry_run, use_llm=not no_llm
        )
    except AiColumnWriteError as exc:
        typer.echo(str(exc), err=True)
        typer.echo(
            "Add the AI Flag / AI Next Action headers yourself, right of NOTES on the "
            "latest weekly tab, then re-run.",
            err=True,
        )
        raise typer.Exit(1) from exc
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc

    for note in report.skipped:
        typer.echo(f"note: {note}", err=True)

    typer.echo(f"# {project_id} as of {today}\n")
    for rule in flags_module.RULE_ORDER:
        if rule in report.counts:
            emoji, label = flags_module.RULE_TEXT[rule]
            typer.echo(f"{emoji} {label}: {report.counts[rule]}")

    if report.write_result is not None:
        verb = "would write" if dry_run else "wrote"
        typer.echo(f"\n{verb} {report.write_result.written} cells:")
        for d in report.write_result.diff:
            typer.echo(f"  {d.item_id} {d.field}: {d.old!r} -> {d.new!r}")


@app.command()
def brief(dry_run: bool = typer.Option(False, "--dry-run")) -> None:
    """Phase 2: rewrite the AI Brief tab."""
    typer.echo("Not implemented yet: Phase 2 (see SPEC.md).", err=True)
    raise typer.Exit(1)


@app.command()
def report(dry_run: bool = typer.Option(False, "--dry-run")) -> None:
    """Phase 3: draft (or send) the weekly report email."""
    typer.echo("Not implemented yet: Phase 3 (see SPEC.md).", err=True)
    raise typer.Exit(1)


@app.command(name="roll-week")
def roll_week(apply: bool = typer.Option(False, "--apply")) -> None:
    """Phase 3 (optional): duplicate the latest weekly tab for the coming week."""
    typer.echo("Not implemented yet: Phase 3 (see SPEC.md).", err=True)
    raise typer.Exit(1)


@app.command()
def ingest() -> None:
    """Phase 4: index Drive docs + tracker history for RAG."""
    typer.echo("Not implemented yet: Phase 4 (see SPEC.md).", err=True)
    raise typer.Exit(1)


@app.command()
def ask(question: str) -> None:
    """Phase 4: answer a question from indexed project documents and tracker history."""
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
def backtest() -> None:
    """Phase 5: replay flag rules against change-log history."""
    typer.echo("Not implemented yet: Phase 5 (see SPEC.md).", err=True)
    raise typer.Exit(1)


@app.command()
def stats() -> None:
    """Phase 5: print metrics from the run log."""
    typer.echo("Not implemented yet: Phase 5 (see SPEC.md).", err=True)
    raise typer.Exit(1)


if __name__ == "__main__":
    app()
