#!/usr/bin/env python
"""
==========================================================================
 DIAGNÓSTICO DE MANIFESTOS TRAVADOS NA VERIFICAÇÃO DE IA
==========================================================================
 Rode este script DENTRO DO CONTAINER para investigar manifestos que 
 ficam travados no "VERIFICANDO COMPROVANTES..." infinitamente.

 USO NA VPS:
   docker exec -it rxtrack_homolog_backend python diagnostico_ia.py
   
   # Para verificar um manifesto específico:
   docker exec -it rxtrack_homolog_backend python diagnostico_ia.py 67087
   
   # Para forçar a liberação de um manifesto travado:
   docker exec -it rxtrack_homolog_backend python diagnostico_ia.py 67087 --liberar
   
   # Para verificar o estado do Celery/IA:
   docker exec -it rxtrack_homolog_backend python diagnostico_ia.py --celery
==========================================================================
"""

import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from django.utils import timezone
from datetime import timedelta
from manifesto.models import Manifesto, NotaFiscal, BaixaNF


# =================== CORES PARA TERMINAL ===================
class C:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    END = '\033[0m'


def banner():
    print(f"""{C.CYAN}{C.BOLD}
╔═══════════════════════════════════════════════════════════╗
║         🔍 DIAGNÓSTICO DE MANIFESTOS TRAVADOS IA         ║
║              RXTrack - Agente IA / Celery                ║
╚═══════════════════════════════════════════════════════════╝{C.END}
""")


def diagnostico_geral():
    """Lista TODOS os manifestos com baixas travadas em PENDENTE_ANALISE."""
    print(f"{C.BOLD}{C.YELLOW}━━━ MANIFESTOS COM BAIXAS TRAVADAS (PENDENTE_ANALISE) ━━━{C.END}\n")
    
    baixas_pendentes = BaixaNF.objects.filter(
        qualidade_canhoto='PENDENTE_ANALISE'
    ).select_related(
        'nota_fiscal', 'nota_fiscal__manifesto', 'nota_fiscal__manifesto__motorista', 'ocorrencia'
    ).order_by('data_baixa')
    
    if not baixas_pendentes.exists():
        print(f"  {C.GREEN}✅ Nenhuma baixa travada em PENDENTE_ANALISE encontrada! Tudo limpo.{C.END}\n")
        return
    
    # Agrupa por manifesto
    manifestos_afetados = {}
    for b in baixas_pendentes:
        mft_num = b.nota_fiscal.manifesto.numero_manifesto if b.nota_fiscal and b.nota_fiscal.manifesto else "SEM_MANIFESTO"
        if mft_num not in manifestos_afetados:
            manifestos_afetados[mft_num] = []
        manifestos_afetados[mft_num].append(b)
    
    print(f"  {C.RED}⚠️  {len(baixas_pendentes)} baixa(s) travada(s) em {len(manifestos_afetados)} manifesto(s){C.END}\n")
    
    for mft_num, baixas in manifestos_afetados.items():
        mft = baixas[0].nota_fiscal.manifesto if baixas[0].nota_fiscal else None
        motorista = mft.motorista.nome_completo if mft and mft.motorista else "Desconhecido"
        status_mft = mft.status if mft else "?"
        
        print(f"  {C.BOLD}📦 Manifesto #{mft_num}{C.END} | Motorista: {motorista} | Status: {status_mft}")
        
        for b in baixas:
            tempo_travado = timezone.now() - b.data_baixa if b.data_baixa else "N/A"
            if isinstance(tempo_travado, timedelta):
                minutos = int(tempo_travado.total_seconds() / 60)
                tempo_str = f"{minutos} min" if minutos < 60 else f"{minutos // 60}h {minutos % 60}min"
            else:
                tempo_str = "N/A"
            
            ocorrencia_str = f"{b.ocorrencia.codigo_tms} ({b.ocorrencia.descricao})" if b.ocorrencia else "Sem Ocorrência"
            foto_str = "Com Foto" if b.comprovante_foto_url else "SEM FOTO"
            
            print(f"    {C.RED}🔴{C.END} Baixa #{b.id} | NF {b.nota_fiscal.numero_nota}")
            print(f"       Travada há: {C.YELLOW}{tempo_str}{C.END}")
            print(f"       Ocorrência: {ocorrencia_str}")
            print(f"       Foto: {foto_str}")
            print(f"       Tentativa: {b.tentativa_foto} | solicitar_nova_foto: {b.solicitar_nova_foto}")
            print(f"       integrado_tms: {b.integrado_tms} | processado_tms: {b.processado_tms}")
            
            if b.comprovante_foto_url:
                print(f"       URL Foto: {b.comprovante_foto_url[:80]}...")
            if b.log_erro_tms:
                print(f"       {C.RED}Erro TMS: {b.log_erro_tms[:100]}{C.END}")
            print()
    
    # Resumo com sugestões
    print(f"{C.BOLD}{C.CYAN}━━━ DIAGNÓSTICO PROVÁVEL ━━━{C.END}\n")
    
    for mft_num, baixas in manifestos_afetados.items():
        for b in baixas:
            tempo = timezone.now() - b.data_baixa if b.data_baixa else timedelta(seconds=0)
            minutos = int(tempo.total_seconds() / 60) if isinstance(tempo, timedelta) else 0
            
            print(f"  Baixa #{b.id} (NF {b.nota_fiscal.numero_nota} / Mft #{mft_num}):")
            
            if not b.comprovante_foto_url:
                print(f"    {C.RED}🔴 CAUSA: Baixa sem foto mas marcada como PENDENTE_ANALISE.{C.END}")
                print(f"    {C.GREEN}➜ SOLUÇÃO: Liberar automaticamente (foto não existe para analisar).{C.END}")
            elif minutos > 5:
                print(f"    {C.RED}🔴 CAUSA: Task Celery provavelmente FALHOU ou NUNCA FOI EXECUTADA.{C.END}")
                print(f"    {C.YELLOW}   Possíveis razões:{C.END}")
                print(f"       1. Worker celery_worker_ai (ia_queue) está DOWN ou travado")
                print(f"       2. Task deu exceção silenciosa e não atualizou o status")
                print(f"       3. Redis perdeu a mensagem da fila")
                print(f"       4. subprocess.run (run_ia.py) travou sem retorno")
                print(f"    {C.GREEN}➜ SOLUÇÃO: Rode com --liberar para forçar a aprovação{C.END}")
            elif minutos > 1:
                print(f"    {C.YELLOW}⚠️  CAUSA: Task pode estar lenta (processando IA/YOLO).{C.END}")
                print(f"    {C.CYAN}   Verifique logs: docker logs rxtrack_homolog_celery_ai --tail 50{C.END}")
            else:
                print(f"    {C.CYAN}ℹ️  CAUSA: Baixa recente (< 1 min). Pode estar processando agora.{C.END}")
            print()


