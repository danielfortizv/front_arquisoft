import io
import os
import shutil  
import jwt
import time
import tempfile
import requests
import numpy as np
from PIL import Image
import nibabel as nib
import concurrent.futures
from .utils import nifti_a_png  
from django.conf import settings
from urllib.parse import urlparse
from django.db import connections
from django.db.utils import OperationalError
from requests.exceptions import RequestException
from prometheus_client import Counter, Histogram
from django.http import JsonResponse, HttpResponse
from requests_toolbelt.downloadutils import stream
from django.views.decorators.http import require_GET
from django.shortcuts import render, get_object_or_404, redirect






LOGIN_URL = 'http://35.188.126.127:3000/login'
BACKEND_URL = "http://34.117.229.99/services"

# ─── API de Historias Clínicas ───────────────────────────────
PACIENTES_API = "http://34.136.217.155:8000/historias/"        # lista
PACIENTE_API  = "http://34.136.217.155:8000/historia/{id}"     # detalle

# ─── API de Exámenes MRI ─────────────────────────────────────
EXAMENES_API  = "http://104.199.116.78:8000/examenes/paciente/{doc}"


# Decorator for views that require login
def login_required(view_func):
    """Decorador para verificar si el usuario está autenticado"""
    def wrapped_view(request, *args, **kwargs):
        if 'usuario' not in request.session:
            return redirect('login')
        return view_func(request, *args, **kwargs)
    return wrapped_view

# Función login_view corregida para manejar el caso de usuario no encontrado

def login_view(request):
    request.session.flush()
    
    if request.method == 'POST':
        usuario = request.POST.get('username')
        contrasena = request.POST.get('password')

        try:
            response = requests.post(LOGIN_URL, json={
                'usuario': usuario,
                'contrasena': contrasena
            })

            if response.status_code == 200:
                token = response.json().get('token')
                decoded_token = jwt.decode(token, options={"verify_signature": False})
                rol = decoded_token.get('rol')

                # Guardar token y rol en sesión
                request.session['token'] = token
                request.session['rol'] = rol
                request.session['usuario'] = usuario

                return redirect('index')  # Ajusta si tienes otra ruta de dashboard
            else:
                return render(request, 'escalabilidad/login.html', {
                    'error_message': 'Credenciales inválidas'
                })
        except Exception as e:
            return render(request, 'escalabilidad/login.html', {
                'error_message': f'Error de conexión: {e}'
            })

    return render(request, 'escalabilidad/login.html')

def logout_view(request):
    """Vista para cerrar sesión"""
    request.session.flush()  # Borra toda la sesión, incluyendo token y rol
    return redirect('login')

# Aplicar el decorador login_required a las vistas que requieren autenticación
@login_required
def index(request):
    rol = request.session.get('rol')
    if rol == 'admin':
        return redirect('dashboard_admin')
    elif rol == 'medico':
        return redirect('dashboard_medico')
    else:
        return redirect('login')  # O error 403



@login_required
def perfil_paciente(request, paciente_id):
    try:
        r = requests.get(PACIENTE_API.format(id=paciente_id), timeout=5)
        r.raise_for_status()
        paciente = r.json()
    except requests.RequestException:
        return HttpResponse("No se pudo cargar la historia clínica", status=502)

    # Ajusta nombres de campos de la API → plantilla
    paciente["cedula"] = paciente.pop("numeroDocumento", paciente_id)
    paciente["alergias"] = ", ".join(paciente.get("alergias", []))
    paciente["antecedentes_medicos"] = "; ".join(paciente.get("cMedicas", []))

    return render(request, "escalabilidad/perfil_paciente.html", {"paciente": paciente})



@login_required
def examenes_mri(request, paciente_id):
    # ① Traemos la lista de exámenes del micro-servicio
    url = f"{settings.EXAMENES_API}{paciente_id}/"
    try:
        exams_raw = requests.get(url, timeout=10).json()
    except Exception as e:
        return render(request, "escalabilidad/examenes_mri.html",
                      {"error": f"No se pudo contactar al API: {e}"})

    # ② Para cada examen generamos/obtenemos su preview
    examenes = []
    for ex in exams_raw:
        try:
            png_rel = nifti_url_to_png(ex["url"], ex["id"])
        except Exception as e:
            png_rel = None         # si algo falla mostramos placeholder
            print(f"[Examen {ex['id']}] error al generar PNG:", e)

        examenes.append({
            "id":  ex["id"],
            "png": png_rel,
        })

    return render(request, "escalabilidad/examenes_mri.html",
                  {"examenes": examenes, "paciente_id": paciente_id})

