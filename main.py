import os
import urllib.parse
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
import pg8000.dbapi

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY")

def get_db():
    conn = pg8000.dbapi.connect(
        host=os.environ.get("DB_HOST"),
        port=int(os.environ.get("DB_PORT", 5432)),
        database=os.environ.get("DB_NAME"),
        user=os.environ.get("DB_USER"),
        password=os.environ.get("DB_PASSWORD"),
        ssl_context=False
    )
    return conn

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
            CREATE TABLE IF NOT EXISTS categorias (
                id SERIAL PRIMARY KEY,
                nombre TEXT UNIQUE NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS productos (
                id SERIAL PRIMARY KEY,
                nombre TEXT NOT NULL,
                categoria_id INTEGER REFERENCES categorias(id),
                activo BOOLEAN DEFAULT TRUE
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pedidos (
                id SERIAL PRIMARY KEY,
                tipo TEXT NOT NULL DEFAULT 'faltante',
                tienda TEXT NOT NULL,
                usuario_id INTEGER REFERENCES usuarios(id),
                producto_id INTEGER,
                producto_nombre TEXT NOT NULL,
                cantidad TEXT NOT NULL,
                modelo_marca TEXT,
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

# ── PEDIDOS ───────────────────────────────────────────────────────────────────

@app.route('/api/pedidos', methods=['GET'])
def get_pedidos():
    if 'usuario_id' not in session:
        return jsonify({'error': 'no autorizado'}), 401
    try:
        tipo = request.args.get('tipo')
        estado = request.args.get('estado')
        tienda_f = request.args.get('tienda')
        agrupar = request.args.get('agrupar') == '1'
        historial = request.args.get('historial') == '1'
        conn = get_db()
        cur = conn.cursor()
        where = []
        params = []
        if session['rol'] != 'bodega':
            where.append("p.tienda = %s")
            params.append(session['tienda'])
        elif tienda_f:
            where.append("p.tienda = %s")
            params.append(tienda_f)
        if tipo:
            where.append("p.tipo = %s")
            params.append(tipo)
        if historial:
            where.append("p.estado IN ('llego', 'bodega', 'no-surtido')")
        elif estado:
            where.append("p.estado = %s")
            params.append(estado)

        if agrupar and session['rol'] == 'bodega':
            grp_where = list(where)
            grp_params = list(params)
            grp_where.append("p.estado = 'pendiente'")
            where_sql = "WHERE " + " AND ".join(grp_where)
            cur.execute(f"""
                SELECT p.producto_nombre, p.modelo_marca, p.tipo,
                       STRING_AGG(DISTINCT p.tienda, ',') AS tiendas,
                       COUNT(*) AS num_pedidos,
                       COUNT(DISTINCT p.tienda) AS num_tiendas
                FROM pedidos p
                {where_sql}
                GROUP BY p.producto_nombre, p.modelo_marca, p.tipo
                ORDER BY CASE p.tipo WHEN 'urgente' THEN 1 WHEN 'faltante' THEN 2 WHEN 'especial' THEN 3 ELSE 4 END,
                         COUNT(DISTINCT p.tienda) DESC, COUNT(*) DESC
            """, grp_params)
            rows = cur.fetchall()
            pedidos = []
            for row in rows:
                tiendas_str = row[3] or ''
                pedidos.append({
                    'producto_nombre': row[0],
                    'modelo_marca': row[1] or '',
                    'tipo': row[2],
                    'tiendas': [t.strip() for t in tiendas_str.split(',') if t.strip()],
                    'num_pedidos': row[4],
                    'num_tiendas': row[5],
                    'cantidad_total': row[4]
                })
        else:
            where_sql = "WHERE " + " AND ".join(where) if where else ""
            cur.execute(f"""
                SELECT p.id, p.tipo, p.tienda, p.usuario_id, p.producto_nombre, p.cantidad,
                       p.urgencia, p.nota, p.estado, p.fecha_estimada,
                       p.fecha_creacion, p.fecha_actualizacion, u.nombre as solicitante,
                       p.modelo_marca, p.producto_id
                FROM pedidos p
                LEFT JOIN usuarios u ON p.usuario_id = u.id
                {where_sql}
                ORDER BY CASE p.tipo WHEN 'urgente' THEN 1 WHEN 'faltante' THEN 2 WHEN 'especial' THEN 3 ELSE 4 END,
                         p.fecha_creacion DESC
            """, params)
            rows = cur.fetchall()
            cols = ['id','tipo','tienda','usuario_id','producto_nombre','cantidad','urgencia','nota','estado',
                    'fecha_estimada','fecha_creacion','fecha_actualizacion','solicitante','modelo_marca','producto_id']
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
            INSERT INTO pedidos (tipo, tienda, usuario_id, producto_id, producto_nombre, cantidad, modelo_marca, urgencia, nota)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            data.get('tipo', 'faltante'),
            session['tienda'],
            session['usuario_id'],
            data.get('producto_id'),
            data['producto_nombre'],
            data['cantidad'],
            data.get('modelo_marca', ''),
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

@app.route('/api/pedidos/<int:pid>', methods=['DELETE'])
def borrar_pedido(pid):
    if 'usuario_id' not in session:
        return jsonify({'error': 'no autorizado'}), 401
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("DELETE FROM pedidos WHERE id = %s", (pid,))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)})