def diagnostico_manifesto(numero_manifesto):
    """Diagnóstico detalhado de um manifesto específico."""
    print(f"{C.BOLD}{C.YELLOW}━━━ DIAGNÓSTICO DO MANIFESTO #{numero_manifesto} ━━━{C.END}\n")
    
    try:
        mft = Manifesto.objects.select_related('motorista', 'filial', 'veiculo').get(numero_manifesto=str(numero_manifesto))
    except Manifesto.DoesNotExist:
        print(f"  {C.RED}❌ Manifesto #{numero_manifesto} NÃO ENCONTRADO no banco.{C.END}")
        return
    
    print(f"  {C.BOLD}📦 Manifesto #{mft.numero_manifesto}{C.END}")
    print(f"     Status: {mft.status}")
    print(f"     Finalizado: {mft.finalizado}")
    print(f"     Motorista: {mft.motorista.nome_completo if mft.motorista else 'N/A'}")
    print(f"     Filial: {mft.filial.nome if mft.filial else 'N/A'}")
    print(f"     Criado em: {mft.data_criacao}")
    print()
    
    # Notas do manifesto
    notas = NotaFiscal.objects.filter(manifesto=mft).prefetch_related('baixa_info', 'baixa_info__ocorrencia')
    print(f"  {C.BOLD}📋 {notas.count()} Nota(s) no manifesto:{C.END}\n")
    
    notas_travadas = 0
    notas_foto_ruim = 0
    notas_pendente = 0
    
    for nf in notas:
        baixa = nf.baixa_info.all().last()
        status_icon = "⬜"
        
        if not baixa:
            status_icon = "⬜"  # Sem baixa
            notas_pendente += 1
        elif baixa.qualidade_canhoto == 'PENDENTE_ANALISE':
            status_icon = f"{C.RED}🔴{C.END}"
            notas_travadas += 1
        elif baixa.solicitar_nova_foto:
            status_icon = f"{C.YELLOW}🟡{C.END}"
            notas_foto_ruim += 1
        elif baixa.qualidade_canhoto == 'APROVADO':
            status_icon = f"{C.GREEN}🟢{C.END}"
        elif baixa.qualidade_canhoto == 'APROVADO_MANUAL':
            status_icon = f"{C.GREEN}🟢{C.END}"
        else:
            status_icon = f"{C.CYAN}🔵{C.END}"
        
        print(f"    {status_icon} NF {nf.numero_nota} | Status: {nf.status} | Tipo: {nf.tipo_operacao}")
        
        if baixa:
            tempo = timezone.now() - baixa.data_baixa if baixa.data_baixa else None
            tempo_str = ""
            if tempo:
                minutos = int(tempo.total_seconds() / 60)
                tempo_str = f"{minutos} min atrás" if minutos < 60 else f"{minutos // 60}h {minutos % 60}min atrás"
            
            print(f"       Baixa #{baixa.id}: qualidade={baixa.qualidade_canhoto} | solicitar_nova_foto={baixa.solicitar_nova_foto}")
            print(f"       Ocorrência: {baixa.ocorrencia.codigo_tms if baixa.ocorrencia else 'N/A'} | Tentativa: {baixa.tentativa_foto}")
            print(f"       Data: {baixa.data_baixa} ({tempo_str})")
            print(f"       Foto: {'SIM' if baixa.comprovante_foto_url else 'NÃO'} | TMS: integrado={baixa.integrado_tms} processado={baixa.processado_tms}")
            if baixa.log_erro_tms:
                print(f"       {C.RED}Erro: {baixa.log_erro_tms[:150]}{C.END}")
        else:
            print(f"       {C.YELLOW}Sem baixa registrada{C.END}")
        print()
    
    # RESUMO
    print(f"{C.BOLD}{C.CYAN}━━━ RESUMO ━━━{C.END}")
    print(f"  Total de notas: {notas.count()}")
    print(f"  Notas sem baixa (pendentes): {notas_pendente}")
    print(f"  {C.RED}Notas travadas em PENDENTE_ANALISE: {notas_travadas}{C.END}")
    print(f"  {C.YELLOW}Notas com foto ilegível (aguardando refoto): {notas_foto_ruim}{C.END}")
    print()
    
    if notas_travadas > 0:
        print(f"  {C.RED}{C.BOLD}⚠️  ESTE MANIFESTO ESTÁ TRAVADO!{C.END}")
        print(f"  {C.YELLOW}  A tela fica em 'VERIFICANDO COMPROVANTES...' porque{C.END}")
        print(f"  {C.YELLOW}  existe(m) {notas_travadas} baixa(s) com qualidade_canhoto='PENDENTE_ANALISE'.{C.END}")
        print(f"  {C.YELLOW}  O frontend faz polling a cada 3s e nunca vai liberar até que{C.END}")
        print(f"  {C.YELLOW}  o status mude para 'APROVADO' ou outro estado final.{C.END}")
        print()
        print(f"  {C.GREEN}➜ Para LIBERAR, rode:{C.END}")
        print(f"    docker exec -it rxtrack_homolog_backend python diagnostico_ia.py {numero_manifesto} --liberar")
    elif notas_foto_ruim > 0:
        print(f"  {C.YELLOW}{C.BOLD}⚠️  Manifesto bloqueado por CANHOTO ILEGÍVEL{C.END}")
        print(f"  {C.YELLOW}  O motorista precisa reenviar foto ou o SAC precisa liberar.{C.END}")
    else:
        print(f"  {C.GREEN}✅ Manifesto sem problemas de IA.{C.END}")


