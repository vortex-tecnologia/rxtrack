# manifesto/rotas/status.py (ou onde estiver sua StatusBuscaManifestoView)
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from manifesto.models import ManifestoBuscaLog

class StatusBuscaManifestoView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        motorista = getattr(request.user, 'motorista_perfil', None)
        if not motorista:
            return Response({'erro': 'Usuário sem perfil de motorista.'}, status=403)

        numero = request.query_params.get('numero_manifesto')

        if not numero:
            return Response({'erro': 'Número não informado'}, status=400)

        log = ManifestoBuscaLog.objects.filter(
            numero_manifesto=numero,
            motorista=motorista
        ).first()

        if not log:
            return Response({'status': 'AGUARDANDO'})

        # O segredo está aqui: retornar exatamente o que o JS espera
        return Response({
            'status': log.status,
            'payload': log.payload,
            'mensagem_erro': log.mensagem_erro
        })