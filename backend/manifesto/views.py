# manifestos/views.py
from rest_framework.views import APIView
from rest_framework import views, status, generics
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django.shortcuts import get_object_or_404
from .models import Manifesto, NotaFiscal, Ocorrencia, BaixaNF, ManifestoBuscaLog
from django.db import transaction
from usuarios.models import Motorista
from .serializers import (
    ManifestoBuscaSerializer, ManifestoSerializer, 
    BaixaNFCreateSerializer, OcorrenciaSerializer
)
from .tasks import buscar_manifesto_completo_task , finalizar_manifesto_tms_task

class ManifestoFinalizacaoView(APIView):
    def post(self, request):
        km_final = request.data.get('km_final')
        numero_mft = request.data.get('manifesto_id') 

        if not numero_mft:
            return Response({"mensagem": "Número do manifesto não fornecido."}, status=400)

        try:
            from manifesto.services import tentar_autofinalizar_manifesto
            sucesso, msg = tentar_autofinalizar_manifesto(numero_mft, km_final=km_final)
            if sucesso:
                return Response({"mensagem": msg, "sucesso": True}, status=200)
            else:
                return Response({"mensagem": msg, "sucesso": False}, status=400)
        except Exception as e:
            return Response({"mensagem": f"Erro interno: {str(e)}"}, status=500)

class AtualizarManifestoView(views.APIView):
    # Reutiliza sua autenticação JWT
    
    def post(self, request):
        numero_manifesto = request.data.get('numero_manifesto')
        motorista = request.user.motorista_profile # Ajuste conforme seu modelo

        if not numero_manifesto:
            return Response({"erro": "Número do manifesto é obrigatório"}, status=status.HTTP_400_BAD_REQUEST)

        # 1. Criamos um log de busca marcado como 'ATUALIZACAO'
        log = ManifestoBuscaLog.objects.create(
            motorista=motorista,
            numero_manifesto=numero_manifesto,
            status='PENDENTE'
        )

        # 2. Chamamos a mesma Task que você já tem
        # Ela vai percorrer a API da ESL e adicionar o que estiver faltando
        buscar_manifesto_completo_task.delay(log.id)

        return Response({
            "mensagem": "Sincronização iniciada. As novas notas aparecerão em instantes.",
            "log_id": log.id
        }, status=status.HTTP_202_ACCEPTED)

class OcorrenciaListView(generics.ListAPIView):
    """
    GET: Lista de todos os códigos de ocorrência (Entrega/Problema) do TMS.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = OcorrenciaSerializer
    queryset = Ocorrencia.objects.all()