import typer
from .tui_app import OctopusApp

app = typer.Typer()

@app.command()
def main(auto_approve: bool = typer.Option(False, help="Auto-approve plan in PLAN mode")):
    """
    Octopus Framework v5.0 (TUI Edition)
    """
    tui = OctopusApp(auto_approve=auto_approve)
    tui.run()

if __name__ == "__main__":
    app()