"""A toy selection loop: pick the tables for a request, then write SQL from only those.

`catalog` holds the table descriptions and how they are rendered for a model.
`selector` and `builder` build the two prompts and parse the two answers.
`ollama` calls a local model. `sql` runs a query read-only with a time limit.
`evaluate` scores selection and SQL separately. `runner` runs the three arms.
"""
