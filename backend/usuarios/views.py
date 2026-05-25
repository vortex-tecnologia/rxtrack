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
class CustomTokenRefreshView(TokenRefreshView):
    permission_classes = [AllowAny]