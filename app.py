import os
import base64
import json
import zipfile
import re
import shutil
import tempfile # Import for temporary file and directory creation

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv

# Make sure pdfplumber is installed: pip install pdfplumber
import pdfplumber

# Cargar variables de entorno desde .env
load_dotenv()

app = Flask(__name__)
CORS(app) # Habilita CORS para todas las rutas

# --- Configuración desde variables de entorno ---
FLASK_RUN_PORT = os.getenv('FLASK_RUN_PORT', 5000)
FONT_PATH = os.getenv('FONT_PATH', 'assets/arial.ttf') # Ruta a tu fuente TTF
# Si la fuente está en un subdirectorio 'assets' junto a app.py
FONT_FULL_PATH = os.path.join(os.path.dirname(__file__), FONT_PATH)

# --- Contador de Folio (Para producción, usar una base de datos) ---
# En un entorno de producción, este contador DEBE ser persistente (ej. en una base de datos)
# para que no se reinicie cada vez que el servidor se apaga o reinicia.
current_folio = 36

# Ruta a la imagen base del cupón
# Asegúrate de que 'coupon_base.jpg' esté en la carpeta 'assets'
COUPON_BASE_IMAGE_PATH = os.path.join(os.path.dirname(__file__), 'assets', 'coupon_base.jpg')

# --- FUNCIONES AUXILIARES para renombrado de PDFs ---

def limpiar_nombre_archivo(nombre):
    """Elimina caracteres inválidos para nombres de archivo."""
    return re.sub(r'[\\/*?:"<>|]', "", nombre)

def renombrar_pdfs_en_directorio(directorio_base):
    """
    Busca y renombra archivos PDF en el directorio base y en todas sus subcarpetas.
    Retorna una lista de los PDFs renombrados (con sus nuevas rutas relativas)
    y una lista de errores/advertencias.
    """
    print("\n--- 🔎 Iniciando proceso de renombrado ---")
    pdf_procesados = 0
    renombrados_info = []
    advertencias_errores = []

    for dirpath, _, filenames in os.walk(directorio_base):
        for nombre_archivo in filenames:
            if nombre_archivo.lower().endswith('.pdf'):
                pdf_procesados += 1
                ruta_completa_original = os.path.join(dirpath, nombre_archivo)
                relative_path_original = os.path.relpath(ruta_completa_original, directorio_base)

                try:
                    with pdfplumber.open(ruta_completa_original) as pdf:
                        # Ensure there's at least one page
                        if not pdf.pages:
                            msg = f"⚠️ ADVERTENCIA: '{relative_path_original}' no tiene páginas."
                            print(msg)
                            advertencias_errores.append(msg)
                            continue

                        texto_completo = pdf.pages[0].extract_text()
                        if not texto_completo:
                            msg = f"⚠️ ADVERTENCIA: No se pudo extraer texto de la primera página de '{relative_path_original}'."
                            print(msg)
                            advertencias_errores.append(msg)
                            continue

                        lineas = texto_completo.split('\n')
                        nombre_encontrado = None
                        for i, linea in enumerate(lineas):
                            if "Nombre(s) Primer apellido Segundo apellido" in linea:
                                if i > 0:
                                    nombre_encontrado = lineas[i-1].strip()
                                    break

                        if nombre_encontrado:
                            nombre_limpio = limpiar_nombre_archivo(nombre_encontrado)
                            nuevo_nombre_archivo = f"{nombre_limpio}.pdf"
                            ruta_completa_nueva = os.path.join(dirpath, nuevo_nombre_archivo)
                            
                            # Handle case where new name is identical to old name (common if already renamed)
                            if os.path.abspath(ruta_completa_original) != os.path.abspath(ruta_completa_nueva):
                                # If the target file already exists, append a number
                                counter = 1
                                original_base, original_ext = os.path.splitext(nuevo_nombre_archivo)
                                while os.path.exists(ruta_completa_nueva):
                                    nuevo_nombre_archivo = f"{original_base}_{counter}{original_ext}"
                                    ruta_completa_nueva = os.path.join(dirpath, nuevo_nombre_archivo)
                                    counter += 1

                                os.rename(ruta_completa_original, ruta_completa_nueva)
                                print(f"✅ RENOMBRADO: '{relative_path_original}' -> '{os.path.relpath(ruta_completa_nueva, directorio_base)}'")
                                renombrados_info.append(os.path.relpath(ruta_completa_nueva, directorio_base))
                            else:
                                msg = f"ℹ️ INFO: '{relative_path_original}' ya tiene el nombre deseado o no requiere cambio."
                                print(msg)
                                renombrados_info.append(relative_path_original) # Still include in renamed list as it was processed
                        else:
                            msg = f"❌ ERROR: No se encontró el texto clave en '{relative_path_original}'. No se renombró."
                            print(msg)
                            advertencias_errores.append(msg)

                except Exception as e:
                    msg = f"❌ ERROR al procesar '{relative_path_original}': {e}"
                    print(msg)
                    advertencias_errores.append(msg)

    if pdf_procesados == 0:
        msg = "⚠️ ADVERTENCIA: No se encontraron archivos PDF en ninguna carpeta dentro del ZIP."
        print(msg)
        advertencias_errores.append(msg)

    print("--- ✒️ Proceso de renombrado finalizado ---\n")
    return renombrados_info, advertencias_errores

