import xml.etree.ElementTree as ET
import logging
from django.http import HttpResponse
from rest_framework.views import APIView
from django.db import transaction
from django.utils import timezone
from manifesto.models import WebhookEventoSOAP

logger = logging.getLogger(__name__)

class UploadRouteSoapView(APIView):
    # Desativa autenticação DRF padrão, pois o SOAP manda a credencial no XML
    authentication_classes = []
    permission_classes = []

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
        <mensagem>Manifesto processado com sucesso pelo Quicktrack</mensagem>
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
