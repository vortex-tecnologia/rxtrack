# usuarios/serializers.py

from rest_framework import serializers
from .models import Motorista
from django.contrib.auth.models import User

## 1. Serializer para entrada de dados de Login
class MotoristaLoginSerializer(serializers.Serializer):
    """
    Define os campos esperados na requisição POST de login.
    O 'username' será mapeado para o CPF no frontend.
    """
    # Recebe o CPF (que será o 'username' do User)
    username = serializers.CharField(max_length=11, label="CPF")
    # Recebe a senha (write_only garante que a senha não seja retornada)
    password = serializers.CharField(write_only=True)

    # Nota: A validação e a geração do token são feitas pelas views do JWT.


## 2. Serializer para a saída dos dados do Perfil do Motorista
class MotoristaPerfilSerializer(serializers.ModelSerializer):
    """
    Retorna os dados do motorista logado (vinculado ao token JWT).
    """
    # Mapeia o campo username do modelo User para o CPF, garantindo que seja read-only
    cpf = serializers.CharField(read_only=True)
    
    # O campo 'username' da tabela User (que contém o CPF)
    user_username = serializers.CharField(source='user.username', read_only=True, label="CPF do Usuário")

    class Meta:
        model = Motorista
        fields = (
            'cpf', 
            'nome_completo', 
            'cnh_numero', 
            'tipo_usuario', 
            'foto_perfil',
            'user_username',
        )
        read_only_fields = fields

from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
import re
from usuarios.models import PreCadastroSAC

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Sobrescreve o login padrão (JWT) para verificar se o CPF tentado existe na lista de
    Pré-Cadastro do SAC. Se existir e não tiver conta no Django, a conta é criada automaticamente.
    """
    def validate(self, attrs):
        cpf_digitado = attrs.get('username') or attrs.get('cpf')
        
        if cpf_digitado:
            cpf_limpo = re.sub(r'\D', '', cpf_digitado)
            # Garanta que o username passado para a autenticação final seja o limpo
            attrs['username'] = cpf_limpo
            
            # Se não existe usuário no Django com esse CPF
            if not User.objects.filter(username=cpf_limpo).exists():
                pre_cadastro = PreCadastroSAC.objects.filter(cpf=cpf_limpo, ativo=True).first()
                if pre_cadastro:
                    # Cria o User do Django (senha será a que o usuário preencheu agora)
                    user = User.objects.create_user(
                        username=cpf_limpo,
                        password=attrs.get('password'),
                        first_name=pre_cadastro.nome.split()[0], # Primeiro nome
                    )
                    user.is_staff = True # SAC precisa acessar painel web, que pode ter partes do admin
                    user.save()
                    
                    # Cria o perfil Motorista (usado unificadamente para todos)
                    motorista, created = Motorista.objects.get_or_create(user=user)
                    motorista.cpf = cpf_limpo
                    motorista.nome_completo = pre_cadastro.nome
                    motorista.filial = pre_cadastro.filial
                    motorista.tipo_usuario = 'SAC'
                    motorista.cargo = 'GESTOR' if pre_cadastro.is_gestor else 'MEMBRO'
                    motorista.save()

        # Processo normal de validação de senha (se recem criado, a senha já confere)
        data = super().validate(attrs)
        
        # Opcional: retorna mais dados em /login
        user = self.user
        if hasattr(user, 'motorista_perfil'):
            data['tipo_usuario'] = user.motorista_perfil.tipo_usuario
            data['nome'] = user.motorista_perfil.nome_completo
            
        return data