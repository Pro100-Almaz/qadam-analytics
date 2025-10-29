import asyncio
from contextlib import asynccontextmanager

import asyncpg
from decouple import config

@asynccontextmanager
async def get_connection():
    conn = await asyncpg.connect(
        user=config('DB_USER'),
        password = config('DB_PASSWORD'),
        host=config('DB_HOST'),
        port=config('DB_PORT'),
        database=config('DB_NAME'),
    )
    try:
        yield conn

    finally:
        await conn.close()
