from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from manifesto.models import Manifesto
from django.utils.datastructures import MultiValueDictKeyError

class VerificarManifestoAtivoView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        motorista = request.user.motorista_perfil
        # Busca se existe algum manifesto com status 'EM_TRANSPORTE'
        manifesto_ativo = Manifesto.objects.filter(
            motorista=motorista, 
            status='EM_TRANSPORTE'
        ).first()

        if manifesto_ativo:
            return Response({
                'tem_manifesto': True,
                'numero_manifesto': manifesto_ativo.numero_manifesto
            })

        return Response({'tem_manifesto': False})