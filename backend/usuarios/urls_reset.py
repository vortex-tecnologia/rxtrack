from django.urls import path
from . import views_reset

urlpatterns = [
    path('', views_reset.redefinir_senha_view, name='redefinir_senha'),
]
