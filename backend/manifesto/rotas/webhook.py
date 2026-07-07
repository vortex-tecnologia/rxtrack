from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
from rest_framework.authtoken.models import Token

from manifesto.models import WebhookEventoManifestoESL


from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes, OpenApiExample, OpenApiResponse

@extend_schema(
    methods=['GET'],
    exclude=True
)
@extend_schema(
    methods=['POST'],
    tags=['Integração TMS'],
    summary="Receber Manifesto via Webhook (JSON)",
    description=(
        "Recebe dados de manifesto e notas fiscais em formato JSON. "
        "Requer autenticação via Header `Authorization: Token SEU_TOKEN`."
    ),
    request=OpenApiTypes.OBJECT,
    examples=[
        OpenApiExample(
            "Exemplo Payload Webhook JSON",
            value={
                "filial": {
                    "id_tms": "ID_FILIAL_TMS",
                    "nome": "NOME DA FILIAL"
                },
                "motorista": {
                    "cpf": "12345678901",
                    "nome": "NOME DO MOTORISTA"
                },
                "manifesto": {
                    "numero": "58134",
                    "id_tms": "ID_INTERNA_TMS",
                    "data_emissao": "2025-03-24T10:00:00Z",
                    "observacoes": "Entrega prioritária"
                },
                "itens": [
                    {
                        "tipo": "ENTREGA",
                        "id_tms": "ID_ITEM_TMS",
                        "numero_item": "123456",
                        "chave_item": "44_DIGITOS_NFE",
                        "numero_cte": "999888",
                        "chave_cte": "44_DIGITOS_CTE",
                        "numero_coleta": "",
                        "data_emissao": "2025-03-22",
                        "sla": "2025-03-25",
                        "destinatario": {
                            "nome": "NOME DA EMPRESA",
                            "documento": "11122233344",
                            "logradouro": "RUA EXEMPLO",
                            "numero": "100",
                            "bairro": "CENTRO",
                            "cidade": "RIO DE JANEIRO",
                            "uf": "RJ",
                            "cep": "00000-000",
                            "telefone": "21999999999"
                        }
                    }
                ]
            },
            request_only=True
        )
    ],
    responses={
        201: OpenApiResponse(description="Recebido e enfileirado para processamento"),
        401: OpenApiResponse(description="Token inválido ou não informado"),
        403: OpenApiResponse(description="Token bloqueado")
    }
)
@api_view(['GET', 'POST'])
@authentication_classes([])            # 👈 REMOVE auth padrão
@permission_classes([AllowAny])        # 👈 PERMITE GET público
def webhook_tms(request):

    # 📘 DOCUMENTAÇÃO (GET SEM TOKEN)
    if request.method == "GET":
        return Response({
            "descricao": "Webhook TMS - Manifesto (Comercial)",
            "endpoint": "/api/webhook/tms/",
            "metodo": "POST",
            "headers_obrigatorios": {
                "Authorization": "Token SEU_TOKEN_AQUI",
                "Content-Type": "application/json"
            },
            "exemplo_payload_padrao": {
                "filial": {
                    "id_tms": "ID_FILIAL_TMS",
                    "nome": "NOME DA FILIAL"
                },
                "motorista": {
                    "cpf": "12345678901",
                    "nome": "NOME DO MOTORISTA"
                },
                "manifesto": {
                    "numero": "58134",
                    "id_tms": "ID_INTERNA_TMS",
                    "data_emissao": "2025-03-24T10:00:00Z",
                    "observacoes": "Entrega prioritária"
                },
                "itens": [
                    {
                        "tipo": "ENTREGA | COLETA | TRANSFERENCIA | DESPACHO | RETIRADA",
                        "id_tms": "ID_ITEM_TMS",
                        "numero_item": "123456 (NF, Coleta ou Minuta)",
                        "chave_item": "44_DIGITOS_NFE (Opcional se CT-e)",
                        "numero_cte": "999888",
                        "chave_cte": "44_DIGITOS_CTE",
                        "numero_coleta": "777666 (Obrigatório se tipo=COLETA)",
                        "data_emissao": "2025-03-22",
                        "sla": "2025-03-25",
                        "destinatario": {
                            "nome": "NOME DA EMPRESA",
                            "documento": "CNPJ_OU_CPF",
                            "logradouro": "RUA EXEMPLO",
                            "numero": "100",
                            "bairro": "CENTRO",
                            "cidade": "RIO DE JANEIRO",
                            "uf": "RJ",
                            "cep": "00000-000",
                            "telefone": "21999999999"
                        }
                    }
                ]
            }
        })

    # 🔐 VALIDA TOKEN E CONTROLE DE USO
    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Token "):
        return Response({"detail": "Token não informado"}, status=status.HTTP_401_UNAUTHORIZED)

    token_key = auth.replace("Token ", "")
    try:
        token_obj = Token.objects.select_related('user').get(key=token_key)
        user = token_obj.user
    except Token.DoesNotExist:
        return Response({"detail": "Token inválido"}, status=status.HTTP_401_UNAUTHORIZED)

    # Verifica se existe controle de token para este usuário
    from manifesto.models import WebhookTokenControl
    control, created = WebhookTokenControl.objects.get_or_create(
        user=user,
        defaults={'mes_referencia': timezone.now().date().replace(day=1)}
    )

    # Verifica se o token foi bloqueado manualmente
    if not control.ativo:
        return Response(
            {"detail": "Seu token de acesso foi desativado. Entre em contato com o suporte."},
            status=status.HTTP_403_FORBIDDEN
        )

    # Lógica de reset mensal e incremento
    control.reset_if_new_month()
    control.total_mes_atual += 1
    control.save()

    # Define flags de faturamento
    limite_excedido = control.total_mes_atual > control.limite_mensal

    # 📩 RECEBE WEBHOOK
    payload = request.data
    numero_manifesto = payload.get("manifesto", {}).get("numero")

    event = WebhookEventoManifestoESL.objects.create(
        tipo=payload.get("tipo", "comercial_standard"),
        numero_manifesto=numero_manifesto,
        payload=payload
    )

    # 🔥 Dispara a leitura asíncrona no Celery
    from manifesto.tasks import processar_webhook_manifesto_task
    processar_webhook_manifesto_task.delay(event.id)

    return Response({
        "ok": True, 
        "mensagem": "Recebido e enfileirado para processamento",
        "monitoramento": {
            "consumo_mes": control.total_mes_atual,
            "limite_plano": control.limite_mensal,
            "aviso_limite_excedido": limite_excedido,
            "valor_adicional": limite_excedido
        },
        "event_id": event.id
    }, status=201)
