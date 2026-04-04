import os
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
import pg8000
import pg8000.native

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "clave-secreta-pedidos")

def get_db():
    url = os.environ.get("DATABASE_URL")
    # parse url: postgresql://user:pass@host:port/db
    import urllib.parse
    r = urllib.parse.urlparse(url)
    return pg8000.connect(
        host=r.hostname,
        port=r.port or 5432,
        database=r.path[1:],
        user=r.username,
        password=r.password,
        ssl_context=False
    )

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id SERIAL PRIMARY KEY,
            nombre TEXT NOT NULL,
            usuario TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            rol TEXT NOT NULL,
            tienda TEXT,
            telefono TEXT
        );
        CREATE TABLE IF NOT EXISTS pedidos (
            id SERIAL PRIMARY KEY,
            tipo TEXT NOT NULL,
            tienda TEXT NOT NULL,
            usuario_id INTEGER REFERENCES usuarios(id),
            producto TEXT NOT NULL,
            cantidad TEXT NOT NULL,
            urgencia TEXT DEFAULT 'media',
            nota TEXT,
            estado TEXT DEFAULT 'pendiente',
            fecha_estimada TEXT,
            fecha_creacion TIMESTAMP DEFAULT NOW(),
            fecha_actualizacion TIMESTAMP DEFAULT NOW()
        );
    """)
    cur.execute("SELECT id FROM usuarios WHERE usuario = 'admin'")
    if not cur.fetchone():
        cur.execute("""
            INSERT INTO usuarios (nombre, usuario, password, rol, tienda, telefono)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, ('Administrador', 'admin', generate_password_hash('admin123'), 'bodega', 'todas', ''))
    conn.commit()
    cur.close()
    conn.close()

@app.route('/')
def index():
    if 'usuario_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    data = request.json
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM usuarios WHERE usuario = %s", (data['usuario'],))
    user = cur.fetchone()
    cur.close()
    conn.close()
    if user and check_password_hash(user['password'], data['password']):
        session['usuario_id'] = user['id']
        session['nombre'] = user['nombre']
        session['rol'] = user['rol']
        session['tienda'] = user['tienda']
        return jsonify({'ok': True, 'rol': user['rol']})
    return jsonify({'ok': False, 'msg': 'Usuario o contraseña incorrectos'})

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/dashboard')
def dashboard():
    if 'usuario_id' not in session:
        return redirect(url_for('index'))
    return render_template('dashboard.html', rol=session['rol'], nombre=session['nombre'], tienda=session['tienda'])

@app.route('/api/pedidos', methods=['GET'])
def get_pedidos():
    if 'usuario_id' not in session:
        return jsonify({'error': 'no autorizado'}), 401
    conn = get_db()
    cur = conn.cursor()
    if session['rol'] == 'bodega':
        cur.execute("""
            SELECT p.*, u.nombre as solicitante FROM pedidos p
            LEFT JOIN usuarios u ON p.usuario_id = u.id
            ORDER BY CASE urgencia WHEN 'alta' THEN 1 WHEN 'media' THEN 2 ELSE 3 END, fecha_creacion DESC
        """)
    else:
        cur.execute("""
            SELECT p.*, u.nombre as solicitante FROM pedidos p
            LEFT JOIN usuarios u ON p.usuario_id = u.id
            WHERE p.tienda = %s
            ORDER BY fecha_creacion DESC
        """, (session['tienda'],))
    pedidos = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([dict(p) for p in pedidos])

@app.route('/api/pedidos', methods=['POST'])
def crear_pedido():
    if 'usuario_id' not in session:
        return jsonify({'error': 'no autorizado'}), 401
    data = request.json
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO pedidos (tipo, tienda, usuario_id, producto, cantidad, urgencia, nota)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (
        data.get('tipo', 'modulo'),
        session['tienda'],
        session['usuario_id'],
        data['producto'],
        data['cantidad'],
        data.get('urgencia', 'media'),
        data.get('nota', '')
    ))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/pedidos/<int:pid>', methods=['PUT'])
def actualizar_pedido(pid):
    if 'usuario_id' not in session:
        return jsonify({'error': 'no autorizado'}), 401
    data = request.json
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        UPDATE pedidos SET estado = %s, fecha_estimada = %s, fecha_actualizacion = NOW()
        WHERE id = %s
    """, (data.get('estado'), data.get('fecha_estimada'), pid))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/mas-solicitados')
def mas_solicitados():
    if 'usuario_id' not in session:
        return jsonify({'error': 'no autorizado'}), 401
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT producto, COUNT(DISTINCT tienda) as tiendas, COUNT(*) as total
        FROM pedidos WHERE estado = 'pendiente'
        GROUP BY producto ORDER BY tiendas DESC, total DESC LIMIT 20
    """)
    data = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([dict(r) for r in data])

@app.route('/api/usuarios', methods=['GET'])
def get_usuarios():
    if session.get('rol') not in ['bodega', 'encargado']:
        return jsonify({'error': 'no autorizado'}), 401
    conn = get_db()
    cur = conn.cursor()
    if session['rol'] == 'bodega':
        cur.execute("SELECT id, nombre, usuario, rol, tienda, telefono FROM usuarios ORDER BY tienda, nombre")
    else:
        cur.execute("SELECT id, nombre, usuario, rol, tienda, telefono FROM usuarios WHERE tienda = %s ORDER BY nombre", (session['tienda'],))
    usuarios = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([dict(u) for u in usuarios])

@app.route('/api/usuarios', methods=['POST'])
def crear_usuario():
    if session.get('rol') not in ['bodega', 'encargado']:
        return jsonify({'error': 'no autorizado'}), 401
    data = request.json
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO usuarios (nombre, usuario, password, rol, tienda, telefono)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            data['nombre'],
            data['usuario'],
            generate_password_hash(data['password']),
            data['rol'],
            data['tienda'],
            data.get('telefono', '')
        ))
        conn.commit()
        return jsonify({'ok': True})
    except Exception:
        conn.rollback()
        return jsonify({'ok': False, 'msg': 'Usuario ya existe'})
    finally:
        cur.close()
        conn.close()

@app.route('/api/whatsapp/<int:pid>')
def whatsapp_link(pid):
    if 'usuario_id' not in session:
        return jsonify({'error': 'no autorizado'}), 401
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT p.*, u.telefono, u.nombre as encargado_nombre
        FROM pedidos p
        LEFT JOIN usuarios u ON u.tienda = p.tienda AND u.rol = 'encargado'
        WHERE p.id = %s LIMIT 1
    """, (pid,))
    p = cur.fetchone()
    cur.close()
    conn.close()
    if not p or not p['telefono']:
        return jsonify({'ok': False, 'msg': 'Sin teléfono'})
    msg = f"Hola {p['encargado_nombre']}, ya llegó la mercancía de *{p['producto']}* para tu tienda *{p['tienda']}*. Por favor recógela mañana. ✅"
    link = f"https://wa.me/52{p['telefono']}?text={msg.replace(' ', '%20')}"
    return jsonify({'ok': True, 'link': link})

with app.app_context():
    init_db()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