def liberar_manifesto(numero_manifesto):
    """Força a liberação de todas as baixas PENDENTE_ANALISE de um manifesto."""
    print(f"{C.BOLD}{C.RED}━━━ LIBERAÇÃO FORÇADA DO MANIFESTO #{numero_manifesto} ━━━{C.END}\n")
    
    try:
        mft = Manifesto.objects.get(numero_manifesto=str(numero_manifesto))
    except Manifesto.DoesNotExist:
        print(f"  {C.RED}❌ Manifesto #{numero_manifesto} NÃO ENCONTRADO.{C.END}")
        return
    
    baixas = BaixaNF.objects.filter(
        nota_fiscal__manifesto=mft,
        qualidade_canhoto='PENDENTE_ANALISE'
    )
    
    total = baixas.count()
    if total == 0:
        print(f"  {C.GREEN}✅ Nenhuma baixa pendente para liberar.{C.END}")
        return
    
    print(f"  Liberando {total} baixa(s)...\n")
    
    for b in baixas:
        old_status = b.qualidade_canhoto
        b.qualidade_canhoto = 'APROVADO'
        b.solicitar_nova_foto = False
        b.save(update_fields=['qualidade_canhoto', 'solicitar_nova_foto'])
        
        print(f"  {C.GREEN}✅ Baixa #{b.id} (NF {b.nota_fiscal.numero_nota}): {old_status} → APROVADO{C.END}")
        
        # Dispara o envio ao TMS se ainda não foi integrado
        if not b.integrado_tms:
            try:
                from AgenteIa.tasks import finalizar_fluxo_tms
                finalizar_fluxo_tms(b)
                print(f"     {C.CYAN}↳ Enviado para TMS (finalizar_fluxo_tms){C.END}")
            except Exception as e:
                print(f"     {C.RED}↳ Erro ao enviar para TMS: {e}{C.END}")
    
    # Envia atualização do painel
    try:
        from manifesto.services import enviar_painel
        enviar_painel(mft)
        print(f"\n  {C.CYAN}📡 Painel WebSocket atualizado.{C.END}")
    except Exception as e:
        print(f"\n  {C.YELLOW}⚠️  Erro ao atualizar painel: {e}{C.END}")
    
    print(f"\n  {C.GREEN}{C.BOLD}✅ Manifesto #{numero_manifesto} LIBERADO com sucesso!{C.END}")
    print(f"  {C.CYAN}  O motorista já deve ver o botão FINALIZAR no app.{C.END}")


