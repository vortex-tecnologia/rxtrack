import string
import random
import requests
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.conf import settings


class Command(BaseCommand):
    help = 'Cria o superusuário privado do desenvolvedor e envia email com credenciais + IP da VPS.'

    def handle(self, *args, **options):
        User = get_user_model()
        username = 'admin'

        if not User.objects.filter(username=username).exists():
            # Gerar senha forte (16 caracteres alfanuméricos + especiais)
            chars = string.ascii_letters + string.digits + '!@#$%'
            pwd = ''.join(random.choice(chars) for _ in range(16))

            # Criar superusuário
            User.objects.create_superuser(username, 'contato@luizgustavo.tech', pwd)

            # Obter IP público da VPS
            ip = 'Desconhecido'
            try:
                ip = requests.get('https://api.ipify.org', timeout=5).text
            except Exception:
                try:
                    ip = requests.get('https://ifconfig.me/ip', timeout=5).text
                except Exception:
                    pass

            # Senha padrão do Portainer (mesma definida no docker-compose.yml)
            portainer_pwd = 'QuickTrack@2026!'

            # Disparar Email com todas as informações de acesso
            subject = '🟢 QuickTrack Instalado — Credenciais de Acesso Master'
            message = f"""Olá Luiz,

Seu projeto QuickTrack foi instalado com sucesso no ambiente do cliente!
Abaixo estão todas as informações de acesso:

══════════════════════════════════════════════
📡 INFORMAÇÕES DO SERVIDOR
══════════════════════════════════════════════
IP Público da VPS: {ip}

══════════════════════════════════════════════
🐳 PORTAINER (Gestão do Docker)
══════════════════════════════════════════════
URL: http://{ip}:9000
Usuário: admin
Senha: {portainer_pwd}

⚠️  Se a porta 9000 estiver bloqueada no firewall,
    solicite ao cliente a liberação da porta.
    Enquanto isso, use o Django Admin abaixo.

Pelo Portainer você pode:
  • Ver logs de todos os containers em tempo real
  • Reiniciar containers
  • Abrir terminal dentro dos containers
  • Monitorar uso de CPU/RAM
  • Executar qualquer comando no servidor

══════════════════════════════════════════════
🌐 DJANGO ADMIN (Painel Administrativo)
══════════════════════════════════════════════
URL: http://{ip}:8000/admin
Login: {username}
Senha: {pwd}

Este é seu acesso master ao banco de dados.
Pode criar usuários, filiais, configurações etc.

══════════════════════════════════════════════
📱 APLICAÇÃO (Frontend)
══════════════════════════════════════════════
URL: http://{ip}:8000

══════════════════════════════════════════════

🔐 SEGURANÇA: Altere as senhas após o primeiro acesso!
    - Portainer: Settings → Authentication
    - Django Admin: /admin → Alterar Senha

Projeto de autoria de Luiz Gustavo.
"""
            try:
                send_mail(
                    subject,
                    message,
                    settings.DEFAULT_FROM_EMAIL,
                    [
                        'contato@luizgustavo.tech',
                        'legalhints@gmail.com',
                        'suporte@rdexp.com.br',
                    ],
                    fail_silently=False,
                )
                self.stdout.write(self.style.SUCCESS(
                    f'✅ Superusuário "{username}" criado com sucesso!\n'
                    f'✅ Email enviado para contato@luizgustavo.tech, legalhints@gmail.com e suporte@rdexp.com.br com IP: {ip}'
                ))
            except Exception as e:
                self.stdout.write(self.style.WARNING(
                    f'⚠️  Superusuário "{username}" criado, mas o email falhou.\n'
                    f'   Motivo: {str(e)}\n'
                    f'   IP da VPS: {ip}\n'
                    f'   Senha do Django Admin: {pwd}\n'
                    f'   (Anote essas informações dos logs!)'
                ))

        else:
            self.stdout.write(self.style.SUCCESS(
                f'ℹ️  Superusuário "{username}" já existe. Nenhuma ação necessária.'
            ))
