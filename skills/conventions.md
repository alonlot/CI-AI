# Code conventions

- Function and variable names must be descriptive; single-letter names only
  for loop indices.
- No commented-out code left in the diff.
- New public functions/classes need a docstring or doc comment.
- Errors must not be silently swallowed (empty catch/except blocks are a
  finding unless there is a comment explaining why).
- Magic numbers should be named constants when they carry meaning.
