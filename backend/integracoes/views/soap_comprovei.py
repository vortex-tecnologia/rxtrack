import xml.etree.ElementTree as ET
import logging
from django.http import HttpResponse
from rest_framework.views import APIView
from django.db import transaction
from django.utils import timezone
from manifesto.models import Manifesto, NotaFiscal, ManifestoBuscaLog
from usuarios.models import Motorista, Filial

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
                logger.error(f"Erro ao parsear XML SOAP Comprovei: {e}")
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

            # 3. Filial / Transportadora
            transportadora = find_tag(rota_element, 'Transportadora')
            filial_nome = "MATRIZ (COMPROVEI)"
            if transportadora is not None:
                razao = find_tag(transportadora, 'Razao')
                if razao is not None and razao.text:
                    filial_nome = str(razao.text).upper()[:100]

            filial_obj, _ = Filial.objects.get_or_create(nome=filial_nome)

            # 4. Motorista
            motorista_el = find_tag(rota_element, 'Motorista')
            if motorista_el is None:
                return self.soap_error("Tag <Motorista> nao encontrada")
            
            moto_cpf = find_tag(motorista_el, 'Usuario')
            moto_nome = find_tag(motorista_el, 'Nome')
            
            cpf = str(moto_cpf.text).strip() if moto_cpf is not None and moto_cpf.text else ""
            nome = str(moto_nome.text).upper().strip() if moto_nome is not None and moto_nome.text else "MOTORISTA COMPROVEI"

            if not cpf:
                return self.soap_error("CPF do motorista nao encontrado")

            motorista_obj, _ = Motorista.objects.get_or_create(
                cpf=cpf,
                defaults={'nome_completo': nome, 'filial': filial_obj}
            )

            # 5. Criar Manifesto
            with transaction.atomic():
                manifesto_obj = Manifesto.objects.filter(numero_manifesto=numero_rota).first()
                status_novo = 'AGUARDANDO'
                if manifesto_obj and manifesto_obj.status == 'EM_TRANSPORTE':
                    status_novo = 'EM_TRANSPORTE'

                manifesto_obj, _ = Manifesto.objects.update_or_create(
                    numero_manifesto=numero_rota,
                    defaults={
                        'motorista': motorista_obj,
                        'filial': filial_obj,
                        'status': status_novo,
                    }
                )

                # 6. Paradas (Notas Fiscais)
                paradas = find_tag(rota_element, 'Paradas')
                count_notas = 0
                ids_processadas = []

                if paradas is not None:
                    # Encontra todas as tags que terminam em 'Parada' e são filhas de 'Paradas'
                    for parada in paradas:
                        if not parada.tag.endswith('Parada'):
                            continue
                            
                        # 'E' = Entrega, 'C' = Coleta
                        tipo_parada = find_tag(parada, 'Tipo')
                        tipo_str = tipo_parada.text if tipo_parada is not None else 'E'
                        tipo_operacao = 'ENTREGA' if tipo_str == 'E' else 'COLETA'

                        doc = find_tag(parada, 'Documento')
                        cliente = find_tag(parada, 'Cliente')

                        if doc is not None:
                            numero_nota = find_tag(doc, 'Numero')
                            numero_nota = numero_nota.text if numero_nota is not None else ""
                            
                            chave_nota = find_tag(doc, 'ChaveNota')
                            chave_nota = chave_nota.text if chave_nota is not None else ""
                        else:
                            numero_nota = ""
                            chave_nota = ""

                        if cliente is not None:
                            razao_cli = find_tag(cliente, 'Razao')
                            destinatario = razao_cli.text.upper() if (razao_cli is not None and razao_cli.text) else "NÃO INFORMADO"
                            
                            end = find_tag(cliente, 'Endereco')
                            bairro = find_tag(cliente, 'Bairro')
                            cidade = find_tag(cliente, 'Cidade')
                            uf = find_tag(cliente, 'Estado')
                            
                            endereco_str = f"{end.text if end is not None and end.text else ''} - {bairro.text if bairro is not None and bairro.text else ''} ({cidade.text if cidade is not None and cidade.text else ''}/{uf.text if uf is not None and uf.text else ''})"
                            endereco_str = endereco_str.upper()
                        else:
                            destinatario = "NÃO INFORMADO"
                            endereco_str = "NÃO INFORMADO"

                        if numero_nota:
                            filtros_busca = {'manifesto': manifesto_obj}
                            if chave_nota:
                                filtros_busca['chave_acesso'] = chave_nota
                            else:
                                filtros_busca['numero_nota'] = numero_nota
                                filtros_busca['tipo_operacao'] = tipo_operacao

                            nota_obj, _ = NotaFiscal.objects.update_or_create(
                                **filtros_busca,
                                defaults={
                                    'destinatario': destinatario,
                                    'endereco_entrega': endereco_str,
                                    'tipo_operacao': tipo_operacao,
                                    'numero_nota': numero_nota,
                                    'chave_acesso': chave_nota if chave_nota else None,
                                }
                            )
                            ids_processadas.append(nota_obj.id)
                            count_notas += 1

                # 7. Remoção de Notas Órfãs (Se o TMS removeu alguma parada, nós deletamos)
                if ids_processadas:
                    notas_removidas = NotaFiscal.objects.filter(
                        manifesto=manifesto_obj,
                        status__in=['PENDENTE', 'AGUARDANDO']
                    ).exclude(id__in=ids_processadas)
                    
                    qtd_removidas = notas_removidas.count()
                    if qtd_removidas > 0:
                        logger.info(f"Removendo {qtd_removidas} notas orfas do manifesto SOAP {numero_rota}")
                        notas_removidas.delete()

                ManifestoBuscaLog.objects.update_or_create(
                    numero_manifesto=numero_rota,
                    motorista=motorista_obj,
                    defaults={
                        'status': 'PROCESSADO',
                        'mensagem_erro': None,
                        'quantidade_notas': count_notas
                    }
                )

            logger.info(f"Manifesto SOAP Comprovei {numero_rota} processado com {count_notas} notas.")
            return self.soap_success()

        except Exception as e:
            logger.error(f"Erro critico ao processar SOAP Comprovei: {e}", exc_info=True)
            return self.soap_error("Erro interno no servidor")

    def soap_success(self):
        """
        Retorna um envelope SOAP de sucesso genérico padrão da Comprovei.
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
