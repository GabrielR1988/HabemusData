from flask import Flask, render_template, redirect, url_for, request, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, current_user, logout_user
from flask_wtf import FlaskForm
from flask import session
from wtforms import StringField, PasswordField
from wtforms.validators import DataRequired
from datetime import datetime
import random, re, os
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import timedelta
from flask_mail import Mail, Message
from flask import flash

app = Flask(__name__)
app.config['SECRET_KEY'] = 'mi_clave_secreta'

#Tiempo de sesion de 15 minutos
app.permanent_session_lifetime = timedelta(minutes=15)

# Configurar la base de datos SQLite
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'data.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Configuración del servidor SMTP
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'hg.rodriguez1988@gmail.com'
app.config['MAIL_PASSWORD'] = 'neba mcqa kqjg xdaf'
app.config['MAIL_DEFAULT_SENDER'] = 'hg.rodriguez1988@gmail.com'

mail = Mail(app)

# Inicializar SQLAlchemy
db = SQLAlchemy(app)

class Usuario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    nombre = db.Column(db.String(100))

class Pedido(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cliente_nombre = db.Column(db.String(100))
    fecha_pedido = db.Column(db.DateTime, default=datetime.utcnow)
    estado = db.Column(db.String(50), default='En espera')  # Nuevo campo de estado
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    dominio = db.Column(db.String(20))

    def __repr__(self):
        return f'<Pedido {self.id} - {self.cliente_nombre}>'

# Inicializamos Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Definimos un usuario simple (en un entorno real se haría con base de datos)
class User(UserMixin):
    def __init__(self, id):
        self.id = id

# Usuarios simulados
#users = {'admin': {'password': 'admin123'}}

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
        username = request.form['username']
        password = request.form['password']

        usuario = Usuario.query.filter_by(username=username).first()

        #if usuario and check_password_hash(usuario.password, password):
            #session['usuario_id'] = usuario.id
            #flash('Inicio de sesión exitoso.', 'success')
            #return redirect(url_for('panel'))

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
    #if 'usuario_id' not in session:
    #    return redirect(url_for('login'))

    pedidos = Pedido.query.filter_by(usuario_id=current_user.id).order_by(Pedido.fecha_pedido.desc()).all()
    return render_template('panel.html', pedidos=pedidos)
    
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

        # Guardar el pedido en la base de datos
        db.session.add(nuevo)
        db.session.commit()
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
            print(e)  # Opcional: log para depurar

        return redirect(url_for('panel'))

    return render_template('nuevo_pedido.html')


@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        usuario_existente = Usuario.query.filter_by(username=username).first()
        if usuario_existente:
            flash('El correo ya está registrado. Iniciá sesión o usá otro correo.', 'error')
            return redirect(url_for('registro'))

        nueva_contraseña = generate_password_hash(password)
        nuevo_usuario = Usuario(username=username, password=nueva_contraseña)
        db.session.add(nuevo_usuario)
        db.session.commit()

        flash('Registro exitoso. Ahora podés iniciar sesión.', 'success')
        return redirect(url_for('login'))

    return render_template('registro.html')

@app.route('/pedido/<int:id>')
def ver_pedido(id):
    pedido = Pedido.query.get_or_404(id)

    # Verifica que el pedido sea del usuario logueado
    #if pedido.usuario_id != session['usuario_id']:
    if pedido.usuario_id != int(current_user.id):
        return 'Acceso denegado'

    return render_template('detalle_pedido.html', pedido=pedido)

@app.route('/pedido/<int:id>/eliminar', methods=['POST'])
def eliminar_pedido(id):
    pedido = Pedido.query.get_or_404(id)

    #if pedido.usuario_id != session['usuario_id']:
    if pedido.usuario_id != int(current_user.id):
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


@app.before_request
def mantener_sesion():
    session.modified = True

@app.route('/')
def inicio():
    return render_template('inicio.html')


if __name__ == '__main__':
    app.run(debug=True)