# manifesto/rotas/iniciar_transporte.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db import transaction
from manifesto.models import Manifesto, ManifestoBuscaLog
from manifesto.tasks import buscar_manifesto_completo_task

class IniciarTransporteView(APIView):
    def post(self, request):
        motorista = request.user.motorista_perfil
        numero = request.data.get('numero_manifesto')

        # 1. Busca o log existente da busca prévia
        log = ManifestoBuscaLog.objects.filter(numero_manifesto=numero, motorista=motorista).first()
        
        if not log:
            return Response({'erro': 'Faça a busca do manifesto primeiro.'}, status=404)

        with transaction.atomic():
            # 2. Cria o registro oficial do manifesto
            manifesto = Manifesto.objects.create(
                numero_manifesto=numero,
                motorista=motorista,
                status='EM_TRANSPORTE'
            )
            
            # 3. Avisa o log que estamos processando
            log.status = 'AGUARDANDO'
            log.save()

            # 4. Chama a Task unificada passando os dois IDs
            buscar_manifesto_completo_task.delay(log.id, manifesto.id)

        return Response({'status': 'sucesso', 'manifesto_id': manifesto.id})