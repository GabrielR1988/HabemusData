from flask import Flask, render_template, redirect, url_for, request, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, current_user, logout_user
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField
from wtforms.validators import DataRequired
from datetime import datetime
import random, re, os
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import timedelta
from flask_mail import Mail, Message
from flask import flash
from flask import send_file
from supabase import create_client
from dotenv import load_dotenv
import os
from flask_migrate import Migrate
from flask import send_from_directory
import json
from io import BytesIO
from datetime import datetime


load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
BUCKET_NAME = os.getenv("BUCKET_NAME")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def actualizar_pedidos_con_pdf(para_usuario_id):
    bucket = supabase.storage.from_(BUCKET_NAME)
    pedidos = Pedido.query.filter_by(usuario_id=para_usuario_id).all()

    for pedido in pedidos:
        archivo_esperado = f"{pedido.id}_{pedido.dominio.upper()}.pdf"

        try:
            archivos = bucket.list()
            nombres = [obj['name'] for obj in archivos if archivo_esperado in obj['name']]

            if nombres:
                public_url = bucket.get_public_url(nombres[0])
                if pedido.url_pdf != public_url:
                    pedido.url_pdf = public_url
                    print(f"[✓] PDF actualizado para pedido {pedido.id}")

                    # Enviar email
                    try:
                        usuario = Usuario.query.get(pedido.usuario_id)
                        mensaje = Message(
                            subject="Tu informe ya está disponible",
                            recipients=[usuario.email],
                            body=f"Hola {usuario.nombre},\n\nTu informe del dominio {pedido.dominio} ya está disponible.\nPodés verlo desde tu panel de usuario."
                        )
                        mail.send(mensaje)
                        print(f"✓ Email enviado a {usuario.email}")
                    except Exception as e:
                        print(f"⚠️ Error al enviar mail: {e}")

        except Exception as e:
            print(f"Error en pedido {pedido.id}: {str(e)}")

    db.session.commit()

app = Flask(__name__)

import logging
from logging.handlers import RotatingFileHandler

if not os.path.exists('logs'):
    os.mkdir('logs')

file_handler = RotatingFileHandler('logs/app.log', maxBytes=10240, backupCount=3)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)s: %(message)s [en %(pathname)s:%(lineno)d]'
))

app.logger.addHandler(file_handler)
app.logger.setLevel(logging.INFO)
app.logger.info('Aplicación iniciada')

app.config['SECRET_KEY'] = os.getenv("SECRET_KEY")

#Tiempo de sesion de 15 minutos
app.permanent_session_lifetime = timedelta(minutes=15)

# Configurar la base de datos SQLite
basedir = os.path.abspath(os.path.dirname(__file__))
#app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'data.db')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DATABASE_URL").replace("postgres://", "postgresql://")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Configuración del servidor SMTP
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.getenv("MAIL_USERNAME")
app.config['MAIL_PASSWORD'] = os.getenv("MAIL_PASSWORD")
app.config['MAIL_DEFAULT_SENDER'] = 'hg.rodriguez1988@gmail.com'

mail = Mail(app)

# Inicializar SQLAlchemy
db = SQLAlchemy(app)

class Usuario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    password = db.Column(db.String(200), nullable=False)
    nombre = db.Column(db.String(100))
    email = db.Column(db.String(100), unique=True, nullable=False)
    telefono = db.Column(db.String(20))
    provincia = db.Column(db.String(50))

class Pedido(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cliente_nombre = db.Column(db.String(100))
    fecha_pedido = db.Column(db.DateTime, default=datetime.utcnow)
    estado = db.Column(db.String(50), default='En espera')  # Nuevo campo de estado
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    dominio = db.Column(db.String(20))
    url_pdf = db.Column(db.String, nullable=True)
    plan = db.Column(db.String(20), default='oro')   # 'bronce', 'plata', 'oro'
    datos_json = db.Column(db.Text, nullable=True)         # JSON con todos los datos del informe

    def __repr__(self):
        return f'<Pedido {self.id} - {self.cliente_nombre}>'
    
migrate = Migrate(app, db)
# Crear las tablas en la base de datos

# Inicializamos Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = ''
login_manager.login_message_category = 'info'

# Definimos un usuario simple (en un entorno real se haría con base de datos)
class User(UserMixin):
    def __init__(self, id):
        self.id = id

# Usuarios
@login_manager.user_loader
def load_user(user_id):
    return User(user_id)

# Formularios de login con Flask-WTF
class LoginForm(FlaskForm):
    username = StringField('Usuario', validators=[DataRequired()])
    password = PasswordField('Contraseña', validators=[DataRequired()])

class Mensaje(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100))
    email = db.Column(db.String(120))
    texto = db.Column(db.Text)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)

