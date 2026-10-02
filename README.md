# money-agent

A buy-only order engine and operating instructions for a three-ETF Pearler
account. `portfolio.py` encodes the one-ticket rule, offset gate, $500 parcel
floor and VGE ceiling. `AGENT.md` is the agent's system prompt.

    cp private/state.example.json private/state.json   # fill in, never commit
    python3 portfolio.py next
    python3 -m unittest discover -s tests

Personal data (the brief, state and ledger) lives in `private/`, which git ignores.
