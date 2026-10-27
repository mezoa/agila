"""The Discord bot (FR27, FR40): a thin client of the Agila API (NFR10).

    uv run --env-file .env python -m agila.bot           (start; Ctrl+C stops it)
    uv run --env-file .env python -m agila.bot --sync    (register the commands in the server)

It holds no search or answer logic and imports no other `agila` module: every command is one or
two calls to the API on 127.0.0.1:8000. `messages` is the pure text part, `client` the API calls.
"""
