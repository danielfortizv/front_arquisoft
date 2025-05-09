# escalabilidad/middleware.py
from django.shortcuts import redirect
from django.urls import reverse

class LoginRequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        # URLs que no requieren autenticación
        self.exempt_urls = ['/login/', '/admin/', '/health/', '/metrics/']

    def __call__(self, request):
        # Verificar si la URL no requiere autenticación
        if any(request.path_info.startswith(url) for url in self.exempt_urls):
            return self.get_response(request)
        
        # Verificar si el usuario está autenticado
        if 'usuario' not in request.session:
            return redirect('login')
        
        return self.get_response(request)