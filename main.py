import os
import urllib.parse
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
import pg8000.dbapi

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "clave-secreta-pedidos")

def get_db():
    conn = pg8000.dbapi.connect(
        host="junction.proxy.rlwy.net",
        port=19313,
        database="railway",
        user="postgres",
        password="wsaHJnpOjtdOluEpcJxxhmwptubxTvZU",
        ssl_context=False
    )
    return conn

def row_to_dict(cursor, row):
    cols = [d[0] for d in cursor.description]
    return dict(zip(cols, row))

def rows_to_dicts(cursor, rows):
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row)) for row in rows]

def init_db():
    try:
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
            )
        """)
        cur.execute("""
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
            )
        """)
        cur.execute("SELECT id FROM usuarios WHERE usuario = 'admin'")
        if not cur.fetchone():
            cur.execute(
                "INSERT INTO usuarios (nombre, usuario, password, rol, tienda, telefono) VALUES (%s, %s, %s, %s, %s, %s)",
                ('Administrador', 'admin', generate_password_hash('admin123'), 'bodega', 'todas', '')
            )
        conn.commit()
        cur.close()
        conn.close()
        print("DB OK")
    except Exception as e:
        print(f"DB Error: {e}")

@app.route('/')
def index():
    if 'usuario_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    data = request.json
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT id, nombre, usuario, password, rol, tienda FROM usuarios WHERE usuario = %s", (data['usuario'],))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            user = {'id': row[0], 'nombre': row[1], 'usuario': row[2], 'password': row[3], 'rol': row[4], 'tienda': row[5]}
            if check_password_hash(user['password'], data['password']):
                session['usuario_id'] = user['id']
                session['nombre'] = user['nombre']
                session['rol'] = user['rol']
                session['tienda'] = user['tienda']
                return jsonify({'ok': True, 'rol': user['rol']})
        return jsonify({'ok': False, 'msg': 'Usuario o contraseña incorrectos'})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)})

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
    try:
        conn = get_db()
        cur = conn.cursor()
        if session['rol'] == 'bodega':
            cur.execute("""
                SELECT p.id, p.tipo, p.tienda, p.usuario_id, p.producto, p.cantidad,
                       p.urgencia, p.nota, p.estado, p.fecha_estimada,
                       p.fecha_creacion, p.fecha_actualizacion, u.nombre as solicitante
                FROM pedidos p
                LEFT JOIN usuarios u ON p.usuario_id = u.id
                ORDER BY CASE p.urgencia WHEN 'alta' THEN 1 WHEN 'media' THEN 2 ELSE 3 END, p.fecha_creacion DESC
            """)
        else:
            cur.execute("""
                SELECT p.id, p.tipo, p.tienda, p.usuario_id, p.producto, p.cantidad,
                       p.urgencia, p.nota, p.estado, p.fecha_estimada,
                       p.fecha_creacion, p.fecha_actualizacion, u.nombre as solicitante
                FROM pedidos p
                LEFT JOIN usuarios u ON p.usuario_id = u.id
                WHERE p.tienda = %s
                ORDER BY p.fecha_creacion DESC
            """, (session['tienda'],))
        rows = cur.fetchall()
        cols = ['id','tipo','tienda','usuario_id','producto','cantidad','urgencia','nota','estado','fecha_estimada','fecha_creacion','fecha_actualizacion','solicitante']
        pedidos = []
        for row in rows:
            d = dict(zip(cols, row))
            if d['fecha_creacion']:
                d['fecha_creacion'] = d['fecha_creacion'].isoformat()
            if d['fecha_actualizacion']:
                d['fecha_actualizacion'] = d['fecha_actualizacion'].isoformat()
            pedidos.append(d)
        cur.close()
        conn.close()
        return jsonify(pedidos)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/pedidos', methods=['POST'])
def crear_pedido():
    if 'usuario_id' not in session:
        return jsonify({'error': 'no autorizado'}), 401
    data = request.json
    try:
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
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)})

@app.route('/api/pedidos/<int:pid>', methods=['PUT'])
def actualizar_pedido(pid):
    if 'usuario_id' not in session:
        return jsonify({'error': 'no autorizado'}), 401
    data = request.json
    try:
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
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)})

@app.route('/api/mas-solicitados')
def mas_solicitados():
    if 'usuario_id' not in session:
        return jsonify({'error': 'no autorizado'}), 401
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT producto, COUNT(DISTINCT tienda) as tiendas, COUNT(*) as total
            FROM pedidos WHERE estado = 'pendiente'
            GROUP BY producto ORDER BY tiendas DESC, total DESC LIMIT 20
        """)
        rows = cur.fetchall()
        result = [{'producto': r[0], 'tiendas': r[1], 'total': r[2]} for r in rows]
        cur.close()
        conn.close()
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/usuarios', methods=['GET'])
def get_usuarios():
    if session.get('rol') not in ['bodega', 'encargado']:
        return jsonify({'error': 'no autorizado'}), 401
    try:
        conn = get_db()
        cur = conn.cursor()
        if session['rol'] == 'bodega':
            cur.execute("SELECT id, nombre, usuario, rol, tienda, telefono FROM usuarios ORDER BY tienda, nombre")
        else:
            cur.execute("SELECT id, nombre, usuario, rol, tienda, telefono FROM usuarios WHERE tienda = %s ORDER BY nombre", (session['tienda'],))
        rows = cur.fetchall()
        cols = ['id','nombre','usuario','rol','tienda','telefono']
        usuarios = [dict(zip(cols, r)) for r in rows]
        cur.close()
        conn.close()
        return jsonify(usuarios)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/usuarios', methods=['POST'])
def crear_usuario():
    if session.get('rol') not in ['bodega', 'encargado']:
        return jsonify({'error': 'no autorizado'}), 401
    data = request.json
    try:
        conn = get_db()
        cur = conn.cursor()
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
        cur.close()
        conn.close()
        return jsonify({'ok': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'ok': False, 'msg': 'Usuario ya existe'})

@app.route('/api/whatsapp/<int:pid>')
def whatsapp_link(pid):
    if 'usuario_id' not in session:
        return jsonify({'error': 'no autorizado'}), 401
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT p.producto, p.tienda, u.telefono, u.nombre
            FROM pedidos p
            LEFT JOIN usuarios u ON u.tienda = p.tienda AND u.rol = 'encargado'
            WHERE p.id = %s LIMIT 1
        """, (pid,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row or not row[2]:
            return jsonify({'ok': False, 'msg': 'Sin teléfono'})
        producto, tienda, telefono, encargado = row
        msg = f"Hola {encargado}, ya llegó la mercancía de *{producto}* para tu tienda *{tienda}*. Por favor recógela mañana. ✅"
        link = f"https://wa.me/52{telefono}?text={msg.replace(' ', '%20')}"
        return jsonify({'ok': True, 'link': link})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)})

with app.app_context():
    init_db()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
