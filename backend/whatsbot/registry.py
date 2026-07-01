import logging
from whatsbot.models import WhatsAppInstancia
from whatsbot.providers.evolution_api import EvolutionAPIAdapter

logger = logging.getLogger(__name__)

# Registro central de provedores WhatsApp disponíveis
# Mesma lógica do integracoes/registry.py
WHATSAPP_REGISTRY = {
    'evolution_api': EvolutionAPIAdapter,
    # 'z_api': ZAPIAdapter,          # Futuro
    # 'wppconnect': WPPConnectAdapter,  # Futuro
}


def get_whatsapp_adapter(filial):
    """
    Retorna o adapter WhatsApp correto para a filial.
    
    Lógica de seleção:
    1. Busca a instância ativa da filial
    2. Verifica se o provedor vinculado está ativo
    3. Retorna o adapter correspondente
    
    Se o provedor da instância estiver desativado, tenta encontrar
    outro provedor ativo (fallback por prioridade).
    
    Retorna None se não houver provedor disponível.
    """
    # Busca a instância da filial
    instancia = WhatsAppInstancia.objects.filter(
        filial=filial,
        ativo=True
    ).select_related('provedor').first()

    if not instancia:
        logger.warning(f"⚠️ Filial {filial.nome} não possui instância WhatsApp ativa.")
        return None

    # Se o provedor da instância está ativo, usa ele
    if instancia.provedor.ativo:
        adapter_class = WHATSAPP_REGISTRY.get(instancia.provedor.nome)
        if adapter_class:
            return adapter_class(instancia)
        logger.error(
            f"❌ Provedor '{instancia.provedor.nome}' não registrado no WHATSAPP_REGISTRY."
        )
        return None

    # Provedor da instância está desativado — tenta fallback
    logger.warning(
        f"⚠️ Provedor {instancia.provedor.get_nome_display()} está desativado. "
        f"Tentando fallback..."
    )

    # Procura outro provedor ativo por ordem de prioridade
    from whatsbot.models import WhatsAppProvedor
    provedor_fallback = WhatsAppProvedor.objects.filter(
        ativo=True
    ).order_by('prioridade').first()

    if not provedor_fallback:
        logger.error("❌ Nenhum provedor WhatsApp ativo encontrado para fallback.")
        return None

    adapter_class = WHATSAPP_REGISTRY.get(provedor_fallback.nome)
    if not adapter_class:
        logger.error(
            f"❌ Provedor fallback '{provedor_fallback.nome}' "
            f"não registrado no WHATSAPP_REGISTRY."
        )
        return None

    # Cria instância temporária com o provedor fallback
    # (usa os dados da instância original mas com o provedor ativo)
    instancia.provedor = provedor_fallback
    logger.info(
        f"🔄 Usando fallback: {provedor_fallback.get_nome_display()} "
        f"para filial {filial.nome}"
    )
    return adapter_class(instancia)
