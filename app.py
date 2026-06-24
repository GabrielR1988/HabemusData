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
from functools import wraps
import resend
import mercadopago


load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
BUCKET_NAME = os.getenv("BUCKET_NAME")
# Usamos la service_role key porque este es código de servidor confiable
# y necesita bypassear RLS para subir/leer archivos del bucket de informes.
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
resend.api_key = os.getenv("RESEND_API_KEY")

# ── MercadoPago ──────────────────────────────────────────────────────────────
mp_sdk = mercadopago.SDK(os.getenv("MP_ACCESS_TOKEN"))

PRECIOS_PLAN = {
    'bronce': 3500.0,
    'plata':  14500.0,
    'oro':    24000.0,
}
NOMBRES_PLAN = {
    'bronce': 'Informe Bronce - HabemusData',
    'plata':  'Informe Plata - HabemusData',
    'oro':    'Informe Oro - HabemusData',
}

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not es_admin():
            flash('Acceso restringido.', 'danger')
            return redirect(url_for('panel'))
        return f(*args, **kwargs)
    return decorated_function

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
                    usuario = Usuario.query.get(pedido.usuario_id)
                    disparar_email(
                        destinatario=usuario.email,
                        asunto='Tu informe ya está disponible',
                        cuerpo=f"Hola {usuario.nombre},\n\nTu informe del dominio {pedido.dominio} ya está disponible.\nPodés verlo desde tu panel de usuario."
                    )

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

def disparar_email(destinatario, asunto, cuerpo):
    try:
        resend.Emails.send({
            "from": "HabemusData <onboarding@resend.dev>",  # o tu dominio verificado
            "to": destinatario,
            "subject": asunto,
            "text": cuerpo
        })
    except Exception as e:
        app.logger.warning(f"No se pudo enviar el correo: {e}")

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
    plan = db.Column(db.String(20), default='plata')  # 'bronce', 'plata', 'oro'
    datos_json = db.Column(db.Text, nullable=True)    # JSON con todos los datos del informe
    mp_preference_id = db.Column(db.String(200), nullable=True)  # ID de preferencia MP

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
    ADMIN_IDS = [3]  # <-- Poné acá tu ID de usuario admin
    if not current_user.is_authenticated:
        return False
    try:
        return int(current_user.id) in ADMIN_IDS
    except (TypeError, ValueError):
        return False