# --- Endpoint para generar el cupón ---
@app.route('/api/generateCoupon', methods=['POST'])
def generate_coupon():
    global current_folio
    data = request.get_json()
    alumni_name = data.get('alumniName')
    recipient_name = data.get('recipientName', '').strip()

    if not alumni_name:
        return jsonify({"error": "El nombre del exalumno es obligatorio."}), 400

    try:
        # Incrementar el folio y formatearlo a 4 dígitos
        current_folio += 1
        folio_number = str(current_folio).zfill(4) # zfill para rellenar con ceros

        # Cargar la imagen base del cupón
        image = Image.open(COUPON_BASE_IMAGE_PATH)
        draw = ImageDraw.Draw(image)

        # Cargar la fuente
        font_size = 32
        try:
            font = ImageFont.truetype(FONT_FULL_PATH, font_size)
        except IOError:
            print(f"Error: No se pudo cargar la fuente en {FONT_FULL_PATH}. Usando fuente predeterminada.")
            font = ImageFont.load_default()
            font_size = 16 # La fuente predeterminada es más pequeña

        # Definir las coordenadas para el texto (ajusta según sea necesario)
        folio_x, folio_y = 160, 28
        alumni_name_x, alumni_name_y = 400, 315
        recipient_name_x, recipient_name_y = 430, 375

        # Escribir el número de folio
        draw.text((folio_x, folio_y), folio_number, font=font, fill=(0, 0, 0)) # Negro

        # Escribir el nombre del exalumno
        draw.text((alumni_name_x, alumni_name_y), alumni_name.upper(), font=font, fill=(0, 0, 0))

        # Escribir el nombre del receptor si se proporciona
        if recipient_name:
            draw.text((recipient_name_x, recipient_name_y), recipient_name.upper(), font=font, fill=(0, 0, 0))

        # Guardar la imagen en un buffer en memoria
        from io import BytesIO
        img_io = BytesIO()
        image.save(img_io, format='JPEG')
        img_io.seek(0)

        # Codificar la imagen a Base64
        base64_image = base64.b64encode(img_io.getvalue()).decode('utf-8')

        print(f"Cupón generado exitosamente para: {alumni_name}, folio: {folio_number}")

        return jsonify({"couponImage": base64_image, "folio": folio_number})

    except FileNotFoundError:
        print(f"Error: Archivo no encontrado. Asegúrate de que '{COUPON_BASE_IMAGE_PATH}' y '{FONT_FULL_PATH}' existan.")
        return jsonify({"error": "Error del servidor: Archivo de imagen o fuente no encontrado."}), 500
    except Exception as e:
        print(f"Error inesperado al generar el cupón: {e}")
        return jsonify({"error": f"Error interno del servidor al generar el cupón: {str(e)}"}), 500

