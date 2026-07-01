import requests
import logging

from whatsbot.base import BaseWhatsAppAdapter

logger = logging.getLogger(__name__)


class EvolutionAPIAdapter(BaseWhatsAppAdapter):
    """
    Implementação para Evolution API v2.x
    Documentação: https://doc.evolution-api.com/v2/
    """

    def _get_headers(self):
        # Se a instância tiver um token específico, usa ele. Senão, usa o global do provedor.
        token_instancia = self.instancia.api_token.strip() if self.instancia.api_token else ""
        token_global = self.provedor.api_key.strip() if self.provedor.api_key else ""
        
        token = token_instancia if token_instancia else token_global

        return {
            "apikey": token,
            "Authorization": f"Bearer {token}",  # Evolution v2 aceita ambos os formatos
            "Content-Type": "application/json"
        }

    def _get_base_url(self):
        """Retorna a URL base sem barra final."""
        return self.provedor.url_base.rstrip('/')

    def enviar_texto(self, numero, mensagem):
        """
        Envia mensagem de texto via Evolution API v2.
        POST {base_url}/message/sendText/{instanceName}
        """
        url = f"{self._get_base_url()}/message/sendText/{self.instancia.nome_instancia}"

        payload = {
            "number": numero,
            "textMessage": {
                "text": mensagem
            },
            "delay": 1200,  # 1.2s de atraso para parecer humano
            "linkPreview": True
        }

        try:
            response = requests.post(
                url,
                json=payload,
                headers=self._get_headers(),
                timeout=15
            )
            response.raise_for_status()
            resultado = response.json()
            logger.info(
                f"✅ WhatsApp enviado via Evolution API "
                f"({self.instancia.nome_instancia}) para {numero}"
            )
            return resultado

        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else 'N/A'
            detalhe = e.response.text if e.response is not None else str(e)
            logger.error(
                f"❌ Erro HTTP {status} ao enviar WhatsApp para {numero}: {detalhe}"
            )
            raise
        except requests.exceptions.RequestException as e:
            logger.error(
                f"❌ Erro de conexão ao enviar WhatsApp para {numero}: {e}"
            )
            raise

    def verificar_conexao(self):
        """
        Verifica se a instância da Evolution API está conectada.
        GET {base_url}/instance/connectionState/{instanceName}
        """
        url = f"{self._get_base_url()}/instance/connectionState/{self.instancia.nome_instancia}"

        try:
            response = requests.get(
                url,
                headers=self._get_headers(),
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            # Evolution API v2 retorna {"instance": {"state": "open"}} quando conectado
            state = data.get("instance", {}).get("state", "")
            return state == "open"
        except Exception as e:
            logger.error(
                f"❌ Erro ao verificar conexão da instância "
                f"{self.instancia.nome_instancia}: {e}"
            )
            return False
