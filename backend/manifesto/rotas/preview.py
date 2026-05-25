# manifesto/rotas/preview.py
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from manifesto.models import ManifestoBuscaLog


class StatusPreviewManifestoView(APIView):
    permission_classes = [IsAuthenticated]
    print( "Carregando StatusPreviewManifestoView..." )
    def get(self, request):
        motorista = request.user.motorista_perfil
        numero = request.query_params.get('numero_manifesto')

        log = ManifestoBuscaLog.objects.filter(
            motorista=motorista,
            numero_manifesto=numero
        ).first()

        if not log:# or log.status == 'AGUARDANDO':
            return Response({
                'status': 'AGUARDANDO',
                'payload': None
            })
        print ("Retornando status do preview do manifesto..." )
        return Response({
            'status': log.status,
            'payload': log.payload,
            'mensagem_erro': log.mensagem_erro
        })
