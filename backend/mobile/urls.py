# mobile/urls.py

from django.urls import path
from django.views.generic import RedirectView
from . import views

urlpatterns = [
    # Rota raiz do PWA (pode ser / ou /app/)
    path('', views.app_view, name='app_home'), 
    
    # Rota específica de Login redirecionada para a raiz /login/
    path('login/', RedirectView.as_view(url='/login/', permanent=True), name='app_login'),
    path('api/v1/save-webpush/', views.save_webpush_token, name='save_webpush_custom'),
    
    # Outras rotas do PWA podem ser adicionadas aqui
]