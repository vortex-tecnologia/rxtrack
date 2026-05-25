from rest_framework import views
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from django.utils import timezone
from django.utils.timezone import localtime

from manifesto.models import Manifesto


class HistoricoManifestosView(views.APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            # Buscamos manifestos finalizados com prefetch profundo para evitar TIMEOUT
            manifestos = (
                Manifesto.objects
                .filter(motorista__user=request.user, finalizado=True)
                .order_by('-data_finalizacao')
                .prefetch_related(
                    'notas_fiscais',
                    'notas_fiscais__historico',
                    'notas_fiscais__baixa_info__ocorrencia' # ForeignKey agora
                )
            )

            dados = []
            for manifesto in manifestos:
                dados_notas = []
                
                for nota in manifesto.notas_fiscais.all():
                    # ✅ ACESSO SEGURO AO CACHE (ForeignKey)
                    # Transformamos em lista para pegar o último registro sem nova consulta SQL
                    baixas_list = list(nota.baixa_info.all())
                    baixa = baixas_list[-1] if baixas_list else None

                    # ✅ ACESSO SEGURO AO HISTÓRICO (TMS)
                    historicos = list(nota.historico.all())
                    # Ordenamos em memória para garantir a data mais recente
                    historicos.sort(key=lambda x: x.data_ocorrencia if x.data_ocorrencia else timezone.now(), reverse=True)
                    ultima_ocorrencia = historicos[0] if historicos else None

                    # Lógica de prioridade de Status
                    if baixa and baixa.ocorrencia:
                        tipo_ocorrencia = baixa.ocorrencia.descricao
                    elif ultima_ocorrencia:
                        tipo_ocorrencia = f"TMS: {ultima_ocorrencia.codigo_tms}"
                    else:
                        tipo_ocorrencia = "Entregue"

                    dados_notas.append({
                        "numero_nf": nota.numero_nota,
                        "status_nf": nota.status,
                        "tipo_ocorrencia": tipo_ocorrencia,
                        "descricao_detalhada": (
                            baixa.observacao if baixa and baixa.observacao 
                            else (ultima_ocorrencia.comentarios if ultima_ocorrencia else "Sem observações.")
                        ),
                        "foto_comprovante": baixa.comprovante_foto_url if baixa else None,
                        "recebedor": baixa.recebedor if baixa and baixa.recebedor else "Não informado",
                        "data_baixa": (
                            localtime(baixa.data_baixa).strftime('%d/%m/%Y %H:%M') if baixa 
                            else (localtime(ultima_ocorrencia.data_ocorrencia).strftime('%d/%m/%Y %H:%M') if ultima_ocorrencia else None)
                        )
                    })

                dados.append({
                    "numero": manifesto.numero_manifesto,
                    "qtd_nfe": len(dados_notas),
                    "data": (localtime(manifesto.data_finalizacao or manifesto.data_criacao)).strftime('%d/%m/%Y'),
                    "km_final": str(manifesto.km_final) if manifesto.km_final else "N/A",
                    "notas": dados_notas
                })

            return Response(dados)

        except Exception as e:
            # Log de erro detalhado para você ver no 'docker logs' da VPS
            print(f"ERRO CRÍTICO NO HISTÓRICO: {str(e)}")
            return Response({"erro": "Erro interno ao carregar histórico."}, status=500)