import sys
import os
import traceback

# Dodaj bieżący katalog do ścieżki, aby python widział pakiet octopus
sys.path.append(os.getcwd())

print("--- DIAGNOSTYKA STARTU OCTOPUS ---")

try:
    print("1. Próba importu octopus.core.session...")
    from octopus.core.session import OctopusSession
    print("   -> Sukces.")

    print("2. Próba inicjalizacji klasy OctopusSession...")
    session = OctopusSession("architect")
    print("   -> Sukces.")

    print("3. Próba uruchomienia generatora initialize()...")
    # Konsumujemy generator, aby wymusić wykonanie kodu
    for event in session.initialize():
        print(f"   -> Event: {event.type} - {event.content[:50]}...")
        if event.type == "error":
            print(f"   !!! WYKRYTO BŁĄD WEWNĘTRZNY: {event.content}")

    print("--- DIAGNOSTYKA ZAKOŃCZONA SUKCESEM ---")

except Exception:
    print("\n--- WYKRYTO BŁĄD KRYTYCZNY ---")
    traceback.print_exc()
