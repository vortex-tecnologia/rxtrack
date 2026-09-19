from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
from rest_framework.authtoken.models import Token
from django.conf import settings

from manifesto.models import WebhookEventoManifestoESL

import logging
logger = logging.getLogger(__name__)

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
        "Aceita **dois formatos**:\n\n"
        "1. **Formato TMS (Comprovei/SSW)**: Envelope SOAP convertido em JSON com credencial dentro do body (`Envelope.Header.Credenciais.Senha`)\n"
        "2. **Formato Padrão RXTrack**: JSON simples com Header `Authorization: Token SEU_TOKEN`\n\n"
        "O endpoint detecta automaticamente qual formato foi enviado."
    ),
    request=OpenApiTypes.OBJECT,
    examples=[
        OpenApiExample(
            "Exemplo Payload Webhook JSON (Formato Padrão)",
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
            "descricao": "Webhook TMS - Manifesto (Comercial + TMS Direto)",
            "endpoint": "/api/webhook/tms/",
            "metodo": "POST",
            "formatos_aceitos": {
                "formato_tms": {
                    "descricao": "JSON Envelope (Comprovei/SSW) — credencial dentro do body",
                    "autenticacao": "Envelope.Header.Credenciais.Senha",
                    "estrutura": "Envelope.Body.uploadRoute.Rotas.Rota { Motorista, Paradas, Transportadora }"
                },
                "formato_padrao": {
                    "descricao": "JSON simples RXTrack — credencial via HTTP Header",
                    "autenticacao": "Header Authorization: Token SEU_TOKEN",
                    "estrutura": "{ filial, motorista, manifesto, itens[] }"
                }
            },
            "headers_obrigatorios_formato_padrao": {
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

    # ───────────────────────────────────────────────────
    # 🔐 1. AUTENTICAÇÃO
    # ───────────────────────────────────────────────────
    payload = request.data
    from integracoes.normalizers import is_formato_tms_envelope, extrair_credencial_tms, normalizar_json_tms

    auth = request.headers.get("Authorization")
    control = None
    limite_excedido = False

    # Opção A: Autenticação via Header Authorization (padrão DRF configurado no Webservice)
    if auth and auth.startswith("Token "):
        token_key = auth.replace("Token ", "").strip()
        try:
            token_obj = Token.objects.select_related('user').get(key=token_key)
            user = token_obj.user
        except Token.DoesNotExist:
            return Response({"detail": "Token de autorização inválido"}, status=status.HTTP_401_UNAUTHORIZED)

        # Controle de consumo mensal
        from manifesto.models import WebhookTokenControl
        control, _ = WebhookTokenControl.objects.get_or_create(
            user=user,
            defaults={'mes_referencia': timezone.now().date().replace(day=1)}
        )

        if not control.ativo:
            return Response(
                {"detail": "Seu token de acesso foi desativado. Entre em contato com o suporte."},
                status=status.HTTP_403_FORBIDDEN
            )

        control.reset_if_new_month()
        control.total_mes_atual += 1
        control.save()
        limite_excedido = control.total_mes_atual > control.limite_mensal

    # Opção B: Fallback via Senha no Payload (se não enviou header)
    elif is_formato_tms_envelope(payload):
        senha_recebida = extrair_credencial_tms(payload)
        senha_esperada = getattr(settings, 'TMS_WEBHOOK_SECRET', '')
        if not senha_esperada or senha_recebida != senha_esperada:
            return Response({"detail": "Token não informado no Header e credencial no payload inválida."}, status=status.HTTP_401_UNAUTHORIZED)

    else:
        return Response({"detail": "Token de autenticação não informado. Envie o header 'Authorization: Token SEU_TOKEN'."}, status=status.HTTP_401_UNAUTHORIZED)

    # ───────────────────────────────────────────────────
    # 🔄 2. NORMALIZAÇÃO AUTOMÁTICA DO PAYLOAD
    # ───────────────────────────────────────────────────
    origem_evento = 'ESL'
    tipo_evento = payload.get("tipo", "comercial_standard")

    if is_formato_tms_envelope(payload):
        logger.info("📦 Webhook recebido no formato TMS Envelope — normalizando automaticamente")
        try:
            payload_processar = normalizar_json_tms(payload)
            origem_evento = 'TMS_JSON'
            tipo_evento = 'tms_uploadroute'
        except (ValueError, KeyError) as e:
            logger.error(f"❌ Erro ao normalizar JSON TMS: {e}")
            return Response({"detail": f"Erro na estrutura do JSON: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)
    else:
        payload_processar = payload

    # ───────────────────────────────────────────────────
    # 📩 3. CRIAÇÃO DO EVENTO E DISPARO CELERY
    # ───────────────────────────────────────────────────
    numero_manifesto = payload_processar.get("manifesto", {}).get("numero")

    event = WebhookEventoManifestoESL.objects.create(
        origem=origem_evento,
        tipo=tipo_evento,
        numero_manifesto=numero_manifesto,
        payload=payload_processar
    )

    from manifesto.tasks import processar_webhook_manifesto_task
    processar_webhook_manifesto_task.delay(event.id)

    response_data = {
        "ok": True,
        "mensagem": "Manifesto recebido e enfileirado para processamento com sucesso.",
        "manifesto": numero_manifesto,
        "event_id": event.id
    }

    if control:
        response_data["monitoramento"] = {
            "consumo_mes": control.total_mes_atual,
            "limite_plano": control.limite_mensal,
            "aviso_limite_excedido": limite_excedido
        }

    return Response(response_data, status=status.HTTP_201_CREATED)
