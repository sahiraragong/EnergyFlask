import os
import time
from datetime import datetime
from flask import Flask, request, render_template_string
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func

# --- Configuración de la Base de Datos ---
# Azure App Service proporcionará la cadena de conexión a través de las variables de entorno
# Nota: La cadena de conexión de PostgreSQL para SQLAlchemy debe usar 'postgresql' en lugar de 'postgres'
# Usamos un valor predeterminado seguro si no está configurada, aunque la conexión fallará sin la real.
DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    print("FATAL: DATABASE_URL no está configurada. Usando cadena de conexión de fallback.")
    DATABASE_URL = "postgresql://user:password@localhost:5432/dbname"

# Reemplazar 'postgres' por 'postgresql' para SQLAlchemy si la cadena de Azure usa el formato corto
if DATABASE_URL.startswith('postgres://'):
    SQLALCHEMY_DATABASE_URI = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
else:
    SQLALCHEMY_DATABASE_URI = DATABASE_URL

# --- Inicialización de Flask y SQLAlchemy ---
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = SQLALCHEMY_DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False # Recomendado para reducir la sobrecarga

db = SQLAlchemy(app)

# --- Definición del Modelo de Datos (Tabla 'mediciones') ---
class Medicion(db.Model):
    """Modelo para almacenar las mediciones del sensor PZEM-004T."""
    __tablename__ = 'mediciones'

    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.now)
    voltage = db.Column(db.Float, nullable=False)
    current = db.Column(db.Float, nullable=False)
    power = db.Column(db.Float, nullable=False)
    energy = db.Column(db.Float, nullable=False)
    frequency = db.Column(db.Float, nullable=False)
    pf = db.Column(db.Float, nullable=False) # Factor de Potencia (Power Factor)

    def __repr__(self):
        return f"<Medicion {self.timestamp} V:{self.voltage:.2f}>"

# Llamamos a create_all() para asegurar que la tabla exista.
# En un entorno de producción avanzado, esto se haría con herramientas de migración (Alembic).
with app.app_context():
    # Intenta crear las tablas. Si la DB no está accesible, registrará un error.
    try:
        db.create_all()
        print("Base de datos y tabla 'mediciones' inicializada correctamente con SQLAlchemy.")
    except Exception as e:
        print(f"Error CRÍTICO al inicializar la DB con SQLAlchemy: {e}")

# --- Endpoint de API (Receptor para el ESP32) ---

@app.route('/api/measurements', methods=['POST'])
def receive_data():
    """
    Recibe los datos del ESP32, valida y los guarda en la DB usando SQLAlchemy.
    """
    if not request.is_json:
        return {"status": "error", "message": "Content-Type must be application/json"}, 400

    data = request.get_json()

    required_fields = ['voltage', 'current', 'power', 'energy', 'frequency', 'pf']
    if not all(field in data for field in required_fields):
        return {"status": "error", "message": "Faltan campos requeridos en el JSON."}, 400

    try:
        # Crear una nueva instancia del modelo
        new_measurement = Medicion(
            voltage=data['voltage'],
            current=data['current'],
            power=data['power'],
            energy=data['energy'],
            frequency=data['frequency'],
            pf=data['pf']
        )
        
        # Añadir a la sesión y hacer commit
        db.session.add(new_measurement)
        db.session.commit()

        # Retornar una respuesta simple y rápida para el ESP32
        return {"status": "success", "message": "Datos guardados"}, 201
    
    except Exception as e:
        db.session.rollback() # Revertir la transacción si falla
        print(f"Error al guardar datos con SQLAlchemy: {e}")
        return {"status": "error", "message": "Error interno del servidor al guardar"}, 500


# --- Endpoint de Dashboard (Visualización) ---

# Usamos HTML simple con Tailwind CSS para una visualización rápida.
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dashboard de Mediciones de Energía</title>
    <script src="[https://cdn.tailwindcss.com](https://cdn.tailwindcss.com)"></script>
    <link href="[https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap](https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap)" rel="stylesheet">
    <style>body { font-family: 'Inter', sans-serif; }</style>
