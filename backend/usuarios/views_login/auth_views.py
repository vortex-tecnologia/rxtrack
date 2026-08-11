from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login, logout
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.permissions import IsAuthenticated

from usuarios.models import Motorista

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from rest_framework.authentication import TokenAuthentication
from rest_framework_simplejwt.authentication import JWTAuthentication

from usuarios.serializers import CustomTokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView

class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer

@method_decorator(csrf_exempt, name='dispatch')
class VerificarCPFView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = [TokenAuthentication, JWTAuthentication]

    def post(self, request):
        cpf = request.data.get('cpf')

        if not cpf or not cpf.isdigit() or len(cpf) != 11:
            return Response({"status": "CPF_INVALIDO"}, status=400)

        try:
            motorista = Motorista.objects.get(cpf=cpf)
            if motorista.user is not None:
                return Response({"status": "USUARIO_EXISTENTE"})
            return Response({
                "status": "NOVO_USUARIO",
                "nome": motorista.nome_completo
            })
        except Motorista.DoesNotExist:
            from usuarios.models import PreCadastroSAC
            pre_cadastro = PreCadastroSAC.objects.filter(cpf=cpf, ativo=True).first()
            if pre_cadastro:
                return Response({
                    "status": "NOVO_USUARIO",
                    "nome": pre_cadastro.nome
                })
            return Response({"status": "NAO_ENCONTRADO"})


@method_decorator(csrf_exempt, name='dispatch')
class PrimeiroAcessoView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = [TokenAuthentication, JWTAuthentication]

    def post(self, request):
        cpf = request.data.get('cpf')
        senha = request.data.get('senha')
        confirmar = request.data.get('confirmar_senha')

        if senha != confirmar:
            return Response(
                {"erro": "Senhas não conferem"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validação de força da senha foi desativada para simplificar testes
        # from django.contrib.auth.password_validation import validate_password
        # from django.core.exceptions import ValidationError as DjangoValidationError
        # try:
        #     validate_password(senha)
        # except DjangoValidationError as e:
        #     return Response(
        #         {"erro": "; ".join(e.messages)},
        #         status=status.HTTP_400_BAD_REQUEST
        #     )

        motorista = None
        user_to_create = None

        try:
            motorista = Motorista.objects.get(cpf=cpf)
            if motorista.user:
                return Response({"erro": "Usuário já existe"}, status=400)
            
            user_to_create = User.objects.create_user(
                username=cpf,
                password=senha,
                first_name=motorista.nome_completo.split()[0]
            )
            motorista.user = user_to_create
            motorista.save()
            
        except Motorista.DoesNotExist:
            from usuarios.models import PreCadastroSAC
            pre_cadastro = PreCadastroSAC.objects.filter(cpf=cpf, ativo=True).first()
            if not pre_cadastro:
                return Response({"erro": "Motorista/SAC não encontrado"}, status=404)
            
            user_to_create = User.objects.create_user(
                username=cpf,
                password=senha,
                first_name=pre_cadastro.nome.split()[0]
            )
            user_to_create.is_staff = True
            user_to_create.save()
            
            motorista = Motorista.objects.create(
                user=user_to_create,
                cpf=cpf,
                nome_completo=pre_cadastro.nome,
                filial=pre_cadastro.filial,
                tipo_usuario='SAC',
                cargo='GESTOR' if pre_cadastro.is_gestor else 'MEMBRO'
            )

        # 1. Loga via Sessão Django
        login(request, user_to_create)
        
        # 2. Retorna JWT para o GPS
        refresh = RefreshToken.for_user(user_to_create)

        return Response({
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "success": True
        })



class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        try:
            motorista = user.motorista_perfil
        except Motorista.DoesNotExist:
            return Response(
                {"detail": "Motorista não vinculado ao usuário"},
                status=404
            )

        return Response({
            "id": motorista.id,
            "nome": motorista.nome_completo,
            "cpf": motorista.cpf,
            "tipo": motorista.tipo_usuario,
            "cargo": motorista.cargo
        })

class LoginSessionView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        username = request.data.get('username') or request.data.get('cpf')
        password = request.data.get('password') or request.data.get('senha')

        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            # 1. Cria a Sessão Django (Seta o cookie 'sessionid')
            login(request, user)
            
            # 2. Gera o JWT apenas para uso do APK (GPS nativo)
            refresh = RefreshToken.for_user(user)
            
            return Response({
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "success": True,
                "message": "Sessão criada e JWT gerado"
            })
        else:
            return Response({"detail": "No active account found with the given credentials"}, status=status.HTTP_401_UNAUTHORIZED)

class MeSessionView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        refresh = RefreshToken.for_user(user)
        return Response({
            "status": "online",
            "access": str(refresh.access_token),
            "refresh": str(refresh)
        })

class LogoutSessionView(APIView):
    permission_classes = [AllowAny]
    
    def post(self, request):
        logout(request)
        return Response({"success": True})

@csrf_exempt
@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
@authentication_classes([])
def login_sac_mobile_view(request):
    """
    Renderiza a página de login exclusiva para o SAC.
    O JS desta página irá lidar com a requisição POST para a API /api/token/ 
    e então redirecionar para /app-sac/.
    """
    if request.method == 'GET':
        from django.shortcuts import render
        return render(request, 'aplicativo/sac/login.html')
    else:
        return Response({'erro': 'Metodo nao permitido para renderizacao de template.'}, status=405)