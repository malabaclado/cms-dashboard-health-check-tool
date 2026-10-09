# Client Dashboard Automation — interactive CLI entry point.
# Orchestrates 4 steps: (1) check today's data, (2) run health check + cookie
# validation, (3) send team email summary, (4) draft engineer notification email.
# Each step can be skipped/confirmed interactively, or auto-confirmed with --auto
# for unattended (e.g. Task Scheduler) runs. Actual work is delegated to
# helper_functions.py; this file only handles CLI flow and rich console output.

# Import Packages
import argparse
import json
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich import box

import config  # DEMO MODE (portfolio only): MOCK_MODE and simulate_failures
from helper_functions import (
    validate_cookies,
    send_email_summary,
    perform_health_check,
    send_mail_to_engineers
)

# Initialize console for styled output
console = Console()


def display_banner():
    """Display welcome banner with styled title."""
    banner = Panel(
        "[bold cyan]Client Dashboard Automation[/bold cyan]\n"
        "[dim]Health Check & Email Summary Tool[/dim]",
        box=box.ROUNDED,
        padding=(1, 2),
        border_style="cyan"
    )
    console.print(banner)

    # ======================================================================
    # DEMO MODE (portfolio only): not part of the original tool.
    # Tell the viewer this run is not live: data is read from mock_input/.
    # The real fetch logic in get_data.py is unchanged and runs when MOCK_MODE is off.
    # ======================================================================
    if config.MOCK_MODE:
        console.print("[yellow]Running in demo mode: data read from mock_input/[/yellow]")


def check_health_check_status():
    """Check if today's content and importer CSV files exist in daily_check/csv/."""
    console.print("\n[bold blue]Step 1:[/bold blue] Checking health check data status...\n")

    # Filenames are produced by save_csv() in write_data.py using this same
    # "%Y%m%d" compact date format — must stay in sync with that function.
    today_compact = datetime.now().strftime("%Y%m%d")
    today_date = datetime.now().strftime("%Y-%m-%d")
    csv_dir = Path('data/daily_check/csv')

    content_csv = csv_dir / f"{today_compact}_content-check.csv"
    importer_csv = csv_dir / f"{today_compact}_importer-check.csv"

    content_exists = content_csv.exists()
    importer_exists = importer_csv.exists()

    if content_exists:
        console.print(f"[green]✓[/green] Content check data found for [bold]{today_date}[/bold]")
    else:
        console.print(f"[yellow]⚠[/yellow] No content check data found for [bold]{today_date}[/bold]")

    if importer_exists:
        console.print(f"[green]✓[/green] Importer check data found for [bold]{today_date}[/bold]")
    else:
        console.print(f"[yellow]⚠[/yellow] No importer check data found for [bold]{today_date}[/bold]")

    # Only report "data exists" when BOTH files are present, so a partial
    # run (e.g. content succeeded but importer failed) is treated as incomplete.
    if content_exists and importer_exists:
        return content_csv
    else:
        return None


def confirm_health_check(data_exists: bool, auto: bool = False):
    """Prompt user to confirm health check with context.

    default flips based on data_exists: if no data exists yet today, default
    to running it (yes); if data already exists, default to NOT re-running (no).
    When auto=True (unattended mode), that same default is returned immediately
    without prompting.
    """
    console.print("\n[bold blue]Step 2:[/bold blue] Health Check & Cookie Validation\n")

    info = Panel(
        "[dim]This will:[/dim]\n"
        "• Validate cookies (prompt for refresh if stale)\n"
        "• Fetch content and importer data from the CMS dashboard\n"
        "• Parse and save results to daily_check/ (txt and csv files)",
        title="[bold cyan]Health Check & Cookie Validation[/bold cyan]",
        border_style="cyan"
    )
    console.print(info)

    default = not data_exists

    if data_exists:
        message = "Health check data already exists. Would you like to [bold]re-run[/bold] it?"
    else:
        message = "Would you like to [bold]run[/bold] the health check now?"

    if auto:
        console.print(f"[dim]{message} (auto: {'yes' if default else 'no'})[/dim]")
        return default

    return Confirm.ask(message, default=default)


