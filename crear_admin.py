import os
import urllib.parse
import pg8000.dbapi
from werkzeug.security import generate_password_hash

def get_db():
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        u = urllib.parse.urlparse(database_url)
        return pg8000.dbapi.connect(
            host=u.hostname,
            port=u.port or 5432,
            database=u.path.lstrip("/"),
            user=u.username,
            password=u.password,
            ssl_context=False
        )
    return pg8000.dbapi.connect(
        host=os.environ.get("DB_HOST"),
        port=int(os.environ.get("DB_PORT") or 5432),
        database=os.environ.get("DB_NAME"),
        user=os.environ.get("DB_USER"),
        password=os.environ.get("DB_PASSWORD"),
        ssl_context=False
    )

def crear_admin():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM usuarios WHERE usuario = 'admin'")
    if cur.fetchone():
        print("El usuario 'admin' ya existe.")
        cur.close()
        conn.close()
        return
    cur.execute(
        "INSERT INTO usuarios (nombre, usuario, password, rol, tienda, telefono) VALUES (%s, %s, %s, %s, %s, %s)",
        ('Administrador', 'admin', generate_password_hash('admin123'), 'bodega', 'Central', '')
    )
    conn.commit()
    cur.close()
    conn.close()
    print("Usuario admin creado: usuario=admin, contraseña=admin123, tienda=Central")

if __name__ == '__main__':
    crear_admin()