def es_admin():
    """Devuelve True si el usuario logueado es admin.
    Ajustá la lógica según tu modelo: podés agregar un campo
    is_admin = db.Column(db.Boolean, default=False) al modelo Usuario.
    Por ahora usamos una lista de IDs hardcodeada como arranque seguro."""
    ADMIN_IDS = [1]  # <-- Poné acá tu ID de usuario admin
    return current_user.is_authenticated and current_user.id in ADMIN_IDS

def parsear_datos_formulario(form):
    """Convierte el form con arrays (multas, embargos, etc.) en un dict limpio."""
    datos = {
        # Vehículo
        'marca': form.get('marca', '').strip(),
        'modelo': form.get('modelo', '').strip(),
        'version': form.get('version', '').strip(),
        'anio': form.get('anio', '').strip(),
        'color': form.get('color', '').strip(),
        'tipo': form.get('tipo', '').strip(),
        'motor': form.get('motor', '').strip(),
        'combustible': form.get('combustible', '').strip(),
        'nro_motor': form.get('nro_motor', '').strip(),
        'nro_chasis': form.get('nro_chasis', '').strip(),
        'radicacion': form.get('radicacion', '').strip(),

        # Titular
        'titular_nombre': form.get('titular_nombre', '').strip(),
        'titular_cuit': form.get('titular_cuit', '').strip(),
        'titular_tipo': form.get('titular_tipo', '').strip(),
        'titular_domicilio': form.get('titular_domicilio', '').strip(),
        'titular_provincia': form.get('titular_provincia', '').strip(),

        # Situación legal
        'robado': form.get('robado', 'No'),
        'inhabilitado': form.get('inhabilitado', 'No'),
        'baja_dominio': form.get('baja_dominio', 'No'),

        # Patente
        'patente_estado': form.get('patente_estado', 'Sin datos'),
        'patente_monto_total': form.get('patente_monto_total', '').strip(),
        'patente_periodos': form.get('patente_periodos', '').strip(),
        'patente_obs': form.get('patente_obs', '').strip(),

        # Precio
        'precio_min': form.get('precio_min', '').strip(),
        'precio_max': form.get('precio_max', '').strip(),
        'precio_fuente': form.get('precio_fuente', '').strip(),
        'precio_fecha': form.get('precio_fecha', '').strip(),
        'precio_obs': form.get('precio_obs', '').strip(),

        # Observaciones
        'observaciones': form.get('observaciones', '').strip(),
    }

    # Arrays: multas
    multa_fechas = form.getlist('multa_fecha[]')
    multa_descs = form.getlist('multa_descripcion[]')
    multa_organismos = form.getlist('multa_organismo[]')
    multa_montos = form.getlist('multa_monto[]')
    datos['multas'] = [
        {'fecha': f, 'descripcion': d, 'organismo': o, 'monto': m}
        for f, d, o, m in zip(multa_fechas, multa_descs, multa_organismos, multa_montos)
        if f.strip() or d.strip()  # descarta filas completamente vacías
    ]

    # Arrays: embargos
    emb_tipos = form.getlist('embargo_tipo[]')
    emb_organismos = form.getlist('embargo_organismo[]')
    emb_montos = form.getlist('embargo_monto[]')
    datos['embargos'] = [
        {'tipo': t, 'organismo': o, 'monto': m}
        for t, o, m in zip(emb_tipos, emb_organismos, emb_montos)
        if t.strip() or o.strip()
    ]

    # Arrays: titulares históricos
    tit_ordenes = form.getlist('titular_orden[]')
    tit_nombres = form.getlist('titular_hist_nombre[]')
    tit_desdes = form.getlist('titular_hist_desde[]')
    tit_hastas = form.getlist('titular_hist_hasta[]')
    datos['titulares'] = [
        {'orden': o, 'nombre': n, 'desde': d, 'hasta': h}
        for o, n, d, h in zip(tit_ordenes, tit_nombres, tit_desdes, tit_hastas)
        if n.strip()
    ]

    # Arrays: recalls
    rec_fechas = form.getlist('recall_fecha[]')
    rec_descs = form.getlist('recall_descripcion[]')
    rec_estados = form.getlist('recall_estado[]')
    datos['recalls'] = [
        {'fecha': f, 'descripcion': d, 'estado': e}
        for f, d, e in zip(rec_fechas, rec_descs, rec_estados)
        if d.strip()
    ]

    return datos

