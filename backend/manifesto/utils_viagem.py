import re

UFS_BRASIL = {
    'AC', 'AL', 'AP', 'AM', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA',
    'MT', 'MS', 'MG', 'PA', 'PB', 'PR', 'PE', 'PI', 'RJ', 'RN',
    'RS', 'RO', 'RR', 'SC', 'SP', 'SE', 'TO'
}


def obter_uf_por_cep(cep_str):
    """
    Identifica o estado (UF) do Brasil com base na faixa oficial do CEP.
    """
    if not cep_str:
        return None
    numeros = ''.join(filter(str.isdigit, str(cep_str)))
    if len(numeros) >= 5:
        try:
            prefixo = int(numeros[:5])
            if 1000 <= prefixo <= 19999:
                return 'SP'
            elif 20000 <= prefixo <= 28999:
                return 'RJ'
            elif 29000 <= prefixo <= 29999:
                return 'ES'
            elif 30000 <= prefixo <= 39999:
                return 'MG'
            elif 40000 <= prefixo <= 48999:
                return 'BA'
            elif 49000 <= prefixo <= 49999:
                return 'SE'
            elif 50000 <= prefixo <= 56999:
                return 'PE'
            elif 57000 <= prefixo <= 57999:
                return 'AL'
            elif 58000 <= prefixo <= 58999:
                return 'PB'
            elif 59000 <= prefixo <= 59999:
                return 'RN'
            elif 60000 <= prefixo <= 63999:
                return 'CE'
            elif 64000 <= prefixo <= 64999:
                return 'PI'
            elif 65000 <= prefixo <= 65999:
                return 'MA'
            elif 66000 <= prefixo <= 68899:
                return 'PA'
            elif 68900 <= prefixo <= 68999:
                return 'AP'
            elif (69000 <= prefixo <= 69299) or (69400 <= prefixo <= 69899):
                return 'AM'
            elif 69300 <= prefixo <= 69399:
                return 'RR'
            elif 69900 <= prefixo <= 69999:
                return 'AC'
            elif (70000 <= prefixo <= 72799) or (73000 <= prefixo <= 73699):
                return 'DF'
            elif (72800 <= prefixo <= 72999) or (73700 <= prefixo <= 76799):
                return 'GO'
            elif 76800 <= prefixo <= 76999:
                return 'RO'
            elif 77000 <= prefixo <= 77999:
                return 'TO'
            elif 78000 <= prefixo <= 78899:
                return 'MT'
            elif 79000 <= prefixo <= 79999:
                return 'MS'
            elif 80000 <= prefixo <= 87999:
                return 'PR'
            elif 88000 <= prefixo <= 89999:
                return 'SC'
            elif 90000 <= prefixo <= 99999:
                return 'RS'
        except ValueError:
            return None
    return None


def obter_uf_por_endereco(endereco_str):
    """
    Extrai a UF a partir da string de endereço (ex: '(GUARULHOS/SP)', '- SP', '/RJ').
    """
    if not endereco_str:
        return None
    endereco_upper = str(endereco_str).upper()

    # 1. Padrão /SP ou / SP ou (CIDADE/SP)
    match = re.search(r'[/,\-]\s*([A-Z]{2})\b', endereco_upper)
    if match and match.group(1) in UFS_BRASIL:
        return match.group(1)

    # 2. Padrão entre parênteses: (SP) ou ao final do texto
    tokens = re.findall(r'\b([A-Z]{2})\b', endereco_upper)
    for t in reversed(tokens):
        if t in UFS_BRASIL:
            return t
    return None


def obter_uf_filial(filial):
    """
    Identifica a UF de uma filial (campo .uf ou inferência pelo nome).
    """
    if not filial:
        return None
    if getattr(filial, 'uf', None):
        uf_val = str(filial.uf).strip().upper()
        if uf_val in UFS_BRASIL:
            return uf_val

    nome = (getattr(filial, 'nome', '') or '').upper()
    for uf in UFS_BRASIL:
        if f"/{uf}" in nome or f"-{uf}" in nome or f" {uf}" in nome or f"({uf})" in nome:
            return uf

    if "RIO" in nome or "FLUMINENSE" in nome or "GALEÃO" in nome or "GALEAO" in nome:
        return "RJ"
    if "SÃO PAULO" in nome or "SAO PAULO" in nome or "PAULISTA" in nome or "GUARULHOS" in nome or "CAMPINAS" in nome:
        return "SP"
    if "BRASILIA" in nome or "BRASÍLIA" in nome or "FEDERAL" in nome:
        return "DF"
    if "MINAS" in nome or "BELO HORIZONTE" in nome or "CONFINS" in nome:
        return "MG"
    if "CURITIBA" in nome or "PARANA" in nome or "PARANÁ" in nome:
        return "PR"

    return None


def verificar_manifesto_viagem(manifesto):
    """
    Verifica se um manifesto é uma viagem interestadual (origem != destino).
    Retorna (is_viagem: bool, uf_destino: str or None).
    """
    filial_origem = getattr(manifesto, 'filial_operacao', None) or getattr(manifesto, 'filial', None)
    uf_origem = obter_uf_filial(filial_origem)
    if not uf_origem:
        return False, None

    # Verifica as notas fiscais do manifesto
    # Usa cache/prefetched se disponível para máxima performance
    notas = manifesto.notas_fiscais.all()
    for nf in notas:
        uf_dest = obter_uf_por_cep(getattr(nf, 'cep', None)) or obter_uf_por_endereco(getattr(nf, 'endereco_entrega', None))
        if uf_dest and uf_dest != uf_origem:
            return True, uf_dest

    return False, uf_origem