def checar_celery():
    """Verifica o estado dos workers Celery e da fila ia_queue."""
    print(f"{C.BOLD}{C.YELLOW}━━━ STATUS DO CELERY / FILAS ━━━{C.END}\n")
    
    import subprocess
    
    # 1. Verifica se o worker de IA está respondendo
    print(f"  {C.BOLD}🔧 Workers Celery:{C.END}")
    try:
        result = subprocess.run(
            ['celery', '-A', 'core', 'inspect', 'ping', '--timeout', '5'],
            capture_output=True, text=True, timeout=15
        )
        if 'pong' in result.stdout.lower():
            print(f"    {C.GREEN}✅ Workers respondendo!{C.END}")
        else:
            print(f"    {C.RED}❌ Workers NÃO responderam ao ping!{C.END}")
        print(f"    Output: {result.stdout[:300]}")
        if result.stderr:
            print(f"    {C.RED}Stderr: {result.stderr[:200]}{C.END}")
    except subprocess.TimeoutExpired:
        print(f"    {C.RED}❌ TIMEOUT! Workers não responderam em 15s.{C.END}")
    except Exception as e:
        print(f"    {C.RED}❌ Erro ao verificar: {e}{C.END}")
    
    print()
    
    # 2. Verifica filas ativas
    print(f"  {C.BOLD}📥 Filas ativas:{C.END}")
    try:
        result = subprocess.run(
            ['celery', '-A', 'core', 'inspect', 'active_queues', '--timeout', '5'],
            capture_output=True, text=True, timeout=15
        )
        print(f"    {result.stdout[:500]}")
    except Exception as e:
        print(f"    {C.RED}Erro: {e}{C.END}")
    
    print()
    
    # 3. Verifica tasks ativas (em execução agora)
    print(f"  {C.BOLD}⏳ Tasks em execução:{C.END}")
    try:
        result = subprocess.run(
            ['celery', '-A', 'core', 'inspect', 'active', '--timeout', '5'],
            capture_output=True, text=True, timeout=15
        )
        output = result.stdout.strip()
        if 'empty' in output.lower() or not output:
            print(f"    {C.CYAN}Nenhuma task em execução no momento.{C.END}")
        else:
            print(f"    {output[:500]}")
    except Exception as e:
        print(f"    {C.RED}Erro: {e}{C.END}")
    
    print()
    
    # 4. Verifica tasks reservadas (na fila aguardando)
    print(f"  {C.BOLD}📋 Tasks reservadas (na fila):{C.END}")
    try:
        result = subprocess.run(
            ['celery', '-A', 'core', 'inspect', 'reserved', '--timeout', '5'],
            capture_output=True, text=True, timeout=15
        )
        output = result.stdout.strip()
        if 'empty' in output.lower() or not output:
            print(f"    {C.CYAN}Nenhuma task na fila.{C.END}")
        else:
            print(f"    {output[:500]}")
    except Exception as e:
        print(f"    {C.RED}Erro: {e}{C.END}")
    
    print()
    
    # 5. Verifica Redis
    print(f"  {C.BOLD}🔴 Redis:{C.END}")
    try:
        from core.redis_client import get_redis_client
        r = get_redis_client()
        info = r.info()
        print(f"    {C.GREEN}✅ Redis UP | Memória: {info.get('used_memory_human', 'N/A')} | Clients: {info.get('connected_clients', 'N/A')}{C.END}")
        
        # Verifica tamanho das filas Celery no Redis
        for queue_name in ['celery', 'ia_queue']:
            qlen = r.llen(queue_name)
            color = C.RED if qlen > 10 else (C.YELLOW if qlen > 0 else C.GREEN)
            print(f"    Fila '{queue_name}': {color}{qlen} mensagem(s){C.END}")
    except Exception as e:
        print(f"    {C.RED}❌ Erro ao conectar no Redis: {e}{C.END}")
    
    print()
    
    # 6. Sugere comandos úteis
    print(f"{C.BOLD}{C.CYAN}━━━ COMANDOS ÚTEIS PARA DEBUG ━━━{C.END}\n")
    print(f"  # Ver logs do worker IA (últimas 50 linhas):")
    print(f"  {C.CYAN}docker logs rxtrack_homolog_celery_ai --tail 50{C.END}\n")
    print(f"  # Ver logs do worker IA em tempo real:")
    print(f"  {C.CYAN}docker logs -f rxtrack_homolog_celery_ai{C.END}\n")
    print(f"  # Ver logs do backend:")
    print(f"  {C.CYAN}docker logs rxtrack_homolog_backend --tail 50{C.END}\n")
    print(f"  # Reiniciar worker IA:")
    print(f"  {C.CYAN}docker restart rxtrack_homolog_celery_ai{C.END}\n")
    print(f"  # Ver se o container IA está rodando:")
    print(f"  {C.CYAN}docker ps | grep celery_ai{C.END}\n")


