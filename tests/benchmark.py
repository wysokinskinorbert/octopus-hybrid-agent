import sys
import os
import time
from rich.console import Console
from rich.table import Table
from octopus.core.session import OctopusSession

console = Console()

TEST_CASES = [
    # 1. Matematyka (Test delegacji obliczeń)
    "Oblicz dokładnie 12345 * 67890.",
    
    # 2. System Plików - Zapis (Test 'write_file')
    "Stwórz plik 'test_octopus.txt' z treścią: 'Octopus Framework Benchmark'.",
    
    # 3. System Plików - Odczyt (Test 'read_file')
    "Odczytaj plik 'test_octopus.txt' i powiedz mi co w nim jest.",
    
    # 4. Shell - Informacje o systemie (Test 'run_shell_command')
    "Sprawdź wersję pythona zainstalowaną w tym środowisku (python --version).",
    
    # 5. Logika złożona - Generowanie kodu (Test pętli ReAct developera)
    "Napisz skrypt w pythonie, który generuje 5 losowych liczb i zapisuje je do pliku 'random_numbers.txt', a potem uruchom go.",
    
    # 6. Analiza plików (Chain of thought)
    "Policz ile linii kodu ma plik 'octopus/main.py'.",
    
    # 7. Sprzątanie (Test usuwania)
    "Usuń plik 'random_numbers.txt' i 'test_octopus.txt'.",
    
    # 8. Test Błędu (Self-Healing)
    "Uruchom komendę 'non_existent_command_xyz' i powiedz mi jaki był kod błędu.",
    
    # 9. Test Listowania
    "Wylistuj pliki w katalogu 'octopus/core'.",
    
    # 10. Test Złożony (Matematyka + Kod)
    "Oblicz silnię z 10 (10!) pisząc szybki skrypt."
]

def run_benchmark():
    console.print("[bold blue]Running Octopus Benchmark (10 Tests)[/bold blue]\n")
    
    results = []
    
    # Initialize Session
    session = OctopusSession(role_name="architect")
    
    # Boot up MCP
    print("Initializing MCP...")
    # Consume generator to start servers
    for _ in session.initialize(): pass
    
    for i, prompt in enumerate(TEST_CASES, 1):
        console.print(f"[bold yellow]Test {i}:[/bold yellow] {prompt}")
        
        delegated = False
        final_answer = ""
        start_time = time.time()
        
        try:
            # Process request
            for event in session.process_user_input(prompt):
                if event.type == "log" and "Delegating" in event.content:
                    delegated = True
                    console.print("  [cyan]✓ Delegated[/cyan]")
                elif event.type == "text" and event.metadata.get("final"):
                    final_answer = event.content
                elif event.type == "error":
                    console.print(f"  [red]Error: {event.content}[/red]")
        except Exception as e:
            final_answer = f"CRASH: {e}"

        duration = time.time() - start_time
        success = delegated and len(final_answer) > 0
        
        # Simple heuristic for success check
        status = "[green]PASS[/green]" if success else "[red]FAIL[/red]"
        console.print(f"  Result: {final_answer[:100]}... [dim]({duration:.2f}s)[/dim]")
        
        results.append((i, prompt, status, f"{duration:.2f}s"))
        print("-" * 50)

    session.shutdown()
    
    # Summary Table
    table = Table(title="Benchmark Report")
    table.add_column("ID", justify="center")
    table.add_column("Task")
    table.add_column("Status")
    table.add_column("Time")
    
    for r in results:
        table.add_row(str(r[0]), r[1][:40]+"...")
        
    console.print(table)

if __name__ == "__main__":
    run_benchmark()
