from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from manifesto.models import Manifesto
from django.db import transaction

class VerificarManifestoAtivoView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        motorista = getattr(request.user, 'motorista_perfil', None)
        if not motorista:
            return Response({'tem_manifesto': False})

        with transaction.atomic():
            # Busca se existe algum manifesto com status 'EM_TRANSPORTE' e NÃO finalizado
            manifesto_ativo = Manifesto.objects.filter(
                motorista=motorista, 
                status='EM_TRANSPORTE',
                finalizado=False
            ).first()

            if not manifesto_ativo:
                # Se não há manifesto ativo, busca o mais antigo com status 'AGUARDANDO' para o motorista
                manifesto_pendente = Manifesto.objects.filter(
                    motorista=motorista,
                    status='AGUARDANDO'
                ).order_by('data_criacao').first()

                if manifesto_pendente:
                    manifesto_pendente.status = 'EM_TRANSPORTE'
                    manifesto_pendente.save()
                    manifesto_ativo = manifesto_pendente

            if manifesto_ativo:
                return Response({
                    'tem_manifesto': True,
                    'numero_manifesto': manifesto_ativo.numero_manifesto
                })

        return Response({'tem_manifesto': False})