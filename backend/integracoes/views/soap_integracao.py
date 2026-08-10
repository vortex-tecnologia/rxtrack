import xml.etree.ElementTree as ET
import logging
from django.http import HttpResponse
from rest_framework.views import APIView
from django.db import transaction
from django.utils import timezone
from manifesto.models import WebhookEventoSOAP
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiExample, OpenApiTypes

logger = logging.getLogger(__name__)

class UploadRouteSoapView(APIView):
    # Desativa autenticação DRF padrão, pois o SOAP manda a credencial no XML
    authentication_classes = []
    permission_classes = []

    @extend_schema(
        tags=['Integração TMS'],
        summary="Receber Manifesto via SOAP",
        description=(
            "Recebe um manifesto contendo motorista, veículo e notas fiscais em formato XML SOAP. "
            "O processamento das notas será executado em background (assíncrono). "
            "Para autenticação, o TMS envia a credencial diretamente no nó `<Credenciais>`. "
            "Caso alguma nota seja omitida no XML, o sistema entenderá que ela foi removida e a deletará do banco se o status for pendente."
        ),
        request=OpenApiTypes.STR,
        examples=[
            OpenApiExample(
                name="Exemplo SOAP UploadRoute",
                description="XML de exemplo de envio de manifesto",
                value='''<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <uploadRoute>
      <Rota numero="999999">
        <Data>20260707</Data>
        <Transportadora>
          <Razao>TRANSPORTADORA EXEMPLO LTDA</Razao>
        </Transportadora>
        <Motorista>
          <Usuario>11122233344</Usuario>
          <Nome>MOTORISTA TESTE</Nome>
        </Motorista>
        <Paradas>
          <Parada numero="1">
            <Tipo>E</Tipo>
            <Documento>
              <Numero>12345</Numero>
              <ChaveNota>35230111111111111111550010000123451000123456</ChaveNota>
            </Documento>
            <Cliente>
              <Razao>CLIENTE DESTINO</Razao>
              <Endereco>RUA DAS FLORES 123</Endereco>
              <Bairro>CENTRO</Bairro>
              <Cidade>SAO PAULO</Cidade>
              <Estado>SP</Estado>
            </Cliente>
          </Parada>
        </Paradas>
      </Rota>
    </uploadRoute>
  </soap:Body>
</soap:Envelope>''',
                request_only=True
            )
        ],
        responses={
            200: OpenApiResponse(
                description="Sucesso. Retorna um envelope SOAP com status OK.",
                response=OpenApiTypes.STR,
                examples=[OpenApiExample("Sucesso", value="<status>OK</status>")]
            ),
            400: OpenApiResponse(
                description="Erro. Retorna um envelope SOAP com status ERRO.",
                response=OpenApiTypes.STR,
                examples=[OpenApiExample("Erro", value="<status>ERRO</status>")]
            )
        }
    )
    def post(self, request, *args, **kwargs):
        try:
            xml_data = request.body
            if not xml_data:
                return self.soap_error("Corpo da requisição vazio")

            # Remove namespaces para facilitar o parsing manual (uma vez que os namespaces podem variar)
            xml_str = xml_data.decode('utf-8')
            xml_str = xml_str.replace('xmlns="WebServiceComprovei"', '')
            xml_str = xml_str.replace('xmlns="WebServiceComprovei:uploadRoute"', '')
            # Regex básico para remover ns prefixes se houver
            import re
            xml_str = re.sub(r' xmlns(:[a-zA-Z0-9]+)?="[^"]+"', '', xml_str)

            try:
                root = ET.fromstring(xml_str)
            except ET.ParseError as e:
                logger.error(f"Erro ao parsear XML SOAP Integracao: {e}")
                return self.soap_error("XML malformado")

            # Função auxiliar para buscar tags ignorando prefixos de namespace
            def find_tag(element, tag_name):
                # Busca iterativa para encontrar a tag ignorando namespaces
                for child in element.iter():
                    if child.tag.endswith(tag_name):
                        return child
                return None

            # 1. Credenciais (opcional, por enquanto aceitamos qualquer um, mas logamos)
            credenciais = find_tag(root, 'Credenciais')
            if credenciais is not None:
                user = find_tag(credenciais, 'Usuario')
                user = user.text if user is not None else ''
                logger.info(f"Recebendo SOAP UploadRoute (Usuario: {user})")

            # 2. Manifesto (Rota)
            rota_element = find_tag(root, 'Rota')
            if rota_element is None:
                return self.soap_error("Tag <Rota> nao encontrada no XML")
            
            numero_rota = rota_element.get('numero')
            if not numero_rota:
                return self.soap_error("Atributo 'numero' nao encontrado na tag <Rota>")

            # 3. Salva o XML no banco usando update_or_create para atualizar caso re-enviem a mesma rota
            evento, _ = WebhookEventoSOAP.objects.update_or_create(
                numero_manifesto=numero_rota,
                defaults={
                    'payload_xml': xml_str,
                    'status': 'PENDENTE',
                    'erro': None
                }
            )

            # 4. Dispara a task do Celery para processamento em background
            from manifesto.tasks import processar_soap_task
            processar_soap_task.delay(evento.id)

            logger.info(f"Manifesto SOAP Integracao {numero_rota} enfileirado para processamento.")
            return self.soap_success()

        except Exception as e:
            logger.error(f"Erro critico ao processar SOAP Integracao: {e}", exc_info=True)
            return self.soap_error("Erro interno no servidor")

    def soap_success(self):
        """
        Retorna um envelope SOAP de sucesso genérico padrão da integracao anterior.
        Muitos TMS avaliam apenas o HTTP 200 e alguma tag indicando sucesso.
        """
        xml_response = """<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <uploadRouteResponse xmlns="WebServiceComprovei:uploadRoute">
      <uploadRouteResult>
        <status>OK</status>
        <mensagem>Manifesto processado com sucesso pelo RXTrack</mensagem>
      </uploadRouteResult>
    </uploadRouteResponse>
  </soap:Body>
</soap:Envelope>"""
        return HttpResponse(xml_response, content_type="text/xml; charset=utf-8")

    def soap_error(self, message):
        """
        Retorna um envelope SOAP de erro.
        """
        xml_response = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <uploadRouteResponse xmlns="WebServiceComprovei:uploadRoute">
      <uploadRouteResult>
        <status>ERRO</status>
        <mensagem>{message}</mensagem>
      </uploadRouteResult>
    </uploadRouteResponse>
  </soap:Body>
</soap:Envelope>"""
        return HttpResponse(xml_response, content_type="text/xml; charset=utf-8", status=400)
