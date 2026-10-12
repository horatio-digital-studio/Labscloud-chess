"""Application logic shared by the Cloudflare Worker and the local dev server.

Nothing in this package imports the Cloudflare runtime (workers, js, pyodide); the
runtime-specific glue lives in src/entry.py, src/game_room.py, src/lobby.py and
src/glue.py.
"""