@app.route('/api/pedidos/accion-masiva', methods=['POST'])
def accion_masiva():
    if session.get('rol') != 'bodega':
        return jsonify({'error': 'no autorizado'}), 401
    data = request.json
    producto = data.get('producto_nombre', '').strip()
    modelo = (data.get('modelo_marca') or '').strip()
    tipo = data.get('tipo', '').strip()
    estado = data.get('estado', '').strip()
    if not producto or not tipo or not estado:
        return jsonify({'ok': False, 'msg': 'Faltan datos'})
    estados_validos = {'llego', 'bodega', 'no-surtido'}
    if estado not in estados_validos:
        return jsonify({'ok': False, 'msg': 'Estado no válido'})
    try:
        conn = get_db()
        cur = conn.cursor()
        if modelo:
            cur.execute("""
                UPDATE pedidos
                SET estado = %s, fecha_actualizacion = NOW()
                WHERE producto_nombre = %s
                  AND tipo = %s
                  AND COALESCE(modelo_marca, '') = %s
                  AND estado = 'pendiente'
            """, (estado, producto, tipo, modelo))
        else:
            cur.execute("""
                UPDATE pedidos
                SET estado = %s, fecha_actualizacion = NOW()
                WHERE producto_nombre = %s
                  AND tipo = %s
                  AND COALESCE(modelo_marca, '') = ''
                  AND estado = 'pendiente'
            """, (estado, producto, tipo))
        afectados = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'ok': True, 'afectados': afectados})
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
            SELECT producto_nombre, tipo, COUNT(DISTINCT tienda) as tiendas, COUNT(*) as total
            FROM pedidos WHERE estado = 'pendiente'
            GROUP BY producto_nombre, tipo ORDER BY tiendas DESC, total DESC LIMIT 20
        """)
        rows = cur.fetchall()
        result = [{'producto': r[0], 'tipo': r[1], 'tiendas': r[2], 'total': r[3]} for r in rows]
        cur.close()
        conn.close()
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── CATEGORIAS ────────────────────────────────────────────────────────────────

@app.route('/api/categorias', methods=['GET'])
def get_categorias():
    if 'usuario_id' not in session:
        return jsonify({'error': 'no autorizado'}), 401
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT id, nombre FROM categorias ORDER BY nombre")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify([{'id': r[0], 'nombre': r[1]} for r in rows])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/categorias', methods=['POST'])
def crear_categoria():
    if session.get('rol') != 'bodega':
        return jsonify({'error': 'no autorizado'}), 401
    data = request.json
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("INSERT INTO categorias (nombre) VALUES (%s)", (data['nombre'],))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'msg': 'Categoría ya existe'})

@app.route('/api/categorias/<int:cid>', methods=['DELETE'])
def borrar_categoria(cid):
    if session.get('rol') != 'bodega':
        return jsonify({'error': 'no autorizado'}), 401
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("DELETE FROM categorias WHERE id = %s", (cid,))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)})

# ── PRODUCTOS ─────────────────────────────────────────────────────────────────

@app.route('/api/productos', methods=['GET'])
def get_productos():
    if 'usuario_id' not in session:
        return jsonify({'error': 'no autorizado'}), 401
    try:
        cat_id = request.args.get('categoria_id')
        conn = get_db()
        cur = conn.cursor()
        if cat_id:
            cur.execute("""
                SELECT p.id, p.nombre, p.categoria_id, c.nombre as categoria
                FROM productos p LEFT JOIN categorias c ON p.categoria_id = c.id
                WHERE p.activo = TRUE AND p.categoria_id = %s ORDER BY p.nombre
            """, (cat_id,))
        else:
            cur.execute("""
                SELECT p.id, p.nombre, p.categoria_id, c.nombre as categoria
                FROM productos p LEFT JOIN categorias c ON p.categoria_id = c.id
                WHERE p.activo = TRUE ORDER BY c.nombre, p.nombre
            """)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify([{'id': r[0], 'nombre': r[1], 'categoria_id': r[2], 'categoria': r[3]} for r in rows])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/productos', methods=['POST'])
def crear_producto():
    if session.get('rol') != 'bodega':
        return jsonify({'error': 'no autorizado'}), 401
    data = request.json
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("INSERT INTO productos (nombre, categoria_id) VALUES (%s, %s)",
            (data['nombre'], data.get('categoria_id')))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)})

@app.route('/api/productos/<int:pid>', methods=['DELETE'])
def borrar_producto(pid):
    if session.get('rol') != 'bodega':
        return jsonify({'error': 'no autorizado'}), 401
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("UPDATE productos SET activo = FALSE WHERE id = %s", (pid,))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)})

# ── USUARIOS ──────────────────────────────────────────────────────────────────

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
        cur.close()
        conn.close()
        return jsonify([dict(zip(cols, r)) for r in rows])
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
        return jsonify({'ok': False, 'msg': 'Usuario ya existe'})

# ── WHATSAPP ──────────────────────────────────────────────────────────────────

@app.route('/api/whatsapp/<int:pid>')
def whatsapp_link(pid):
    if 'usuario_id' not in session:
        return jsonify({'error': 'no autorizado'}), 401
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT p.producto_nombre, p.tienda, u.telefono, u.nombre
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
