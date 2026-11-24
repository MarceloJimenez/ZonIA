"""Recruiter dashboard: a list of conversations, one page per candidate, and the recruiter's outcome and note.

It reads the same SQLite file as Sonia (ZONIA_DB, or zonia.db), and saves the recruiter's outcomes and notes there.
`zonia-dashboard` starts it on http://127.0.0.1:8000.
- app.py: the routes (list, candidate page, save an outcome).
- rows.py: how each field and each row is shown, with the English labels.
- filters.py: which candidates the list shows.
"""
