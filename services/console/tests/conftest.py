"""
Change working directory to the console service root before tests run.
The console uses Jinja2 with a relative `templates/` directory, so tests must
run from within services/console/ for template lookups to resolve.
"""
import os
from pathlib import Path

# Move up from services/console/tests/ to services/console/
_CONSOLE_ROOT = Path(__file__).parent.parent
os.chdir(_CONSOLE_ROOT)
