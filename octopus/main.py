import typer
from .tui_app import OctopusApp

app = typer.Typer()

@app.command()
def main():
    """
    Octopus Framework v5.0 (TUI Edition)
    """
    tui = OctopusApp()
    tui.run()

if __name__ == "__main__":
    app()