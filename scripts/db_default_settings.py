from contextlib import contextmanager
from decouple import config
import psycopg2

@contextmanager
def get_connection():
    conn = psycopg2.connect(
        user=config('DB_USER'),
        password = config('DB_PASSWORD'),
        host=config('DB_HOST'),
        port=config('DB_PORT'),
        database=config('DB_NAME'),
    )
    try:
        yield conn

    finally:
        conn.close()
