from db_default_settings import get_connection

async def get_admin_id() -> int:
    async with get_connection() as conn:
        admin_id = await conn.fetchval("""
            SELECT id FROM authentication_customuser 
            WHERE username = 'admin';
        """)
        return admin_id