from django.urls import path
from . import views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('', views.index, name='index'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('usuarios/', views.listar_usuarios, name='listar_usuarios'),
    path('eventos/', views.obtener_eventos, name='obtener_eventos'),
    path("pacientes/<str:paciente_id>/", views.perfil_paciente, name="perfil_paciente"),
    path("pacientes_con_examen/", views.pacientes_con_examen, name="pacientes_con_examen"),
    path("pacientes/<str:paciente_id>/mri/", views.examenes_mri, name="examenes_mri"),
    path('pacientes/<int:paciente_id>/mri/<int:examen_id>/', views.ver_mri, name='ver_mri'),
    path('dashboard_admin/', views.dashboard_admin, name='dashboard_admin'),
    path('dashboard_medico/', views.dashboard_medico, name='dashboard_medico'),
    path("pacientes/", views.pacientes, name="pacientes"),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