def url_examenes_paciente(doc: str) -> str:
    """URL completa de la lista de exámenes para un paciente"""
    return EXAMENES_API.format(doc=doc)


@login_required
def ver_mri(request, paciente_id, examen_id):
    """
    Descarga el .nii.gz del examen, genera un PNG del slice central
    y lo envía como respuesta image/png
    """
    try:
        # 1) localizar el examen en la API
        r = requests.get(url_examenes_paciente(paciente_id), timeout=10)
        r.raise_for_status()
        examen = next((e for e in r.json() if e["id"] == examen_id), None)
        if not examen:
            return JsonResponse({"error": "Examen no encontrado"}, status=404)

        url_nii = _gcs_public(examen["url"])

        # 2) descargar el NIfTI a un temporal
        with requests.get(url_nii, stream=True, timeout=20) as remoto:
            remoto.raise_for_status()
            with tempfile.NamedTemporaryFile(suffix=".nii.gz") as tmp:
                for chunk in remoto.iter_content(chunk_size=8192):
                    tmp.write(chunk)
                tmp.flush()

                # 3) abrir y extraer slice central
                img  = nib.load(tmp.name)
                data = img.get_fdata()
                sl   = data[:, :, data.shape[2] // 2]
                png  = Image.fromarray((sl / sl.max() * 255).astype(np.uint8))

        buf = io.BytesIO()
        png.save(buf, format="PNG")
        return HttpResponse(buf.getvalue(), content_type="image/png")

    except Exception as exc:
        # Devuelve 502 para que el front muestre el alt o un toast
        return JsonResponse({"error": str(exc)}, status=502)

@login_required
def obtener_eventos(request):
    try:
        response = requests.get(f"{BACKEND_URL}/eventos/")
        response.raise_for_status()
        eventos = response.json()
    except requests.RequestException as e:
        eventos = []
        print(f"Error al conectar con el backend: {e}")
    
    return render(request, 'escalabilidad/eventos.html', {'eventos': eventos})

@login_required
def detalle_examen_mri(request, sujeto_id):
    # Ruta completa del archivo MRI
    archivo_nifti = os.path.join(settings.MEDIA_ROOT, f'mri_data/sub-{sujeto_id}/anat/sub-{sujeto_id}_acq-iso08_T1w.nii.gz')
    
    # Cargar el archivo usando nibabel
    try:
        img = nib.load(archivo_nifti)
        data = img.get_fdata()
        
        # Vamos a tomar una sola capa de la imagen para mostrarla (por ejemplo, la mitad)
        slice_index = data.shape[2] // 2
        slice_data = data[:, :, slice_index]
        
        # Convertir la imagen a formato PIL
        slice_image = Image.fromarray(np.uint8(slice_data / np.max(slice_data) * 255))

        # Convertir la imagen a PNG y retornar en la respuesta HTTP
        response = HttpResponse(content_type="image/png")
        slice_image.save(response, "PNG")
        return response
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
    
@login_required
def obtener_examenes_mri(request, td, cedula):
    url = f"{BACKEND_URL}/mris/{td}/{cedula}/"  
    response = requests.get(url)
    
    if response.status_code == 200:
        examenes = response.json() 
        return render(request, 'examenes_mri.html', {'examenes': examenes, 'paciente_id': cedula})
    else:
        return JsonResponse({'error': 'No se pudieron obtener los exámenes MRI'}, status=500)


HEALTH_CHECK_COUNTER = Counter(
    'django_health_check_total', 
    'Total number of health checks',
    ['status']
)

HEALTH_CHECK_DURATION = Histogram(
    'django_health_check_duration_seconds',
    'Duration of health check in seconds'
)


def health_check(request):
    start_time = time.time()
    
    # Comprobar la conexión a la base de datos
    db_status = "healthy"
    try:
        connections['default'].cursor()
    except OperationalError:
        db_status = "unhealthy"
    
    end_time = time.time()
    response_time = end_time - start_time
    
    status = "healthy" if db_status == "healthy" else "degraded"
    
    HEALTH_CHECK_COUNTER.labels(status=status).inc()
    HEALTH_CHECK_DURATION.observe(response_time)
    
    return JsonResponse({
        "status": status,
        "database": db_status,
        "response_time": response_time,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
    })
    

def listar_usuarios(request):
    token = request.session.get('token')
    url = 'http://35.192.101.24:3000/usuarios'

    headers = {'Authorization': f'Bearer {token}'}
    response = requests.get(url, headers=headers)
    usuarios = response.json()

    return render(request, 'escalabilidad/usuarios.html', {'usuarios': usuarios})

def dashboard_admin(request):
    return render(request, 'escalabilidad/dashboard_admin.html')

def dashboard_medico(request):
    return render(request, 'escalabilidad/dashboard_medico.html')

@login_required
def pacientes(request):
    try:
        r = requests.get(PACIENTES_API, timeout=5)
        r.raise_for_status()
        
        pacientes = [
            {
                "id":  p["id"],
                "nombre": p["nombre"],
                "cedula": p["numeroDocumento"],  
                "email": p.get("email", ""),
            }
            for p in r.json()
        ]
    except requests.RequestException:
        pacientes = []

    return render(request, "escalabilidad/pacientes.html", {"pacientes": pacientes})

@login_required
def pacientes_con_examen(request):
    try:
        pacientes = requests.get(settings.PACIENTES_API, timeout=5).json()
    except RequestException:
        pacientes = []

    def con_estudios(p):
        try:
            r = requests.get(url_examenes_paciente(p["numeroDocumento"]), timeout=5)
            return p if r.status_code == 200 and r.json() else None
        except RequestException:
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        pacientes_ok = [p for p in pool.map(con_estudios, pacientes) if p]

    return render(request, "escalabilidad/pacientes_con_examen.html",
                  {"pacientes": pacientes_ok})

def _gcs_public(url: str) -> str:
    """
    Convierte un enlace de Google Cloud Storage de forma
    `storage.cloud.google.com/bucket/...`
    a la forma pública `storage.googleapis.com/bucket/...`
    """
    if "storage.cloud.google.com" in url:
        parts = urlparse(url)
        # 0   1         2
        # https://storage.cloud.google.com/bucket/obj
        bucket, *path = parts.path.lstrip("/").split("/", 1)
        return f"https://storage.googleapis.com/{bucket}/{'/'.join(path)}"
    return url

def nifti_url_to_png(url: str, examen_id: int) -> str:
    """
    Descarga un NIfTI (.nii ó .nii.gz) desde `url`, extrae el corte axial
    central y guarda un PNG en MEDIA_ROOT/mri_previews/<examen_id>.png
    """

    # 1⃣  Pedimos el archivo SIN que el servidor lo comprima de nuevo
    headers = {"Accept-Encoding": "identity"}          # ★ NUEVO
    resp = requests.get(url, stream=True, timeout=20, headers=headers)
    resp.raise_for_status()

    # 2⃣  Dejamos que 'requests' haga lo normal  →  ❌ BORRA ESTA LÍNEA
    # resp.raw.decode_content = False

    # ---------- guardamos los bytes tal cual en un tmp -------------
    with tempfile.NamedTemporaryFile(suffix=".nii.gz", delete=False) as tmp:
        shutil.copyfileobj(resp.raw, tmp)
        tmp_path = tmp.name

    try:
        # ---------- leemos el volumen 3-D con nibabel ---------------
        img  = nib.load(tmp_path)             # ahora SÍ reconoce el formato
        data = img.get_fdata()

        slice_ = data[:, :, data.shape[2] // 2]                    # corte central
        norm   = ((slice_ - slice_.min()) / (slice_.ptp() or 1) * 255).astype(np.uint8)

        out_dir  = os.path.join(settings.MEDIA_ROOT, "mri_previews")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"{examen_id}.png")

        Image.fromarray(norm).save(out_path, "PNG")

    finally:
        # limpieza del .nii.gz temporal
        try:
            os.remove(tmp_path)
        except FileNotFoundError:
            pass

    # Ruta relativa que tu plantilla mostrará con {{ examen.png_url }}
    return f"mri_previews/{examen_id}.png"