def load_and_validate_cookies():
    """Load and validate cookies with progress indicator."""
    console.print("[dim]Loading and validating cookies...[/dim]")

    try:
        # The spinner only wraps the file read (fast, non-interactive).
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            progress.add_task("Loading cookies...", total=None)
            with open('data/cookies.json', 'r') as f:
                cookies = json.load(f)

        # Progress spinner is stopped before this call, since stale cookies
        # trigger an interactive input() prompt that would corrupt a live spinner.
        validate_cookies(cookies)
        console.print("[green]✓[/green] Cookies validated successfully\n")
        return True
    except FileNotFoundError:
        console.print("[red]✗[/red] Cookies file not found. Please check cookies.json\n")
        return False
    except json.JSONDecodeError:
        console.print("[red]✗[/red] Cookies file is corrupted. Please check JSON format\n")
        return False
    except Exception as e:
        console.print(f"[red]✗[/red] Cookie validation failed: {str(e)}\n")
        return False


def perform_health_check_flow():
    """Execute health check with visual feedback.

    Delegates to helper_functions.perform_health_check(), which fetches,
    parses, and saves both the content and importer checks. Any failure
    inside that call (network, parsing, or file I/O) is caught here as a
    generic Exception, since perform_health_check() doesn't distinguish
    failure types itself.
    """
    console.print("[dim]Running health checks...[/dim]\n")

    try:
        perform_health_check()
        console.print("\n[green]✓[/green] Health checks completed successfully\n")
        return True
    except Exception as e:
        console.print(f"\n[red]✗[/red] Health check failed: {str(e)}\n")
        return False


def confirm_email_summary(auto: bool = False):
    """Prompt user about email summary."""
    console.print("\n[bold blue]Step 3:[/bold blue] Email Summary\n")

    info = Panel(
        "[dim]This will:[/dim]\n"
        "• Extract dashboard summary data\n"
        "• Attach CSV files\n"
        "• Send to team email",
        title="[bold cyan]Email Summary[/bold cyan]",
        border_style="cyan"
    )
    console.print(info)

    if auto:
        console.print("[dim]Proceed with sending email summary? (auto: yes)[/dim]")
        return True

    return Confirm.ask("\nProceed with sending email summary?", default=True)


def send_email_summary_flow():
    """Send email summary with progress tracking."""
    console.print("[dim]Sending email summary...[/dim]\n")

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Processing and sending...", total=None)
            send_email_summary()
            progress.stop()

        console.print("[green]✓[/green] Email summary sent successfully\n")
        return True
    except FileNotFoundError as e:
        console.print(f"[red]✗[/red] File error: {str(e)}\n")
        return False
    except Exception as e:
        console.print(f"[red]✗[/red] Failed to send email: {str(e)}\n")
        return False


def confirm_engineer_email(auto: bool = False):
    """Prompt user about engineer email."""
    console.print("\n[bold blue]Step 4:[/bold blue] Engineer Notification\n")

    info = Panel(
        "[dim]This will:[/dim]\n"
        "• Create email to engineering team\n"
        "• Include importer error report\n"
        "• Open for review before sending",
        title="[bold cyan]Engineer Notification[/bold cyan]",
        border_style="cyan"
    )
    console.print(info)

    if auto:
        console.print("[dim]Proceed with engineer notification? (auto: yes)[/dim]")
        return True

    return Confirm.ask("\nProceed with engineer notification?", default=True)


def send_engineer_email_flow():
    """Send engineer email."""
    console.print("[dim]Creating engineer notification...[/dim]\n")

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Preparing email...", total=None)
            send_mail_to_engineers()
            progress.stop()

        console.print("[green]✓[/green] Engineer email prepared and opened for review\n")
        return True
    except Exception as e:
        console.print(f"[red]✗[/red] Failed to create engineer email: {str(e)}\n")
        return False