</head>
<body class="bg-gray-100 min-h-screen p-4 sm:p-8">

    <div class="max-w-4xl mx-auto">
        <h1 class="text-3xl font-bold text-gray-900 mb-6 text-center">
            Monitor de Energía PZEM-004T (Última Medición)
        </h1>
        <p class="text-center text-gray-600 mb-8">
            Datos recibidos de la ESP32 y almacenados en Azure Database.
        </p>

        <div class="bg-white p-6 rounded-xl shadow-2xl border border-blue-200">
            <div class="grid grid-cols-2 md:grid-cols-3 gap-6">
                {{ cards_html }}
            </div>
            <p class="text-sm text-gray-500 mt-6 text-center">
                Última actualización: <span id="last-update">{{ last_update }}</span>
            </p>
        </div>
        
        <div class="mt-10 p-6 bg-white rounded-xl shadow-inner border border-gray-200">
            <h2 class="text-xl font-semibold text-gray-800 mb-4">Consejo de Despliegue en Azure</h2>
            <p class="text-gray-600">
                Asegúrate de que tu cadena de conexión `DATABASE_URL` en Azure App Service esté configurada. Para conexiones con PostgreSQL, Azure a veces necesita que se añadan parámetros como `?sslmode=require` si usas SSL. Si tienes problemas de conexión, revisa la configuración del firewall de tu servidor de base de datos en Azure. 
            </p>
        </div>
    </div>
</body>
</html>
"""

@app.route('/')
def dashboard():
    """Muestra el último registro capturado en un dashboard simple."""
    latest_data = {}
    last_update = "N/A"

    try:
        # Usar el ORM para obtener el último registro. 
        # Ordernar por timestamp de forma descendente y limitar a 1
        latest_record = db.session.execute(
            db.select(Medicion).order_by(Medicion.timestamp.desc()).limit(1)
        ).scalar_one_or_none()
        
        if latest_record:
            # Convertir el objeto ORM a un diccionario para facilitar el manejo
            latest_data = {
                'voltage': latest_record.voltage,
                'current': latest_record.current,
                'power': latest_record.power,
                'energy': latest_record.energy,
                'frequency': latest_record.frequency,
                'pf': latest_record.pf,
            }
            last_update = latest_record.timestamp.strftime("%Y-%m-%d %H:%M:%S")

        else:
            # No hay registros en la DB, usar valores predeterminados
            latest_data = {
                'voltage': 0.0, 'current': 0.0, 'power': 0.0, 
                'energy': 0.0, 'frequency': 0.0, 'pf': 0.0
            }
            last_update = "No hay datos aún"

    except Exception as e:
        print(f"Error al obtener datos con SQLAlchemy: {e}")
        # Si la DB falla, mostramos valores por defecto y un mensaje de error
        latest_data = {
            'voltage': 0.0, 'current': 0.0, 'power': 0.0, 
            'energy': 0.0, 'frequency': 0.0, 'pf': 0.0
        }
        last_update = "Error de conexión a la base de datos"


    # Preparar datos para las tarjetas
    measurements = [
        ("Voltaje (V)", f"{latest_data['voltage']:.2f}", "V", "bg-blue-100 text-blue-800"),
        ("Corriente (A)", f"{latest_data['current']:.3f}", "A", "bg-green-100 text-green-800"),
        ("Potencia (W)", f"{latest_data['power']:.1f}", "W", "bg-red-100 text-red-800"),
        ("Energía (kWh)", f"{latest_data['energy']:.3f}", "kWh", "bg-yellow-100 text-yellow-800"),
        ("Frecuencia (Hz)", f"{latest_data['frequency']:.1f}", "Hz", "bg-purple-100 text-purple-800"),
        ("Factor de Potencia (PF)", f"{latest_data['pf']:.2f}", "", "bg-indigo-100 text-indigo-800"),
    ]

    cards_html = ""
    for title, value, unit, color_class in measurements:
        cards_html += f"""
        <div class="p-4 {color_class} rounded-lg shadow-md transform transition duration-300 hover:scale-[1.03]">
            <p class="text-sm font-medium opacity-80">{title}</p>
            <p class="text-4xl font-extrabold mt-1">
                {value}
                <span class="text-xl font-semibold ml-1 opacity-70">{unit}</span>
            </p>
        </div>
        """

    return render_template_string(HTML_TEMPLATE, cards_html=cards_html, last_update=last_update)

# --- Arranque de la Aplicación ---
# En Azure, Gunicorn ejecutará la aplicación usando este entry point.
# En local, puedes usar el if __name__ == '__main__':
if __name__ == '__main__':
    # Puerto de desarrollo local (el puerto en Azure se gestiona automáticamente)
    app.run(debug=True, host='0.0.0.0', port=5000)
