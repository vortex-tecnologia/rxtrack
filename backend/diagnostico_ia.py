#!/usr/bin/env python
"""
==========================================================================
 DIAGNÓSTICO DE MANIFESTOS TRAVADOS NA VERIFICAÇÃO DE IA
 (Compatível com Django Tenants / Multi-tenant)
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
from django_tenants.utils import schema_context
from tenants.models import Client


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


def get_tenants():
    """Retorna todos os tenants cadastrados excluindo o public."""
    tenants = list(Client.objects.exclude(schema_name='public'))
    return tenants


def diagnostico_geral():
    """Lista TODOS os manifestos com baixas travadas em PENDENTE_ANALISE em todos os tenants."""
    from manifesto.models import Manifesto, NotaFiscal, BaixaNF
    
    tenants = get_tenants()
    if not tenants:
        print(f"  {C.RED}❌ Nenhum tenant encontrado.{C.END}\n")
        return

    print(f"{C.BOLD}{C.YELLOW}━━━ MANIFESTOS COM BAIXAS TRAVADAS (PENDENTE_ANALISE) ━━━{C.END}\n")

    total_geral_travadas = 0

    for tenant in tenants:
        with schema_context(tenant.schema_name):
            baixas_pendentes = BaixaNF.objects.filter(
                qualidade_canhoto='PENDENTE_ANALISE'
            ).select_related(
                'nota_fiscal', 'nota_fiscal__manifesto', 'nota_fiscal__manifesto__motorista', 'ocorrencia'
            ).order_by('data_baixa')

            if not baixas_pendentes.exists():
                continue

            total_geral_travadas += baixas_pendentes.count()
            
            # Agrupa por manifesto
            manifestos_afetados = {}
            for b in baixas_pendentes:
                mft_num = b.nota_fiscal.manifesto.numero_manifesto if b.nota_fiscal and b.nota_fiscal.manifesto else "SEM_MANIFESTO"
                if mft_num not in manifestos_afetados:
                    manifestos_afetados[mft_num] = []
                manifestos_afetados[mft_num].append(b)

            print(f"  {C.HEADER}🏢 Tenant: {tenant.name} (Schema: {tenant.schema_name}){C.END}")
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

    if total_geral_travadas == 0:
        print(f"  {C.GREEN}✅ Nenhuma baixa travada em PENDENTE_ANALISE encontrada em nenhum tenant!{C.END}\n")


def diagnostico_manifesto(numero_manifesto):
    """Diagnóstico detalhado de um manifesto específico."""
    from manifesto.models import Manifesto, NotaFiscal, BaixaNF

    tenants = get_tenants()
    encontrado = False

    for tenant in tenants:
        with schema_context(tenant.schema_name):
            try:
                mft = Manifesto.objects.select_related('motorista', 'filial', 'veiculo').get(numero_manifesto=str(numero_manifesto))
            except Manifesto.DoesNotExist:
                continue

            encontrado = True
            print(f"{C.BOLD}{C.YELLOW}━━━ DIAGNÓSTICO DO MANIFESTO #{numero_manifesto} (Tenant: {tenant.name}) ━━━{C.END}\n")
            print(f"  {C.BOLD}📦 Manifesto #{mft.numero_manifesto}{C.END}")
            print(f"     Status: {mft.status}")
            print(f"     Finalizado: {mft.finalizado}")
            print(f"     Motorista: {mft.motorista.nome_completo if mft.motorista else 'N/A'}")
            print(f"     Filial: {mft.filial.nome if mft.filial else 'N/A'}")
            print(f"     Criado em: {mft.data_criacao}")
            print()

            notas = NotaFiscal.objects.filter(manifesto=mft).prefetch_related('baixa_info', 'baixa_info__ocorrencia')
            print(f"  {C.BOLD}📋 {notas.count()} Nota(s) no manifesto:{C.END}\n")

            notas_travadas = 0
            notas_foto_ruim = 0
            notas_pendente = 0

            for nf in notas:
                baixa = nf.baixa_info.all().last()
                if not baixa:
                    status_icon = "⬜"
                    notas_pendente += 1
                elif baixa.qualidade_canhoto == 'PENDENTE_ANALISE':
                    status_icon = f"{C.RED}🔴{C.END}"
                    notas_travadas += 1
                elif baixa.solicitar_nova_foto:
                    status_icon = f"{C.YELLOW}🟡{C.END}"
                    notas_foto_ruim += 1
                elif baixa.qualidade_canhoto in ['APROVADO', 'APROVADO_MANUAL']:
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

            print(f"{C.BOLD}{C.CYAN}━━━ RESUMO ━━━{C.END}")
            print(f"  Total de notas: {notas.count()}")
            print(f"  Notas sem baixa (pendentes): {notas_pendente}")
            print(f"  {C.RED}Notas travadas em PENDENTE_ANALISE: {notas_travadas}{C.END}")
            print(f"  {C.YELLOW}Notas com foto ilegível (aguardando refoto): {notas_foto_ruim}{C.END}")
            print()

            if notas_travadas > 0:
                print(f"  {C.RED}{C.BOLD}⚠️  ESTE MANIFESTO ESTÁ TRAVADO NO LOADING DA IA!{C.END}")
                print(f"  {C.GREEN}➜ Para LIBERAR agora, rode:{C.END}")
                print(f"    docker exec -it rxtrack_homolog_backend python diagnostico_ia.py {numero_manifesto} --liberar")
            elif notas_foto_ruim > 0:
                print(f"  {C.YELLOW}{C.BOLD}⚠️  Manifesto bloqueado por CANHOTO ILEGÍVEL (motorista precisa reenviar foto){C.END}")
            else:
                print(f"  {C.GREEN}✅ Manifesto sem problemas de IA.{C.END}")
            break

    if not encontrado:
        print(f"  {C.RED}❌ Manifesto #{numero_manifesto} NÃO ENCONTRADO em nenhum tenant.{C.END}")


def liberar_manifesto(numero_manifesto):
    """Força a liberação de todas as baixas PENDENTE_ANALISE de um manifesto."""
    from manifesto.models import Manifesto, BaixaNF

    tenants = get_tenants()
    for tenant in tenants:
        with schema_context(tenant.schema_name):
            try:
                mft = Manifesto.objects.get(numero_manifesto=str(numero_manifesto))
            except Manifesto.DoesNotExist:
                continue

            baixas = BaixaNF.objects.filter(
                nota_fiscal__manifesto=mft,
                qualidade_canhoto='PENDENTE_ANALISE'
            )

            total = baixas.count()
            if total == 0:
                print(f"  {C.GREEN}✅ Nenhuma baixa pendente para liberar no manifesto #{numero_manifesto}.{C.END}")
                return

            print(f"  Liberando {total} baixa(s) no schema '{tenant.schema_name}'...\n")

            for b in baixas:
                old_status = b.qualidade_canhoto
                b.qualidade_canhoto = 'APROVADO'
                b.solicitar_nova_foto = False
                b.save(update_fields=['qualidade_canhoto', 'solicitar_nova_foto'])

                print(f"  {C.GREEN}✅ Baixa #{b.id} (NF {b.nota_fiscal.numero_nota}): {old_status} → APROVADO{C.END}")

                if not b.integrado_tms:
                    try:
                        from AgenteIa.tasks import finalizar_fluxo_tms
                        finalizar_fluxo_tms(b)
                        print(f"     {C.CYAN}↳ Enviado para TMS (finalizar_fluxo_tms){C.END}")
                    except Exception as e:
                        print(f"     {C.RED}↳ Erro ao enviar para TMS: {e}{C.END}")

            try:
                from manifesto.services import enviar_painel
                enviar_painel(mft)
                print(f"\n  {C.CYAN}📡 Painel WebSocket atualizado.{C.END}")
            except Exception as e:
                print(f"\n  {C.YELLOW}⚠️  Erro ao atualizar painel: {e}{C.END}")

            print(f"\n{C.GREEN}{C.BOLD}✅ Manifesto #{numero_manifesto} LIBERADO com sucesso!{C.END}")
            print(f"  {C.CYAN}  O motorista já pode ver o botão FINALIZAR no app.{C.END}")
            return

    print(f"  {C.RED}❌ Manifesto #{numero_manifesto} não encontrado.{C.END}")


def checar_celery():
    """Verifica o estado dos workers Celery e da fila ia_queue."""
    print(f"{C.BOLD}{C.YELLOW}━━━ STATUS DO CELERY / FILAS ━━━{C.END}\n")
    import subprocess

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
    except Exception as e:
        print(f"    {C.RED}❌ Erro ao verificar Celery: {e}{C.END}")

    print(f"\n  {C.BOLD}🔴 Redis:{C.END}")
    try:
        from core.redis_client import get_redis_client
        r = get_redis_client()
        info = r.info()
        print(f"    {C.GREEN}✅ Redis UP | Memória: {info.get('used_memory_human', 'N/A')}{C.END}")
        for queue_name in ['celery', 'ia_queue']:
            qlen = r.llen(queue_name)
            color = C.RED if qlen > 10 else (C.YELLOW if qlen > 0 else C.GREEN)
            print(f"    Fila '{queue_name}': {color}{qlen} mensagem(s){C.END}")
    except Exception as e:
        print(f"    {C.RED}❌ Erro Redis: {e}{C.END}")


def listar_baixas_com_foto_ilegivel():
    """Lista baixas com solicitar_nova_foto=True."""
    from manifesto.models import BaixaNF
    tenants = get_tenants()
    
    for tenant in tenants:
        with schema_context(tenant.schema_name):
            baixas = BaixaNF.objects.filter(solicitar_nova_foto=True).select_related('nota_fiscal', 'nota_fiscal__manifesto', 'nota_fiscal__manifesto__motorista')
            if baixas.exists():
                print(f"\n{C.BOLD}{C.YELLOW}━━━ BAIXAS COM CANHOTO ILEGÍVEL (Tenant: {tenant.name}) ━━━{C.END}")
                for b in baixas:
                    mft_num = b.nota_fiscal.manifesto.numero_manifesto if b.nota_fiscal and b.nota_fiscal.manifesto else "?"
                    print(f"    {C.YELLOW}🟡{C.END} Baixa #{b.id} | NF {b.nota_fiscal.numero_nota} | Mft #{mft_num} | Tentativa: {b.tentativa_foto}/3")


if __name__ == '__main__':
    banner()
    args = sys.argv[1:]
    if not args:
        diagnostico_geral()
        listar_baixas_com_foto_ilegivel()
    elif args[0] == '--celery':
        checar_celery()
    elif len(args) >= 2 and args[1] == '--liberar':
        diagnostico_manifesto(args[0])
        print()
        liberar_manifesto(args[0])
    else:
        diagnostico_manifesto(args[0])
