from django.shortcuts import redirect
from django.contrib import messages
from functools import wraps
from django.core.exceptions import ObjectDoesNotExist


# usuarios/decorators.py
from django.shortcuts import redirect
from functools import wraps

# usuarios/decorators.py
from django.shortcuts import redirect
from functools import wraps

def apenas_operacional(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        # Se não está logado, vai para o login real
        if not request.user.is_authenticated:
            return redirect('/login/')

        # Verifica apenas a permissão. 
        # Se a view der erro (tipo Manifesto 404), o Django deve mostrar o erro, 
        # e não te deslogar.
        if hasattr(request.user, 'motorista_perfil') and \
           request.user.motorista_perfil.tipo_usuario in ['OPERACIONAL', 'SAC', 'GESTOR']:
            return view_func(request, *args, **kwargs)
        
        # Se for motorista, manda para o app
        return redirect('/app/')
    return _wrapped_view