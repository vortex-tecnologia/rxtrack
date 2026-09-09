# manifesto/rotas/init.py
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from manifesto.models import Manifesto


class AppInitView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        motorista = request.user.motorista_perfil

        # Manifesto ativo em transporte e NÃO finalizado
        manifesto = Manifesto.objects.filter(
            motorista=motorista,
            status='EM_TRANSPORTE',
            finalizado=False
        ).first()

        if not manifesto:
            # Auto-recuperação: se o manifesto estava finalizado há menos de 24h e recebeu novas notas pendentes
            from django.utils import timezone
            from datetime import timedelta
            from django.db.models import Q
            limite_24h = timezone.now() - timedelta(hours=24)

            manifesto_com_pendencia = Manifesto.objects.filter(
                motorista=motorista,
                notas_fiscais__status='PENDENTE',
                notas_fiscais__baixa_info__isnull=True
            ).filter(
                Q(data_finalizacao__gte=limite_24h) | (Q(data_finalizacao__isnull=True) & Q(data_criacao__gte=limite_24h))
            ).distinct().order_by('-data_criacao', '-id').first()

            if manifesto_com_pendencia and (manifesto_com_pendencia.finalizado or manifesto_com_pendencia.status == 'FINALIZADO'):
                manifesto_com_pendencia.status = 'EM_TRANSPORTE'
                manifesto_com_pendencia.finalizado = False
                manifesto_com_pendencia.data_finalizacao = None
                manifesto_com_pendencia.save(update_fields=['status', 'finalizado', 'data_finalizacao'])
                manifesto = manifesto_com_pendencia

        if manifesto:
            return Response({
                'tela': 'NOTAS',
                'manifesto_id': manifesto.numero_manifesto or manifesto.id
            })

        return Response({'tela': 'BUSCA'})
