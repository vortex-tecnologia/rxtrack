import os
import sys
import django
import requests
import json

# Setup Django Environment
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from configuracao.models import ConfiguracaoSistema
from manifesto.models import Frete, NotaFiscal
from django.db.models import Q

def run_test(target_seq_code):
    config = ConfiguracaoSistema.load()
    token = config.token_invoices
    domain = config.dominio_esl
    
    print(f"--- INICIANDO TESTE PARA O FRETE {target_seq_code} ---")
    print(f"Domínio ESL: {domain}")
    
    # 1. Busca o frete no banco local pelo ID Frete TMS (sequence_code)
    freight = Frete.objects.filter(freight_id_tms=target_seq_code).first()
    if not freight:
        print(f"Erro: Frete com sequence_code {target_seq_code} não foi encontrado no banco de dados local.")
        return
        
    print(f"Frete encontrado localmente!")
    print(f"  CT-e: {freight.numero_cte}")
    print(f"  ID Frete TMS (sequence_code): {freight.freight_id_tms}")
    
    # 2. Busca o ID interno da ESL nas notas vinculadas a este frete
    internal_id = None
    notes = freight.notas.all()
    print(f"  Notas vinculadas: {notes.count()}")
    for n in notes:
        print(f"    Nota: {n.numero_nota} | Chave: {n.chave_acesso} | ID Interno ESL (freight_id_tms): {n.freight_id_tms}")
        if n.freight_id_tms:
            internal_id = n.freight_id_tms
            
    if not internal_id:
        print("Erro: Não foi possível obter o ID interno do frete nas notas locais.")
        return
        
    print(f"ID Interno da ESL localizado: {internal_id}")
    
    # 3. Monta e envia a requisição de ocorrência 50 para a ESL
    url = f"https://{domain}/api/v1/freights/{internal_id}/invoice_occurrences"
    
    payload = {
        "invoice_occurrence": {
            "receiver": "Motorista Teste",
            "document_number": "",
            "comments": "Ocorrencia 50 enviada via script de teste no frete correto",
            "occurrence_at": "2026-07-22T21:55:00.000-03:00",
            "occurrence": {
                "code": 50
            }
        }
    }
    
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {token}'
    }
    
    print(f"\nPOST URL: {url}")
    print(f"Payload: {json.dumps(payload, indent=2)}")
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        print(f"\nStatus Code ESL: {response.status_code}")
        print(f"Resposta ESL: {response.text}")
    except Exception as e:
        print(f"Erro ao conectar na ESL: {e}")

if __name__ == '__main__':
    # O usuário informou sequence_code 429089
    target = '429089'
    if len(sys.argv) > 1:
        target = sys.argv[1]
    run_test(target)