def generar_pdf_informe(pedido, datos):
    """Renderiza el template HTML y lo convierte a PDF con WeasyPrint.
    Devuelve bytes del PDF."""
    from flask import render_template
    from datetime import datetime
    from weasyprint import HTML as WeasyprintHTML  # <-- se importa solo cuando se llama la función
    from datetime import datetime

    fecha_emision = datetime.now().strftime('%d/%m/%Y %H:%M')

    html_str = render_template(
        'informe_pdf.html',
        pedido=pedido,
        datos=datos,
        fecha_emision=fecha_emision
    )

    pdf_bytes = WeasyprintHTML(string=html_str, base_url='').write_pdf()
    return pdf_bytes

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        usuario = Usuario.query.filter_by(email=email).first()

        if usuario and check_password_hash(usuario.password, password):
            user_obj = User(usuario.id)
            login_user(user_obj)
            flash('Inicio de sesión exitoso.', 'success')
            return redirect(url_for('panel'))

        flash('Usuario o contraseña incorrecto.', 'error')

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Cerraste sesión correctamente.', 'success')
    return redirect(url_for('login'))

@app.route('/panel')
@login_required
def panel():
    # Solo verifica PDFs del usuario actual
    actualizar_pedidos_con_pdf(current_user.id)

    page = request.args.get('page', 1, type=int)
    per_page = 10

    # Buscar por patente (dominio)
    busqueda = request.args.get('buscar', '').upper().strip()

    usuario = Usuario.query.get_or_404(current_user.id)

    # Filtrar solo por pedidos de este usuario
    query = Pedido.query.filter_by(usuario_id=current_user.id)

    # Si hay texto de búsqueda, filtrar por dominio
    if busqueda:
        query = query.filter(Pedido.dominio.like(f"%{busqueda}%"))

    # Aplicar orden y paginación
    pedidos_paginados = query.order_by(Pedido.fecha_pedido.desc()).paginate(page=page, per_page=per_page)

    # Renderizar plantilla
    return render_template(
        'panel.html',
        pedidos=pedidos_paginados.items,
        usuario=usuario,
        pagination=pedidos_paginados,
        busqueda=busqueda
    )

    
@app.route('/nuevo_pedido', methods=['GET', 'POST'])
@login_required
def nuevo_pedido():
    if request.method == 'POST':
        dominio = request.form['dominio'].upper().strip()

        # Obtenemos el objeto real del usuario
        usuario = Usuario.query.get(current_user.id)

        nuevo = Pedido(
            dominio=dominio,
            fecha_pedido=datetime.now(),
            estado='Pendiente',
            usuario_id=current_user.id,
            cliente_nombre=usuario.nombre
        )

        db.session.add(nuevo)
        db.session.commit()

        # -------- Generar el PDF (ejemplo básico) --------
        #ruta_local = f"informes/informe_{nuevo.id}.pdf"
        #os.makedirs("informes", exist_ok=True)  # Asegura que la carpeta exista
        #with open(ruta_local, "wb") as f:
        #    f.write(f"Informe del dominio {dominio}".encode("utf-8"))  # Podés reemplazar esto por tu lógica real

        # -------- Subir a Supabase Storage --------
        #nombre_en_bucket = f"informe_{nuevo.id}.pdf"
        #try:
        #    with open(ruta_local, "rb") as archivo:
        #        supabase.storage.from_("informes").upload(nombre_en_bucket, archivo, {"upsert": True})
        #    url_publica = supabase.storage.from_("informes").get_public_url(nombre_en_bucket)
        #    nuevo.url_pdf = url_publica
        #    db.session.commit()
        #except Exception as e:
        #    flash("El pedido fue creado, pero hubo un problema al subir el informe a la nube.", "warning")
        #    print("Error Supabase:", e)

        # -------- Enviar el email --------
        try:
            msg = Message(
                'Nuevo Pedido Creado',
                sender='hg.rodriguez1988@gmail.com',
                recipients=['hg.rodriguez1988@gmail.com']
            )
            msg.body = f'Se ha creado un nuevo pedido con el dominio: {dominio}.\nID del pedido: {nuevo.id}.'
            mail.send(msg)
            flash('¡El pedido se creó y el correo se envió con éxito!', 'success')
        except Exception as e:
            flash('El pedido se creó, pero no se pudo enviar el correo.', 'warning')
            print(e)

        return redirect(url_for('panel'))

    return render_template('nuevo_pedido.html')


