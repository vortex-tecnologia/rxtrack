from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_decode
from django.utils.encoding import force_str
from django.contrib import messages

def redefinir_senha_view(request, uidb64, token):
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user is not None and default_token_generator.check_token(user, token):
        if request.method == 'POST':
            nova_senha = request.POST.get('senha')
            confirmacao_senha = request.POST.get('senha_confirmacao')

            if nova_senha and nova_senha == confirmacao_senha:
                user.set_password(nova_senha)
                user.save()
                messages.success(request, 'Sua senha foi redefinida com sucesso. Faça login para continuar.')
                return redirect('/login/')
            else:
                messages.error(request, 'As senhas não coincidem ou são inválidas.')

        return render(request, 'desktop/paginas/redefinir_senha.html', {'validlink': True})
    else:
        return render(request, 'desktop/paginas/redefinir_senha.html', {'validlink': False})
