from db_default_settings import get_connection

def prefill_school_groups():
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                               INSERT INTO authentication_schoolgroup (id, name, avatar) VALUES
                                   (1, 'Aq Orda', 'school_group/Aq-orda.jpg'),
                                   (2, 'Uly Orda', 'school_group/Uly-Orda.png'), 
                                   (3, 'Kok Orda', 'school_group/Kok-Orda.png'), 
                                   (4, 'Altyn Orda', 'school_group/Altyn_Orda.png')
                                   ON CONFLICT (id) DO NOTHING;
                                       
                               """)
        conn.commit()
        print("school groups inserted")



