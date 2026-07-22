# Marks app/ideation as a package. The ideation crew lives here:
#   schema.py       — the IdeaDoc and Spec data shapes (what the crew produces)
#   roles.py        — the system prompt for each crew role (verbatim, PROMPT.md §9)
#   parsing.py      — pull structured JSON out of a model's text answer
#   repo.py         — persist sessions / messages / artifacts to SQLite
#   orchestrator.py — the state machine that runs the debate and the human gate
