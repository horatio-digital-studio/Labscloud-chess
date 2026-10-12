"""Local stand-in for the Cloudflare runtime, used by tests and for browser testing.

It wires the same `app` cores together in-process with sqlite3 storage, so everything
except the thin runtime glue (src/entry.py, src/game_room.py, src/lobby.py, src/glue.py)
can be exercised without Cloudflare. CI additionally runs the integration suite
against the real runtime (`pywrangler dev`).
"""
