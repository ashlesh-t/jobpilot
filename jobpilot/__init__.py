"""JobPilot — installable CLI wrapper around the job-hunt pipeline + control service.

This thin package exists so `pipx install jobpilot-ai` gives a cross-platform `jobpilot`
command. The actual pipeline (engines/, server/, scripts/, skills/, config/, schema/) is
bundled alongside it and resolved at runtime by `jobpilot.paths`.
"""
__version__ = "1.7.0"
