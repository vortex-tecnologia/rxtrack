from django.urls import path
from django.http import HttpResponse
from core.admin_public import public_admin_site

def public_index(request):
    html = """
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>RXTrack SaaS - Plataforma Logística</title>
        <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;800&display=swap" rel="stylesheet">
        <style>
            body {
                font-family: 'Outfit', sans-serif;
                background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%);
                color: #ffffff;
                margin: 0;
                display: flex;
                align-items: center;
                justify-content: center;
                min-height: 100vh;
                text-align: center;
            }
            .container {
                max-width: 600px;
                padding: 40px;
                background: rgba(255, 255, 255, 0.03);
                backdrop-filter: blur(10px);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 24px;
                box-shadow: 0 20px 50px rgba(0, 0, 0, 0.3);
            }
            h1 {
                font-size: 3rem;
                font-weight: 800;
                margin-bottom: 20px;
                background: linear-gradient(90deg, #38bdf8, #818cf8);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
            }
            p {
                font-size: 1.15rem;
                line-height: 1.6;
                color: #94a3b8;
                margin-bottom: 30px;
            }
            .subdomain-badge {
                display: inline-block;
                padding: 10px 24px;
                background: rgba(56, 189, 248, 0.1);
                border: 1px solid rgba(56, 189, 248, 0.3);
                color: #38bdf8;
                border-radius: 9999px;
                font-weight: 600;
                margin-top: 10px;
                font-size: 1.1rem;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>RXTrack SaaS</h1>
            <p>Seja bem-vindo à nossa plataforma logística inteligente. Cada empresa possui um endereço de acesso exclusivo.</p>
            <p>Por favor, acesse utilizando o subdomínio da sua empresa:</p>
            <div class="subdomain-badge">exemplo.rxtrack.com.br</div>
        </div>
    </body>
    </html>
    """
    return HttpResponse(html)

from django.shortcuts import redirect

def redirect_to_admin(request):
    return redirect('/admin/')

urlpatterns = [
    path('admin/', public_admin_site.urls),
    path('', redirect_to_admin, name='public_index'),
]

from django.urls import re_path
from django.views.static import serve
from django.conf import settings

# Servir arquivos de mídia também pelo schema público (em ambiente sem Nginx)
urlpatterns += [
    re_path(r'^media/(?P<path>.*)$', serve, {
        'document_root': settings.MEDIA_ROOT,
    }),
]
