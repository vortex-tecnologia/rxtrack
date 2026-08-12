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
            from django.db.models import Q
            manifesto = Manifesto.objects.filter(
                Q(numero_manifesto=str(numero_mft)) | Q(id=str(numero_mft))
            ).first()
            
            if not manifesto:
                return Response({"mensagem": "Manifesto não encontrado."}, status=404)

            # Se o manifesto já estava finalizado ou com status FINALIZADO, garante a consistência e libera o motorista
            if manifesto.finalizado or manifesto.status == 'FINALIZADO':
                manifesto.finalizado = True
                manifesto.status = "FINALIZADO"
                if not manifesto.data_finalizacao:
                    manifesto.data_finalizacao = timezone.now()
                if km_final and km_final != "0":
                    manifesto.km_final = km_final
                manifesto.save()

                try:
                    from manifesto.services import enviar_painel
                    enviar_painel(manifesto)
                except Exception:
                    pass

                return Response({"mensagem": "Manifesto finalizado com sucesso!", "sucesso": True}, status=200)

            # 1. Conferência de Notas Pendentes (Trava de segurança para não fechar se ainda houver notas pendentes de baixa)
            notas_pendentes = NotaFiscal.objects.filter(
                manifesto=manifesto, 
                status='PENDENTE'
            ).count()

            if notas_pendentes > 0:
                return Response({
                    "mensagem": f"Não é possível finalizar. Existem {notas_pendentes} nota(s) pendente(s) de baixa.",
                    "sucesso": False
                }, status=400)

            # 2. Conferência de Fotos em Análise pela IA
            from manifesto.models import BaixaNF
            from django.utils import timezone
            from datetime import timedelta

            # Auto-recuperação: Baixas com mais de 45s travadas em PENDENTE_ANALISE são liberadas
            limite_recente = timezone.now() - timedelta(seconds=45)
            BaixaNF.objects.filter(
                nota_fiscal__manifesto=manifesto,
                qualidade_canhoto='PENDENTE_ANALISE',
                data_baixa__lt=limite_recente
            ).update(qualidade_canhoto='APROVADO', solicitar_nova_foto=False)

            notas_em_analise = BaixaNF.objects.filter(
                nota_fiscal__manifesto=manifesto,
                qualidade_canhoto='PENDENTE_ANALISE',
                solicitar_nova_foto=False
            ).count()

            if notas_em_analise > 0:
                return Response({
                    "mensagem": f"Ainda não é possível finalizar o manifesto: existem {notas_em_analise} foto(s) de canhoto sendo analisadas pela IA. Aguarde alguns instantes.",
                    "sucesso": False
                }, status=400)

            # 3. Conferência de Canhotos Ilegíveis / Reprovados pela IA (Tentativa < 3 e sem aprovação manual)
            notas_foto_ruim = BaixaNF.objects.filter(
                nota_fiscal__manifesto=manifesto,
                solicitar_nova_foto=True
            ).count()

            if notas_foto_ruim > 0:
                return Response({
                    "mensagem": f"Não é possível finalizar o manifesto: existem {notas_foto_ruim} nota(s) com canhoto ilegível pendente(s) de nova foto (máximo 3 tentativas) ou liberação do SAC.",
                    "sucesso": False
                }, status=400)

            # --- SUCESSO LOCAL ---
            if km_final and km_final != "0":
                manifesto.km_final = km_final
            manifesto.finalizado = True
            manifesto.status = "FINALIZADO"
            manifesto.data_finalizacao = timezone.now()
            manifesto.save()

            # Notifica a Torre de Controle para remover/atualizar o card
            try:
                from manifesto.services import enviar_painel
                enviar_painel(manifesto)
            except Exception:
                pass

            # --- DISPARA INTEGRAÇÃO EM BACKGROUND ---
            finalizar_manifesto_tms_task.delay(manifesto.id)

            return Response({"mensagem": "Manifesto finalizado com sucesso!", "sucesso": True}, status=200)

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