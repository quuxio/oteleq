from pathlib import Path
Path('/Users/sclarke/github/oteleq-qualification/2026-10-22/project-tests-development/pythonpath-preflight/unexpected-application-initializer.txt').write_text("application initializer ran")
raise RuntimeError("application module imported by planner host")
