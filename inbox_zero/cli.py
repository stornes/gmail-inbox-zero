"""Click CLI for gmail-inbox-zero."""

import click


@click.group()
def cli():
    """Gmail Inbox Zero, a self-learning rule engine."""


@cli.command()
@click.option("--dry-run/--no-dry-run", default=True, help="Preview without executing.")
@click.option("--max-results", default=500, help="Max messages per rule query.")
@click.option("--verbose", "-v", is_flag=True, help="Show per-message details.")
def run(dry_run: bool, max_results: int, verbose: bool):
    """Evaluate rules and execute actions."""
    mode = "DRY RUN" if dry_run else "LIVE"
    click.echo(f"[{mode}] Running inbox-zero (max_results={max_results})")

    if verbose:
        click.echo("Verbose output enabled.")

    # Placeholder: engine + actions integration happens when WP2 is merged.
    click.echo("Engine not yet connected. Nothing to evaluate.")


@cli.command()
def stats():
    """Show action log statistics."""
    click.echo("stats not yet connected to storage")


@cli.command()
def rules():
    """List all rules with confidence and hit counts."""
    click.echo("rules listing not yet connected to storage")


@cli.command()
def review():
    """Show flagged-for-review messages."""
    raise NotImplementedError("review command is not yet implemented")


@cli.command()
def propose():
    """Show proposed rules awaiting approval."""
    raise NotImplementedError("propose command is not yet implemented")


@cli.command()
def migrate():
    """Convert legacy hardcoded filters to rules.json."""
    raise NotImplementedError("migrate command is not yet implemented")


@cli.command()
def feedback():
    """Run the feedback cycle manually."""
    raise NotImplementedError("feedback command is not yet implemented")


if __name__ == "__main__":
    cli()
