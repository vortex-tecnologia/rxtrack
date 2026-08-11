from configuracao.utils import get_config
from integracoes.providers.esl_cloud import ESLCloudAdapter

# Registro central de provedores TMS disponíveis
TMS_REGISTRY = {
    'esl_cloud': ESLCloudAdapter,
    # 'totvs': TOTVSAdapter,      # futuro
    # 'sap_tm': SAPTMAdapter,     # futuro
}

def get_tms_adapter(config=None):
    """
    Retorna a instância do adapter TMS correto para o tenant.
    Se config não for passado, busca a configuração atual via get_config().
    """
    if config is None:
        config = get_config()
    
    provider_key = getattr(config, 'tms_provider', 'esl_cloud')
    
    # Se o cliente escolher "Sem integração TMS", retornamos None
    if provider_key == 'nenhum':
        return None
        
    adapter_class = TMS_REGISTRY.get(provider_key)
    
    if not adapter_class:
        # Se for inválido ou não registrado, faz fallback seguro para esl_cloud
        # para garantir funcionamento ininterrupto do legado
        adapter_class = ESLCloudAdapter
        
    return adapter_class(config)
