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

    def __repr__(self):
        return f'<Pedido {self.id} - {self.cliente_nombre}>'
    
migrate = Migrate(app, db)
# Crear las tablas en la base de datos

# Inicializamos Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

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


if __name__ == '__main__':
    app.run(debug=False)