def display_execution_summary(summary: dict):
    """Display final summary of executed tasks.

    summary values are one of three states (not a bool): "done" (ran
    successfully), "failed" (ran but raised/returned failure), or "skipped"
    (user declined, or auto default was "no"). This distinguishes an
    intentional skip from an actual failure, which a plain True/False could not.
    """
    console.print()

    results = Table(
        title="[bold cyan]Execution Summary[/bold cyan]",
        box=box.ROUNDED,
        padding=(0, 1)
    )
    results.add_column("Task", style="cyan", width=30)
    results.add_column("Result", style="green")

    status_styles = {
        "done": "[green]✓ Completed[/green]",
        "failed": "[red]✗ Failed[/red]",
        "skipped": "[dim]⊘ Skipped[/dim]"
    }

    for task, state in summary.items():
        results.add_row(task, status_styles[state])

    console.print(results)

    # Final panel
    # NOTE: this message is unconditional — it prints even if one or more
    # steps above are marked "failed". It only confirms the program ran to
    # completion without an unhandled exception, not that every step succeeded.
    console.print()
    final_panel = Panel(
        "[bold green]✓ Program completed successfully[/bold green]",
        box=box.ROUNDED,
        border_style="green"
    )
    console.print(final_panel)


def parse_args():
    """Define and parse CLI arguments.

    --auto is the only flag: it makes all three confirm_* functions skip
    Confirm.ask and return their default immediately, so the program can run
    unattended (e.g. via Windows Task Scheduler) without blocking on stdin.
    """
    parser = argparse.ArgumentParser(description="Client Dashboard Automation")
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Run unattended: skip all confirmation prompts and use their defaults "
             "(health check: run, email summary: send, engineer notification: send)"
    )
    # ======================================================================
    # DEMO MODE (portfolio only): not part of the original tool.
    # Makes the first N fetch attempts of each check fail in demo mode, so the
    # retry and backoff output can be shown. Ignored when MOCK_MODE is off.
    # The real fetch logic in get_data.py is unchanged and runs when MOCK_MODE is off.
    # ======================================================================
    parser.add_argument(
        "--simulate-failure",
        type=int,
        default=0,
        metavar="N",
        help="Demo mode only: fail the first N fetch attempts of each check to show retry/backoff"
    )
    return parser.parse_args()


def main():
    """Main function with improved UX using rich CLI."""
    args = parse_args()

    # DEMO MODE (portfolio only): pass --simulate-failure N on to get_data.get_mock_data().
    config.simulate_failures = args.simulate_failure

    display_banner()

    if args.auto:
        console.print("[dim]Running in --auto mode: confirmation prompts are disabled.[/dim]")

    execution_summary = {
        "Health Check": "skipped",
        "Email Summary": "skipped",
        "Engineer Notification": "skipped"
    }

    try:
        # Step 1: Check health check status
        health_check_path = check_health_check_status()

        # Step 2: Confirm and perform health check
        if confirm_health_check(health_check_path is not None, auto=args.auto):
            if load_and_validate_cookies() and perform_health_check_flow():
                execution_summary["Health Check"] = "done"
            else:
                execution_summary["Health Check"] = "failed"
        else:
            console.print("[yellow]⚠[/yellow] Health check skipped\n")

        # Step 3: Email summary
        if confirm_email_summary(auto=args.auto):
            if send_email_summary_flow():
                execution_summary["Email Summary"] = "done"
            else:
                execution_summary["Email Summary"] = "failed"
        else:
            console.print("[yellow]⚠[/yellow] Email summary skipped\n")

        # Step 4: Engineer email
        if confirm_engineer_email(auto=args.auto):
            if send_engineer_email_flow():
                execution_summary["Engineer Notification"] = "done"
            else:
                execution_summary["Engineer Notification"] = "failed"
        else:
            console.print("[yellow]⚠[/yellow] Engineer notification skipped\n")

        # Display final summary
        display_execution_summary(execution_summary)

    except KeyboardInterrupt:
        console.print("\n[red]✗[/red] Program interrupted by user")
    except Exception as e:
        # NOTE: this does not catch SystemExit. If cookie refresh fails inside
        # update_cookies() (helper_functions.py), it calls exit() directly,
        # which bypasses this handler and display_execution_summary() entirely,
        # since SystemExit is a BaseException, not an Exception subclass.
        console.print(f"\n[red]✗[/red] An unexpected error occurred: [bold]{str(e)}[/bold]")


if __name__ == '__main__':
    main()