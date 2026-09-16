# clientes/decorators.py
from django.shortcuts import redirect
from functools import wraps


def apenas_cliente(view_func):
    """
    Decorator que garante que apenas usuários do tipo CLIENTE acessem o portal.
    Redireciona para /login/ se não autenticado, ou para a área correta se for outro tipo.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('/login/')

        # Verifica se é um cliente
        if hasattr(request.user, 'cliente_perfil'):
            return view_func(request, *args, **kwargs)

        # Se for operacional/motorista, manda para a área correta
        if hasattr(request.user, 'motorista_perfil'):
            tipo = request.user.motorista_perfil.tipo_usuario
            if tipo in ['OPERACIONAL', 'SAC', 'GESTOR', 'FINANCEIRO']:
                return redirect('/dashboard/')
            return redirect('/app/')

        return redirect('/login/')
    return _wrapped_view
