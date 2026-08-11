# manifesto/rotas/init.py
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from manifesto.models import Manifesto


class AppInitView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        motorista = request.user.motorista_perfil

        manifesto = Manifesto.objects.filter(
            motorista=motorista,
            status='EM_TRANSPORTE'
        ).first()

        if manifesto:
            return Response({
                'tela': 'NOTAS',
                'manifesto_id': manifesto.id
            })

        return Response({'tela': 'BUSCA'})