def parsear_datos_formulario(form):
    SECCIONES = ['vehiculo','radicacion','legal','vtv','gnc','km','impuesto','multas','embargos','titulares','recalls','precios','observaciones']

    datos = {
        # Estado de cada switch (1 = incluir, 0 = no incluir)
        **{f'sec_{s}': '1' if form.get(f'sec_{s}') else '0' for s in SECCIONES},

        # Vehículo
        'marca':      form.get('marca', '').strip(),
        'modelo':     form.get('modelo', '').strip(),
        'anio':       form.get('anio', '').strip(),
        'nro_motor':  form.get('nro_motor', '').strip(),
        'nro_chasis': form.get('nro_chasis', '').strip(),

        # Registro de radicación
        'radicado':             form.get('radicado', '').strip(),
        'radicacion_direccion': form.get('radicacion_direccion', '').strip(),
        'radicacion_telefono':  form.get('radicacion_telefono', '').strip(),
        'radicacion_registro':  form.get('radicacion_registro', '').strip(),
        'radicacion_localidad': form.get('radicacion_localidad', '').strip(),

        # Situación legal
        'robado':       form.get('robado', 'No'),
        'inhabilitado': form.get('inhabilitado', 'No'),
        'baja_dominio': form.get('baja_dominio', 'No'),

        # VTV
        'vtv_organismo': form.get('vtv_organismo', '').strip(),
        'vtv_anio':      form.get('vtv_anio', '').strip(),
        'vtv_centro':    form.get('vtv_centro', '').strip(),
        'vtv_resultado': form.get('vtv_resultado', '').strip(),
        'vtv_fecha':     form.get('vtv_fecha', '').strip(),
        'vtv_falla':     form.get('vtv_falla', '').strip(),

        # GNC
        'gnc_operacion':         form.get('gnc_operacion', '').strip(),
        'gnc_fecha':             form.get('gnc_fecha', '').strip(),
        'gnc_fecha_vencimiento': form.get('gnc_fecha_vencimiento', '').strip(),
        'gnc_nro_oblea':         form.get('gnc_nro_oblea', '').strip(),
        'gnc_lugar':             form.get('gnc_lugar', '').strip(),

        # Kilometraje
        'km_fecha': form.get('km_fecha', '').strip(),
        'km_valor': form.get('km_valor', '').strip(),

        # Infracciones
        'multas_total': form.get('multas_total', '0').strip(),

        # Observaciones generales
        'observaciones': form.get('observaciones', '').strip(),
    }

    # Arrays: impuesto automotor
    imp_anios   = form.getlist('impuesto_anio[]')
    imp_cuotas  = form.getlist('impuesto_cuota[]')
    imp_estados = form.getlist('impuesto_estado[]')
    imp_venc    = form.getlist('impuesto_vencimiento[]')
    imp_orig    = form.getlist('impuesto_importe_original[]')
    imp_act     = form.getlist('impuesto_importe_actualizado[]')
    datos['impuesto'] = [
        {'anio': a, 'cuota': c, 'estado': e, 'vencimiento': v,
         'importe_original': io, 'importe_actualizado': ia}
        for a, c, e, v, io, ia in zip(imp_anios, imp_cuotas, imp_estados, imp_venc, imp_orig, imp_act)
        if a.strip() or c.strip()
    ]

    # Arrays: multas / infracciones (con descripcion por fila)
    multa_fechas   = form.getlist('multa_fecha[]')
    multa_actas    = form.getlist('multa_acta[]')
    multa_importes = form.getlist('multa_importe[]')
    multa_descs    = form.getlist('multa_descripcion[]')
    datos['multas'] = [
        {'fecha': f, 'acta': a, 'importe': i, 'descripcion': d}
        for f, a, i, d in zip(multa_fechas, multa_actas, multa_importes, multa_descs)
        if f.strip() or a.strip()
    ]

    # Arrays: embargos
    emb_tipos      = form.getlist('embargo_tipo[]')
    emb_organismos = form.getlist('embargo_organismo[]')
    emb_montos     = form.getlist('embargo_monto[]')
    datos['embargos'] = [
        {'tipo': t, 'organismo': o, 'monto': m}
        for t, o, m in zip(emb_tipos, emb_organismos, emb_montos)
        if t.strip() or o.strip()
    ]

    # Arrays: titulares históricos
    tit_ordenes = form.getlist('titular_orden[]')
    tit_nombres = form.getlist('titular_hist_nombre[]')
    tit_desdes  = form.getlist('titular_hist_desde[]')
    tit_hastas  = form.getlist('titular_hist_hasta[]')
    datos['titulares'] = [
        {'orden': o, 'nombre': n, 'desde': d, 'hasta': h}
        for o, n, d, h in zip(tit_ordenes, tit_nombres, tit_desdes, tit_hastas)
        if n.strip()
    ]

    # Arrays: recalls
    rec_fechas  = form.getlist('recall_fecha[]')
    rec_marcas  = form.getlist('recall_marca[]')
    rec_modelos = form.getlist('recall_modelo[]')
    rec_descs   = form.getlist('recall_descripcion[]')
    datos['recalls'] = [
        {'fecha': f, 'marca': m, 'modelo': mo, 'descripcion': d}
        for f, m, mo, d in zip(rec_fechas, rec_marcas, rec_modelos, rec_descs)
        if d.strip()
    ]

    # Arrays: precios de referencia
    precio_anios    = form.getlist('precio_anio[]')
    precio_importes = form.getlist('precio_importe[]')
    datos['precios'] = [
        {'anio': a, 'importe': i}
        for a, i in zip(precio_anios, precio_importes)
        if a.strip() or i.strip()
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
    # Si viene la patente desde la landing, la pre-llenamos
    dominio_prefill = request.args.get('dominio', '').upper().strip()
    plan_prefill    = request.args.get('plan', 'plata').lower()

    if request.method == 'POST':
        dominio = request.form.get('dominio', '').upper().strip().replace(' ', '')
        plan    = request.form.get('plan', 'plata').lower()

        if not dominio:
            flash('Ingresá una patente válida.', 'danger')
            return render_template('nuevo_pedido.html', dominio_prefill=dominio, plan_prefill=plan)

        if plan not in PRECIOS_PLAN:
            plan = 'plata'

        usuario = Usuario.query.get(current_user.id)

        # 1. Crear pedido en estado "Pendiente de pago" antes de redirigir a MP.
        #    Así tenemos el ID para usarlo como external_reference.
        nuevo = Pedido(
            dominio=dominio,
            fecha_pedido=datetime.now(),
            estado='Pendiente de pago',
            usuario_id=current_user.id,
            cliente_nombre=usuario.nombre,
            plan=plan,
        )
        db.session.add(nuevo)
        db.session.commit()

        # 2. Crear preferencia en MercadoPago
        base_url = request.host_url.rstrip('/')
        preference_data = {
            "items": [{
                "title":     NOMBRES_PLAN[plan],
                "quantity":  1,
                "unit_price": PRECIOS_PLAN[plan],
                "currency_id": "ARS",
            }],
            "payer": {
                "name":  usuario.nombre,
                "email": usuario.email,
            },
            "external_reference": str(nuevo.id),   # lo usamos para identificar el pedido en el webhook
            "back_urls": {
                "success": f"{base_url}/pago/exito",
                "pending": f"{base_url}/pago/pendiente",
                "failure": f"{base_url}/pago/fallo",
            },
            "auto_return": "approved",              # MP redirige solo si fue aprobado
            "notification_url": f"{base_url}/pago/webhook",
            "statement_descriptor": "HABEMUSDATA",
        }

        try:
            result = mp_sdk.preference().create(preference_data)
            preference = result["response"]

            # Guardar preference_id para referencia futura
            nuevo.mp_preference_id = preference["id"]
            db.session.commit()

            # 3. Redirigir al checkout de MercadoPago
            init_point = preference["init_point"]          # producción
            # init_point = preference["sandbox_init_point"] # descomentar para pruebas
            return redirect(init_point)

        except Exception as e:
            app.logger.error(f'Error creando preferencia MP para pedido {nuevo.id}: {e}')
            # Si MP falla, borramos el pedido fantasma y mostramos error
            db.session.delete(nuevo)
            db.session.commit()
            flash('No se pudo conectar con el sistema de pagos. Intentá de nuevo en unos minutos.', 'danger')
            return render_template('nuevo_pedido.html', dominio_prefill=dominio, plan_prefill=plan)

    return render_template('nuevo_pedido.html', dominio_prefill=dominio_prefill, plan_prefill=plan_prefill)


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
@login_required
def ver_pedido(id):
    pedido = Pedido.query.get_or_404(id)
    if pedido.usuario_id != int(current_user.id):
        return 'Acceso denegado'

    return render_template('detalle-pedido.html', pedido=pedido)

@app.route('/pedido/<int:id>/eliminar', methods=['POST'])
@login_required
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
        disparar_email(msg)
        return render_template('contacto.html', enviado=True)

    return render_template('contacto.html', enviado=False)

@app.route('/panel/informes')
@login_required
@admin_required
def informes():
    pedidos = Pedido.query.filter(
        Pedido.estado.in_(['En espera', 'En proceso'])
    ).order_by(Pedido.fecha_pedido.asc()).all()

    return render_template('informes.html', pedidos=pedidos)

@app.route('/panel/informes/actualizar_estado/<int:pedido_id>', methods=['POST'])
@login_required
@admin_required
def actualizar_estado(pedido_id):
    pedido = Pedido.query.get_or_404(pedido_id)
    pedido.estado = 'En proceso'  # Cambiar el estado cuando se empieza a trabajar
    db.session.commit()
    flash('Estado actualizado.', 'success')
    return redirect('/panel/informes')

@app.route('/panel/informes/terminar/<int:pedido_id>', methods=['POST'])
@login_required
@admin_required
def terminar(pedido_id):
    pedido = Pedido.query.get_or_404(pedido_id)
    pedido.estado = 'Terminado'  # Cambiar el estado a terminado
    db.session.commit()
    flash('Pedido terminado.', 'success')
    return redirect('/panel/informes')

# ── RUTAS DE RETORNO DE MERCADOPAGO ─────────────────────────────────────────

@app.route('/pago/exito')
@login_required
def pago_exito():
    """MP redirige aquí cuando el pago fue APROBADO (auto_return=approved)."""
    pedido_id         = request.args.get('external_reference')
    payment_id        = request.args.get('payment_id')
    merchant_order_id = request.args.get('merchant_order_id')

    pedido = None
    if pedido_id:
        pedido = Pedido.query.filter_by(id=int(pedido_id), usuario_id=int(current_user.id)).first()

    if pedido and pedido.estado == 'Pendiente de pago':
        pedido.estado = 'En espera'
        db.session.commit()

        # Notificar al admin
        disparar_email(
            destinatario='hg.rodriguez1988@gmail.com',
            asunto=f'[HabemusData] Nuevo pago recibido – Pedido #{pedido.id}',
            cuerpo=(
                f'Se acreditó el pago del pedido #{pedido.id}.\n'
                f'Dominio: {pedido.dominio}\n'
                f'Plan: {pedido.plan}\n'
                f'Cliente: {pedido.cliente_nombre}\n'
                f'Payment ID: {payment_id}\n'
            )
        )

        flash('¡Pago acreditado! Estamos procesando tu informe. Te avisaremos por email cuando esté listo.', 'success')
    elif pedido and pedido.estado != 'Pendiente de pago':
        # Ya fue procesado por el webhook, solo mostramos confirmación
        flash('Tu pedido ya fue registrado correctamente.', 'success')
    else:
        flash('Pago recibido. Si no ves tu pedido en unos minutos, contactanos.', 'info')

    return redirect(url_for('panel'))


@app.route('/pago/pendiente')
@login_required
def pago_pendiente():
    """MP redirige aquí cuando el pago quedó PENDIENTE (ej: transferencia, efectivo)."""
    pedido_id = request.args.get('external_reference')
    if pedido_id:
        pedido = Pedido.query.filter_by(id=int(pedido_id), usuario_id=int(current_user.id)).first()
        if pedido and pedido.estado == 'Pendiente de pago':
            pedido.estado = 'Pago pendiente'
            db.session.commit()

    flash('Tu pago está siendo procesado. En cuanto se acredite, comenzamos con tu informe.', 'warning')
    return redirect(url_for('panel'))


@app.route('/pago/fallo')
@login_required
def pago_fallo():
    """MP redirige aquí cuando el pago FALLÓ o fue rechazado."""
    pedido_id = request.args.get('external_reference')
    dominio   = ''
    plan      = 'plata'

    if pedido_id:
        pedido = Pedido.query.filter_by(id=int(pedido_id), usuario_id=int(current_user.id)).first()
        if pedido and pedido.estado == 'Pendiente de pago':
            dominio = pedido.dominio
            plan    = pedido.plan
            # Eliminamos el pedido fallido para que pueda reintentarlo limpio
            db.session.delete(pedido)
            db.session.commit()

    flash('El pago no pudo procesarse. Podés intentarlo nuevamente.', 'danger')
    return render_template('nuevo_pedido.html', dominio_prefill=dominio, plan_prefill=plan)


@app.route('/pago/webhook', methods=['POST'])
def pago_webhook():
    """Webhook IPN de MercadoPago — confirmación server-to-server.
    Se ejecuta independientemente de las back_urls, es la fuente más confiable."""
    try:
        data = request.get_json(silent=True) or {}
        topic   = data.get('type') or request.args.get('topic', '')
        mp_id   = data.get('data', {}).get('id') or request.args.get('id', '')

        if topic == 'payment' and mp_id:
            payment_info = mp_sdk.payment().get(mp_id)
            payment      = payment_info.get('response', {})
            status       = payment.get('status')
            pedido_id    = payment.get('external_reference')

            app.logger.info(f'[MP Webhook] payment_id={mp_id} status={status} pedido={pedido_id}')

            if pedido_id:
                pedido = Pedido.query.get(int(pedido_id))
                if pedido:
                    if status == 'approved' and pedido.estado in ('Pendiente de pago', 'Pago pendiente'):
                        pedido.estado = 'En espera'
                        db.session.commit()
                        app.logger.info(f'[MP Webhook] Pedido {pedido.id} → En espera')
                    elif status in ('rejected', 'cancelled') and pedido.estado == 'Pendiente de pago':
                        pedido.estado = 'Pago fallido'
                        db.session.commit()

    except Exception as e:
        app.logger.error(f'[MP Webhook] Error procesando notificación: {e}')

    # MP espera siempre un 200; si devolvemos otra cosa reintenta
    return '', 200


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

    if pedido.usuario_id != int(current_user.id):
        return 'Acceso denegado'

    if not pedido.url_pdf:
        flash("El informe aún no está disponible para descargar.", "warning")
        return redirect(url_for('panel'))

    nombre_archivo = f"{pedido.id}_{pedido.dominio.upper()}.pdf"

    try:
        bucket = supabase.storage.from_(BUCKET_NAME)
        pdf_bytes = bucket.download(nombre_archivo)
    except Exception as e:
        app.logger.error(f'Error descargando PDF pedido {pedido.id}: {e}')
        flash("No se pudo descargar el informe. Intentá de nuevo más tarde.", "warning")
        return redirect(url_for('panel'))

    return send_file(
        BytesIO(pdf_bytes),
        as_attachment=True,
        download_name=f"informe_{pedido.dominio}.pdf",
        mimetype='application/pdf'
    )

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
@admin_required
def cargar_informe(id):
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
                usuario = Usuario.query.get(pedido.usuario_id)
                disparar_email(
                    destinatario=usuario.email,
                    asunto='Tu informe vehicular ya está disponible',
                    cuerpo=(
                        f"Hola {usuario.nombre},\n\n"
                        f"Tu informe del dominio {pedido.dominio} ya está listo.\n"
                        f"Podés descargarlo desde tu panel: https://habemusdata.com.ar/panel\n\n"
                        f"Gracias por confiar en HabemusData.\n"
                    )
                )

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
@admin_required
def preview_informe(id):
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