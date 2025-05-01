from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('escalabilidad/', views.escalabilidad_view, name='escalabilidad'),
    path('eventos/', views.obtener_eventos, name='obtener_eventos'),
    path('pacientes/<int:paciente_id>/', views.perfil_paciente, name='perfil_paciente'),
    path('pacientes/<int:paciente_id>/mri/', views.examenes_mri, name='examenes_mri'),
    path('pacientes/<int:paciente_id>/mri/<int:examen_id>/', views.ver_mri, name='ver_mri'),
]
