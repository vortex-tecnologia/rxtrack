from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.exceptions import NotFound
from .serializers import MotoristaPerfilSerializer

class PerfilMotoristaView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MotoristaPerfilSerializer

    def get_object(self):
        """
        Retorna o perfil Motorista associado ao usuário autenticado.
        """
        try:
            return self.request.user.motorista_perfil
        except AttributeError:
            raise NotFound("Perfil de motorista não encontrado.")

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.views import TokenRefreshView
from django.utils import timezone
from rest_framework.views import APIView

class CustomTokenRefreshView(TokenRefreshView):
    permission_classes = [AllowAny]
    authentication_classes = [] # Impede que o Django exija CSRF Token se os cookies do WebView forem perdidos


from usuarios.models import DeviceToken

class AtualizarFcmTokenView(APIView):
    """
    Endpoint chamado pelo APK Android para salvar/atualizar o Token FCM (Firebase).
    Aceita autenticação via Sessão/JWT ou envio de device_token.
    POST /auth/fcm-token/
    Payload: { "fcm_token": "...", "device_token": "..." }
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        fcm_token = request.data.get('fcm_token')
        device_token = request.data.get('device_token')

        if not fcm_token:
            return Response({'erro': 'O campo fcm_token é obrigatório.'}, status=status.HTTP_400_BAD_REQUEST)

        motorista = None
        if request.user and request.user.is_authenticated:
            try:
                motorista = request.user.motorista_perfil
            except AttributeError:
                pass

        if not motorista and device_token:
            try:
                device = DeviceToken.objects.select_related('user__motorista_perfil').get(token=device_token, ativo=True)
                motorista = getattr(device.user, 'motorista_perfil', None)
            except DeviceToken.DoesNotExist:
                pass

        if not motorista:
            return Response({'erro': 'Perfil de motorista não autenticado ou device_token inválido.'}, status=status.HTTP_401_UNAUTHORIZED)

        motorista.fcm_token = fcm_token.strip()
        motorista.fcm_token_atualizado_em = timezone.now()
        motorista.save(update_fields=['fcm_token', 'fcm_token_atualizado_em'])

        return Response({
            'sucesso': True,
            'mensagem': 'Token FCM atualizado com sucesso no backend!',
            'fcm_token_atualizado_em': motorista.fcm_token_atualizado_em
        }, status=status.HTTP_200_OK)