@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        nombre = request.form['nombre']
        email = request.form['email']
        telefono = request.form['telefono']
        provincia = request.form['provincia']
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        if password != confirm_password:
            flash('Las contraseñas no coinciden.', 'danger')
            return redirect(url_for('registro'))

        usuario_existente = Usuario.query.filter_by(email=email).first()
        if usuario_existente:
            flash('El correo ya está registrado. Iniciá sesión o usá otro correo.', 'error')
            return redirect(url_for('registro'))
        
        nuevo_usuario = Usuario(
            nombre=nombre,
            email=email,
            telefono=telefono,
            provincia=provincia,
            password=generate_password_hash(password)
        )
        db.session.add(nuevo_usuario)
        db.session.commit()

        flash('Registro exitoso. Ahora podés iniciar sesión.', 'success')
        return redirect(url_for('login'))

    return render_template('registro.html')

@app.route('/pedido/<int:id>')
def ver_pedido(id):
    pedido = Pedido.query.get_or_404(id)
    if pedido.usuario_id != current_user.id:
        return 'Acceso denegado'

    return render_template('detalle_pedido.html', pedido=pedido)

@app.route('/pedido/<int:id>/eliminar', methods=['POST'])
def eliminar_pedido(id):
    pedido = Pedido.query.get_or_404(id)

    #if pedido.usuario_id != session['usuario_id']:
    if pedido.usuario_id != current_user.id:
        return 'Acceso denegado'

    db.session.delete(pedido)
    db.session.commit()
    flash('Pedido eliminado.', 'success')
    return redirect(url_for('panel'))

@app.route('/contacto', methods=['GET', 'POST'])
def contacto():
    if request.method == 'POST':
        nombre = request.form['nombre']
        email = request.form['email']
        texto = request.form['texto']

        nuevo_mensaje = Mensaje(nombre=nombre, email=email, texto=texto)
        db.session.add(nuevo_mensaje)
        db.session.commit()

        # Enviar email
        msg = Message('Nuevo mensaje de contacto', recipients=['hg.rodriguez1988@gmail.com'])
        msg.body = f'Nombre: {nombre}\nEmail: {email}\nMensaje:\n{texto}'
        mail.send(msg)
        return render_template('contacto.html', enviado=True)

    return render_template('contacto.html', enviado=False)

@app.route('/panel/informes')
@login_required
def informes():
    pedidos = Pedido.query.filter_by(estado='En espera').all()  # Solo pedidos pendientes
    return render_template('informes.html', pedidos=pedidos)

@app.route('/panel/informes/actualizar_estado/<int:pedido_id>', methods=['POST'])
@login_required
def actualizar_estado(pedido_id):
    pedido = Pedido.query.get_or_404(pedido_id)
    pedido.estado = 'En proceso'  # Cambiar el estado cuando se empieza a trabajar
    db.session.commit()
    flash('Estado actualizado.', 'success')
    return redirect('/panel/informes')

@app.route('/panel/informes/terminar/<int:pedido_id>', methods=['POST'])
@login_required
def terminar(pedido_id):
    pedido = Pedido.query.get_or_404(pedido_id)
    pedido.estado = 'Terminado'  # Cambiar el estado a terminado
    db.session.commit()
    flash('Pedido terminado.', 'success')
    return redirect('/panel/informes')