# --- Nuevo Endpoint para renombrar PDFs ---
@app.route('/api/renamePDF', methods=['POST'])
def rename_pdf():
    if 'zip_file' not in request.files:
        return jsonify({"error": "No se encontró el archivo ZIP en la solicitud. Asegúrate de que el nombre del campo sea 'zip_file'."}), 400

    zip_file = request.files['zip_file']

    if not zip_file.filename.endswith('.zip'):
        return jsonify({"error": "El archivo cargado no es un archivo ZIP."}), 400

    # Create temporary directories for processing
    # Vercel's /tmp directory is ephemeral and cleaned up automatically.
    # No manual cleanup needed in 'finally' block for deployment.
    temp_dir = tempfile.mkdtemp()
    extracted_dir = os.path.join(temp_dir, 'extracted_pdfs')
    os.makedirs(extracted_dir)
    output_zip_path = None 

    try:
        uploaded_zip_path = os.path.join(temp_dir, zip_file.filename)
        zip_file.save(uploaded_zip_path)
        print(f"Archivo ZIP guardado temporalmente en: {uploaded_zip_path}")

        print(f"📦 Descomprimiendo '{os.path.basename(uploaded_zip_path)}'...")
        with zipfile.ZipFile(uploaded_zip_path, 'r') as zf:
            zf.extractall(extracted_dir)
        print("¡Descompresión completa!")

        renombrados_info, advertencias_errores = renombrar_pdfs_en_directorio(extracted_dir)

        output_zip_name = 'renombrados.zip'
        output_zip_path = os.path.join(temp_dir, output_zip_name)
        
        print(f"⚙️ Creando archivo '{output_zip_name}' con los PDFs actualizados...")
        with zipfile.ZipFile(output_zip_path, 'w', zipfile.ZIP_DEFLATED) as zip_out:
            for dirpath, _, filenames in os.walk(extracted_dir):
                for filename in filenames:
                    if filename.lower().endswith('.pdf'):
                        full_path = os.path.join(dirpath, filename)
                        arcname = os.path.relpath(full_path, extracted_dir)
                        zip_out.write(full_path, arcname)
        print(f"🎉 Archivo '{output_zip_name}' creado con éxito.")

        # send_file automatically handles closing the file and streaming it.
        # Vercel's environment will clean up temp_dir after the function finishes.
        return send_file(output_zip_path,
                         mimetype='application/zip',
                         as_attachment=True,
                         download_name='renombrados.zip')

    except zipfile.BadZipFile:
        print(f"Error: El archivo cargado '{zip_file.filename}' no es un archivo ZIP válido.")
        return jsonify({"error": "El archivo cargado no es un archivo ZIP válido o está corrupto."}), 400
    except Exception as e:
        print(f"Error inesperado en /api/renamePDF: {e}")
        return jsonify({"error": f"Error interno del servidor al procesar los PDFs: {str(e)}"}), 500
    finally:
        # For Vercel, manual cleanup here is usually not needed as /tmp is ephemeral.
        # On local Windows, this might still cause WinError 32 if the file handle isn't released immediately.
        # But for Vercel, this block can often be removed or simplified.
        if temp_dir and os.path.exists(temp_dir):
            try:
                # Adding a small delay or a more robust cleanup might be needed for *local Windows testing*,
                # but on Vercel's Linux environment, the ephemeral nature usually handles it.
                # For robust cross-platform local testing, consider a separate cleanup script or an in-memory ZIP for the final output.
                # For Vercel, simply removing the manual cleanup for temp_dir is often the fix.
                pass # Removed shutil.rmtree here for Vercel deployment
            except OSError as e:
                print(f"Error al intentar limpiar el directorio temporal {temp_dir}: {e}")


# --- Iniciar el servidor Flask ---
if __name__ == '__main__':
    # print(f"Backend corriendo en http://localhost:{FLASK_RUN_PORT}") # Keep for local debugging visibility
    # app.run(debug=True, port=FLASK_RUN_PORT) # <--- THIS LINE MUST BE COMMENTED OUT OR REMOVED FOR VERCEL
    pass # This 'pass' ensures the block is valid even if app.run is commented/removed.