def listar_baixas_com_foto_ilegivel():
    """Lista baixas que estão com solicitar_nova_foto=True (bloqueando finalização)."""
    print(f"{C.BOLD}{C.YELLOW}━━━ BAIXAS COM CANHOTO ILEGÍVEL (solicitar_nova_foto=True) ━━━{C.END}\n")
    
    baixas = BaixaNF.objects.filter(
        solicitar_nova_foto=True
    ).select_related(
        'nota_fiscal', 'nota_fiscal__manifesto', 'nota_fiscal__manifesto__motorista'
    ).order_by('data_baixa')
    
    if not baixas.exists():
        print(f"  {C.GREEN}✅ Nenhuma baixa pendente de nova foto.{C.END}\n")
        return
    
    print(f"  {C.YELLOW}⚠️  {baixas.count()} baixa(s) aguardando nova foto:{C.END}\n")
    
    for b in baixas:
        mft = b.nota_fiscal.manifesto if b.nota_fiscal else None
        mft_num = mft.numero_manifesto if mft else "?"
        motorista = mft.motorista.nome_completo if mft and mft.motorista else "?"
        
        print(f"    {C.YELLOW}🟡{C.END} Baixa #{b.id} | NF {b.nota_fiscal.numero_nota} | Mft #{mft_num}")
        print(f"       Motorista: {motorista} | Tentativa: {b.tentativa_foto}/3")
        print(f"       qualidade: {b.qualidade_canhoto} | motivo: {b.motivo_rejeicao_ia}")
        print()


# =================== MAIN ===================
if __name__ == '__main__':
    banner()
    
    args = sys.argv[1:]
    
    if not args:
        # Sem argumentos: diagnóstico geral
        diagnostico_geral()
        listar_baixas_com_foto_ilegivel()
        print(f"\n{C.BOLD}Uso:{C.END}")
        print(f"  python diagnostico_ia.py                     → Diagnóstico geral")
        print(f"  python diagnostico_ia.py 67087               → Diagnóstico do manifesto 67087")
        print(f"  python diagnostico_ia.py 67087 --liberar     → Libera manifesto travado")
        print(f"  python diagnostico_ia.py --celery            → Status do Celery/Redis/Filas")
        print()
    elif args[0] == '--celery':
        checar_celery()
    elif len(args) >= 2 and args[1] == '--liberar':
        diagnostico_manifesto(args[0])
        print()
        liberar_manifesto(args[0])
    else:
        diagnostico_manifesto(args[0])
