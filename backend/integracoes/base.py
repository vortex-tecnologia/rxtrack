from abc import ABC, abstractmethod

class BaseTMSAdapter(ABC):
    """Contrato que todo provedor TMS deve seguir."""
    
    def __init__(self, config):
        """Recebe o ConfiguracaoSistema do tenant."""
        self.config = config

    @abstractmethod
    def iniciar_transporte(self, numero_manifesto: str, task=None) -> dict:
        """Muda o status do manifesto para EM_TRANSPORTE no TMS."""
        pass

    @abstractmethod
    def buscar_manifesto_completo(self, log_id: int, task=None) -> str:
        """Busca o manifesto e suas notas e coletas de forma síncrona."""
        pass

    @abstractmethod
    def buscar_coletas_manifesto(self, manifesto_id: int, numero_visual: str, task=None) -> str:
        """Busca coletas vinculadas ao manifesto em background."""
        pass

    @abstractmethod
    def enviar_baixa(self, baixa_id: int, task=None) -> str:
        """Envia uma baixa de entrega/ocorrência para o TMS."""
        pass

    @abstractmethod
    def enviar_baixa_minuta(self, baixa_id: int, task=None) -> str:
        """Envia baixa de minuta (Freight ID) para o TMS."""
        pass

    @abstractmethod
    def enviar_coleta(self, baixa_id: int, task=None) -> str:
        """Envia um registro de coleta para o TMS."""
        pass

    @abstractmethod
    def finalizar_manifesto(self, manifesto_id: int, task=None) -> str:
        """Finaliza um manifesto no TMS."""
        pass
