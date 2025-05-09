import io
import os  
import time
import requests
import numpy as np
from PIL import Image
import nibabel as nib
from .utils import nifti_a_png  
from django.db import connections
from django.conf import settings
from prometheus_client import Counter, Histogram
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_GET
from django.shortcuts import render, get_object_or_404, redirect
from django.db.utils import OperationalError

BACKEND_URL = "http://34.117.229.99/services"

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
    """Vista para mostrar el formulario de login"""
    # Si el usuario ya está logueado, redirigir al inicio
    if 'usuario' in request.session:
        return redirect('index')
        
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        try:
            # Hacer la petición al backend para verificar el usuario
            response = requests.get(f"{BACKEND_URL}/usuarios/{username}")
            
            # Verificar si la respuesta fue exitosa y contiene datos
            if response.status_code == 200:
                try:
                    user_data = response.json()
                    
                    # Verificar que user_data no sea None y tenga una clave 'contrasena'
                    if user_data and 'contrasena' in user_data:
                        # Verificar la contraseña
                        if user_data.get('contrasena') == password:
                            # Guardar información de sesión
                            request.session['usuario'] = {
                                'username': user_data.get('usuario', ''),
                                'nombre': user_data.get('nombre', ''),
                                'cedula': user_data.get('cedula', ''),
                                'rol': user_data.get('rol', ''),
                                'email': user_data.get('email', ''),
                                'telefono': user_data.get('telefono', '')
                            }
                            
                            # Redirigir a la página principal
                            return redirect('index')
                        else:
                            return render(request, 'escalabilidad/login.html', {'error_message': 'Contraseña incorrecta'})
                    else:
                        return render(request, 'escalabilidad/login.html', {'error_message': 'Datos de usuario incompletos o inválidos'})
                except ValueError:
                    # Error al procesar JSON
                    return render(request, 'escalabilidad/login.html', {'error_message': 'Respuesta inválida del servidor'})
            else:
                return render(request, 'escalabilidad/login.html', {'error_message': f'Usuario no encontrado. Código: {response.status_code}'})
                
        except requests.RequestException as e:
            return render(request, 'escalabilidad/login.html', {'error_message': f'Error al conectar con el servidor: {str(e)}'})
    
    return render(request, 'escalabilidad/login.html')

def logout_view(request):
    """Vista para cerrar sesión"""
    # Eliminar datos de sesión
    if 'usuario' in request.session:
        del request.session['usuario']
    
    return redirect('login')

# Aplicar el decorador login_required a las vistas que requieren autenticación
@login_required
def index(request):
    try:
        response = requests.get(f"{BACKEND_URL}/pacientes")
        response.raise_for_status()  # Verifica errores HTTP
        pacientes = response.json()
    except (requests.RequestException, ValueError) as e:
        # Captura errores de red o JSON
        print(f"Error en index: {type(e).__name__}: {str(e)}")
        pacientes = []
    
    return render(request, 'escalabilidad/index.html', {'pacientes': pacientes})

@login_required
def perfil_paciente(request, paciente_id):
    response = requests.get(f"{BACKEND_URL}/pacientes/{paciente_id}")
    paciente = response.json()
    return render(request, 'escalabilidad/perfil_paciente.html', {'paciente': paciente})

@login_required
def escalabilidad_view(request):
    try:
        # Hacemos una petición GET al backend para obtener la lista de eventos
        response = requests.get(f"{BACKEND_URL}/eventos/")
        response.raise_for_status()
        eventos = response.json()
        error = None
    except requests.RequestException as e:
        eventos = []
        error = f"Error al conectar con el backend: {e}"
        print(error)
    
    context = {'eventos': eventos, 'error': error}
    return render(request, 'escalabilidad/escalabilidad.html', context)

@login_required
def examenes_mri(request, paciente_id):
    response = requests.get(f"{BACKEND_URL}/examenes")
    if response.status_code == 200:
        examenes = response.json()
        # Filtrar exámenes por el paciente_id (cédula)
        examenes = [examen for examen in examenes if examen['cedula'] == str(paciente_id)]
    else:
        examenes = []
        
    return render(request, 'escalabilidad/examenes_mri.html', {'examenes': examenes, 'paciente_id': paciente_id})

@login_required
def ver_mri(request, paciente_id, examen_id):
    # Hacemos la solicitud al backend para obtener la información del examen
    response = requests.get(f"{BACKEND_URL}/examenes/{examen_id}")
    
    if response.status_code == 200:
        examen = response.json()
        ruta_relativa = examen["observaciones"].lstrip("/")  # Eliminamos el slash inicial si existe
        ruta_absoluta = os.path.join(settings.MEDIA_ROOT, ruta_relativa)

        if os.path.exists(ruta_absoluta):
            try:
                # Leer el archivo .nii.gz usando nibabel
                img = nib.load(ruta_absoluta)
                data = img.get_fdata()
                
                # Seleccionamos un slice central de la imagen 3D
                slice_index = data.shape[2] // 2
                slice_data = data[:, :, slice_index]

                # Convertimos la imagen a formato PIL
                slice_image = Image.fromarray(np.uint8(slice_data / np.max(slice_data) * 255))

                # Convertimos la imagen a PNG y la enviamos como respuesta
                response = HttpResponse(content_type="image/png")
                slice_image.save(response, "PNG")
                return response

            except Exception as e:
                return JsonResponse({"error": f"Error al procesar el archivo: {str(e)}"}, status=500)
        else:
            return JsonResponse({"error": f"Archivo no encontrado en la ruta: {ruta_absoluta}"}, status=404)
    else:
        return JsonResponse({"error": "No se pudo obtener la información del examen desde el backend"}, status=500)

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