"""
db.py — shared Postgres connection + schema init.
Reads the connection string from the DATABASE_URL environment variable
(set as a GitHub Actions secret, and also as a Kaggle secret when you
want to query from a notebook).

Get this string from Supabase: Project Settings → Database →
Connection string → URI. Use the "Session pooler" URI if you're
connecting from a serverless/short-lived environment like GitHub
Actions or Kaggle (it handles connection churn better than a direct
connection).
"""

import os
import psycopg2


def get_conn():
    url = os.environ.get('DATABASE_URL')
    if not url:
        raise RuntimeError(
            'DATABASE_URL is not set. Add it as a GitHub Actions secret '
            '(and/or a Kaggle secret) with your Supabase connection string.'
        )
    return psycopg2.connect(url, sslmode='require')


def init_schema():
    """Idempotent — safe to call on every run."""
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, 'schema.sql')) as f:
        schema_sql = f.read()

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(schema_sql)
    conn.commit()
    cur.close()
    conn.close()


def deck_key(cards):
    """Canonical deck identifier — sorted card names joined by pipe"""
    return '|'.join(sorted([c for c in cards if c]))
