import sys
import os
import asyncio
from textual.app import App

# Dodaj ścieżkę do projektu
sys.path.append(os.getcwd())

try:
    from octopus.tui_app import OctopusApp
except Exception as e:
    print(f"IMPORT ERROR: {e}")
    sys.exit(1)

class TestApp(OctopusApp):
    async def on_mount(self):
        print("DEBUG: TestApp.on_mount started")
        try:
            await super().on_mount()
            print("DEBUG: Super.on_mount finished")
            # Wait a bit for async workers (init_session)
            self.set_timer(3.0, self.exit_test)
        except Exception as e:
            print(f"RUNTIME ERROR in on_mount: {e}")
            self.exit(1)

    def exit_test(self):
        print("DEBUG: Exiting normally after timeout")
        self.exit(0)

if __name__ == "__main__":
    print("Starting TestApp...")
    try:
        app = TestApp()
        app.run()
    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
