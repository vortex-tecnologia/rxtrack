from abc import ABC, abstractmethod


class BaseWhatsAppAdapter(ABC):
    """
    Contrato que todo provedor de WhatsApp deve seguir.
    Espelho do BaseTMSAdapter (integracoes/base.py) aplicado para mensageria.
    """

    def __init__(self, instancia):
        """
        Recebe a WhatsAppInstancia (que contém o provedor, nome da instância, etc.)
        """
        self.instancia = instancia
        self.provedor = instancia.provedor

    @abstractmethod
    def enviar_texto(self, numero: str, mensagem: str) -> dict:
        """
        Envia uma mensagem de texto simples para o número informado.
        Retorna o JSON de resposta da API do provedor.
        """
        pass

    @abstractmethod
    def verificar_conexao(self) -> bool:
        """
        Verifica se a instância está conectada e pronta para enviar mensagens.
        Retorna True se conectada, False caso contrário.
        """
        pass

    @abstractmethod
    def buscar_foto_perfil(self, numero: str) -> str:
        """
        Busca a URL da foto de perfil de um número de WhatsApp.
        Retorna a URL da imagem ou None se não encontrar.
        """
        pass