@app.errorhandler(404)
def pagina_no_encontrada(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def error_interno(error):
    return render_template('500.html'), 500

@app.route('/')
def inicio():
    return render_template('inicio.html')

from flask import send_file

@app.route('/descargar/<int:id>')
@login_required
def descargar_informe(id):
    pedido = Pedido.query.get_or_404(id)

    if not pedido.url_pdf:
        flash("El informe aún no está disponible para descargar.", "warning")
        return redirect(url_for('panel'))

    # Ruta del archivo local si lo estás buscando ahí
    ruta_archivo = f"informes/informe_{pedido.id}.pdf"

    if not os.path.exists(ruta_archivo):
        flash("El archivo no se encuentra disponible en el servidor.", "warning")
        return redirect(url_for('panel'))

    return send_file(ruta_archivo, as_attachment=True)

@app.route('/robots.txt')
def robots_txt():
    return send_from_directory(app.root_path, 'robots.txt', mimetype='text/plain')

@app.route('/terminos')
def terminos():
    return render_template('terminos.html')

@app.route('/privacidad')
def privacidad():
    return render_template('privacidad.html')

@app.route('/admin/informe/<int:id>', methods=['GET', 'POST'])
@login_required
def cargar_informe(id):
    if not es_admin():
        flash('Acceso restringido.', 'danger')
        return redirect(url_for('panel'))

    pedido = Pedido.query.get_or_404(id)

    # Cargar datos previos si existen (para re-editar)
    datos = {}
    if pedido.datos_json:
        try:
            datos = json.loads(pedido.datos_json)
        except Exception:
            datos = {}

    if request.method == 'POST':
        accion = request.form.get('accion', 'guardar')
        datos  = parsear_datos_formulario(request.form)

        # Guardar siempre
        pedido.datos_json = json.dumps(datos, ensure_ascii=False)

        if accion == 'generar':
            try:
                pdf_bytes = generar_pdf_informe(pedido, datos)

                # Nombre del archivo en Supabase
                nombre_archivo = f"{pedido.id}_{pedido.dominio.upper()}.pdf"

                # Subir a Supabase (upsert para sobreescribir si ya existe)
                bucket = supabase.storage.from_(BUCKET_NAME)
                bucket.upload(
                    path=nombre_archivo,
                    file=pdf_bytes,
                    file_options={"content-type": "application/pdf", "upsert": "true"}
                )

                url_publica = bucket.get_public_url(nombre_archivo)
                pedido.url_pdf = url_publica
                pedido.estado  = 'Terminado'
                db.session.commit()

                # Notificar al cliente
                try:
                    usuario = Usuario.query.get(pedido.usuario_id)
                    msg = Message(
                        subject='Tu informe vehicular ya está disponible',
                        recipients=[usuario.email],
                        body=(
                            f"Hola {usuario.nombre},\n\n"
                            f"Tu informe del dominio {pedido.dominio} ya está listo.\n"
                            f"Podés descargarlo desde tu panel: https://habemusdata.com.ar/panel\n\n"
                            f"Gracias por confiar en HabemusData.\n"
                        )
                    )
                    mail.send(msg)
                except Exception as e:
                    app.logger.warning(f'Email no enviado para pedido {pedido.id}: {e}')

                flash(f'✓ PDF generado y publicado. El cliente ya puede descargarlo.', 'success')
                return redirect(url_for('informes'))

            except Exception as e:
                app.logger.error(f'Error generando PDF pedido {pedido.id}: {e}')
                db.session.commit()  # Guardamos los datos igual
                flash(f'Error al generar el PDF: {str(e)}. Los datos quedaron guardados.', 'danger')

        else:
            # Solo guardar borrador
            db.session.commit()
            flash('Borrador guardado correctamente.', 'success')

    return render_template('cargar_informe.html', pedido=pedido, datos=datos)


# ── RUTA: Preview del PDF en el navegador (útil para debug) ─────────
@app.route('/admin/informe/<int:id>/preview')
@login_required
def preview_informe(id):
    if not es_admin():
        return 'Acceso restringido', 403

    pedido = Pedido.query.get_or_404(id)
    datos = {}
    if pedido.datos_json:
        try:
            datos = json.loads(pedido.datos_json)
        except Exception:
            datos = {}

    from datetime import datetime
    fecha_emision = datetime.now().strftime('%d/%m/%Y %H:%M')

    # Renderiza el HTML del PDF directo en el navegador para verificar diseño
    return render_template('informe_pdf.html', pedido=pedido, datos=datos, fecha_emision=fecha_emision)


if __name__ == '__main__':
    app.run(debug=False, host="0.0.0.0", port=8000)