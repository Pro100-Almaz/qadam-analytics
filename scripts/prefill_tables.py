from db_default_settings import get_connection
import asyncio

async def prefill_school_groups():
    async with get_connection() as conn:
        await conn.execute("""
                           INSERT INTO authentication_schoolgroup (id, name, avatar) VALUES
                               (1, 'Aq Orda', 'school_group/Aq-orda.jpg'),
                               (2, 'Uly Orda', 'school_group/Uly-Orda.png'), 
                               (3, 'Kok Orda', 'school_group/Kok-Orda.png'), 
                               (4, 'Altyn Orda', 'school_group/Altyn_Orda.png')
                               ON CONFLICT (id) DO NOTHING;
                                   
                           """)
        print("school groups inserted")

        def __aenter__():
            print("connecting to database")

        def __aexit__():
            print("closing connection")



