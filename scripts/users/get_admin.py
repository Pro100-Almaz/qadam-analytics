from scripts.db_default_settings import get_connection

def get_admin_id() -> int:
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT id FROM authentication_customuser 
                WHERE username = 'admin';
            """)
            admin_id = cursor.fetchone()[0]
            return admin_id if admin_id else None