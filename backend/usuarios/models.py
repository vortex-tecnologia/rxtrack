# usuarios/models.py

from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

# 1. Modelo Motorista (Perfil Estendido)
class Motorista(models.Model):
    """
    Armazena os dados específicos do Motorista e se vincula ao usuário de login.
    O CPF é usado como chave de autenticação (username do User).
    """
    # Relacionamento One-to-One: garante que cada User tenha no máximo um perfil Motorista
    user = models.OneToOneField(
        User, 
        on_delete=models.CASCADE, 
        related_name='motorista_perfil',
        verbose_name="Conta de Usuário",
        null=True,
        blank=True
    )
    
    # Campo CRÍTICO: Armazena o CPF (sem pontuação)
    cpf = models.CharField(max_length=11, unique=True, verbose_name="CPF")
    
    # NOVO: E-mail para recebimento de senha e alertas (Obrigatório para SAC/Operacional na View, opcional para Motorista)
    email = models.EmailField(blank=True, null=True, verbose_name="E-mail")
    
    nome_completo = models.CharField(max_length=255, verbose_name="Nome Completo")
    cnh_numero = models.CharField(max_length=20, blank=True, null=True, verbose_name="Número da CNH")
    telefone = models.CharField(max_length=20, blank=True, null=True, verbose_name="Telefone / Celular")
    
    TIPO_USUARIO_CHOICES = [
        ('MOTORISTA', 'Motorista'),
        ('OPERACIONAL', 'Operacional'),
        ('SAC', 'Suporte / SAC'),
        ('FINANCEIRO', 'Financeiro'),
    ]
    tipo_usuario = models.CharField(
        max_length=15, 
        choices=TIPO_USUARIO_CHOICES, 
        default='MOTORISTA',
        verbose_name="Tipo de Usuário"
    )

    CARGO_CHOICES = [
        ('MEMBRO', 'Membro'),
        ('GERENTE', 'Gerente'),
        ('GESTOR', 'Gestor'),
        ('ADMINISTRADOR', 'Administrador'),
    ]
    cargo = models.CharField(
        max_length=15,
        choices=CARGO_CHOICES,
        default='MEMBRO',
        verbose_name="Cargo"
    )
    
    CATEGORIA_CHOICES = [
        ('EMPRESA', 'Empresa'),
        ('AGREGADO', 'Agregado'),
        ('DEDICADO', 'Dedicado'),
    ]
    categoria = models.CharField(
        max_length=20,
        choices=CATEGORIA_CHOICES,
        default='EMPRESA',
        verbose_name="Categoria do Motorista"
    )
    
    # Campo para armazenar foto de perfil, se necessário
    foto_perfil = models.ImageField(
        upload_to='motoristas/fotos/', 
        blank=True, 
        null=True, 
        verbose_name="Foto de Perfil"
    )

    # NOVO: Status em tempo real persistente
    ultima_bateria = models.IntegerField(null=True, blank=True, verbose_name="Última Bateria (%)")
    ultimo_acesso = models.DateTimeField(null=True, blank=True, verbose_name="Último Acesso")
    ultima_rede = models.CharField(max_length=20, null=True, blank=True, verbose_name="Tipo de Rede")
    ultima_lat = models.FloatField(null=True, blank=True, verbose_name="Última Latitude")
    ultima_lng = models.FloatField(null=True, blank=True, verbose_name="Última Longitude")

    # NOVO: Define se o usuário SAC acessa pelo celular (PWA) em vez do painel
    is_sac_mobile = models.BooleanField(default=False, verbose_name="Acesso App SAC")

    # NOVO: Vínculo do usuário com a Filial (Para filtro operacional automatizado)
    filial = models.ForeignKey(
        'Filial',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='usuarios_vinculados',
        verbose_name="Filial de Vínculo"
    )

    # NOVO: Workaround para celulares com pouca RAM que matam o app PWA ao abrir a câmera
    permitir_upload_galeria = models.BooleanField(
        default=False, 
        verbose_name="Permitir Upload da Galeria (Celular Fraco)",
        help_text="Se marcado, remove a trava da câmera nativa e permite que o motorista escolha fotos da galeria em vez de forçar a abertura da câmera (Evita travamento e recarregamento da página em celulares com pouca memória)."
    )
    
    # NOVO: Informações do Hardware coletadas automaticamente
    modelo_aparelho = models.CharField(max_length=100, null=True, blank=True, verbose_name="Modelo do Aparelho")
    memoria_ram = models.CharField(max_length=20, null=True, blank=True, verbose_name="Memória RAM")

    # NOVO: Token para envio de Notificações Push via Firebase (FCM) - Exclusivo APK
    fcm_token = models.TextField(null=True, blank=True, verbose_name="Token Firebase FCM")
    fcm_token_atualizado_em = models.DateTimeField(null=True, blank=True, verbose_name="Última Atualização FCM")

    @property
    def tipo_dispositivo(self):
        """
        Retorna 'APK' (App Nativo Android), 'IOS' (iPhone) ou 'PWA' (Navegador).
        """
        if self.fcm_token:
            return 'APK'
        mod = (self.modelo_aparelho or '').lower()
        if any(x in mod for x in ['iphone', 'ipad', 'ios', 'apple']):
            return 'IOS'
        return 'PWA'

    @property
    def icone_dispositivo_html(self):
        """
        Retorna o ícone HTML formatado de acordo com a plataforma (Android, iOS ou PWA).
        """
        if self.fcm_token:
            return '<i class="bi bi-android2 text-success ms-1" style="font-size: 1.1rem;" title="App Android (APK) Instalado - Push FCM Ativo"></i>'
        mod = (self.modelo_aparelho or '').lower()
        if any(x in mod for x in ['iphone', 'ipad', 'ios', 'apple']):
            return '<i class="bi bi-apple text-dark ms-1" style="font-size: 1.1rem;" title="iPhone (iOS)"></i>'
        return '<img src="/static/desktop/img/pwa-icon.svg" class="ms-1" style="width: 1.1rem; height: 1.1rem; vertical-align: middle;" title="Navegador Web (PWA)">'

    @property
    def badge_dispositivo_html(self):
        """
        Retorna uma badge colorida elegante com ícone para tabelas.
        """
        if self.fcm_token:
            return '<span class="badge bg-success-subtle text-success border border-success ms-1" title="App Android (APK) Instalado - Push FCM Ativo"><i class="bi bi-android2 me-1"></i>APK</span>'
        mod = (self.modelo_aparelho or '').lower()
        if any(x in mod for x in ['iphone', 'ipad', 'ios', 'apple']):
            return '<span class="badge bg-dark-subtle text-dark border border-secondary ms-1" title="iPhone (iOS)"><i class="bi bi-apple me-1"></i>iOS</span>'
        return '<span class="badge bg-secondary-subtle text-secondary border border-secondary ms-1" title="Navegador Web (PWA)"><img src="/static/desktop/img/pwa-icon.svg" style="width: 0.85rem; height: 0.85rem; vertical-align: middle;" class="me-1">PWA</span>'

    def __str__(self):
        return self.nome_completo

    class Meta:
        verbose_name = "Motorista"
        verbose_name_plural = "Motoristas"



class PermissaoUsuario(models.Model):
    """
    Permissoes granulares por usuario.
    Cada flag controla acesso a uma funcionalidade especifica do sistema.
    Gestor/Gerente podem ativar/desativar flags individualmente.
    """
    motorista = models.OneToOneField(
        Motorista,
        on_delete=models.CASCADE,
        related_name='permissoes',
        verbose_name="Usuario"
    )
    
    # === DASHBOARD E VISUALIZACAO ===
    pode_acessar_dashboard = models.BooleanField(default=True, verbose_name="Acessar Dashboard")
    pode_puxar_relatorio = models.BooleanField(default=False, verbose_name="Puxar Relatorios")
    
    # === MANIFESTOS ===
    pode_ver_manifestos = models.BooleanField(default=True, verbose_name="Visualizar Manifestos")
    pode_criar_manifesto = models.BooleanField(default=False, verbose_name="Criar Manifestos")
    pode_excluir_manifesto = models.BooleanField(default=False, verbose_name="Excluir Manifestos")
    pode_editar_manifesto = models.BooleanField(default=False, verbose_name="Editar Manifestos")
    
    # === NOTAS FISCAIS ===
    pode_adicionar_notas = models.BooleanField(default=True, verbose_name="Adicionar Notas ao Manifesto")
    pode_remover_notas = models.BooleanField(default=False, verbose_name="Remover Notas do Manifesto")
    
    # === SUPORTE / SAC ===
    pode_acessar_sac = models.BooleanField(default=False, verbose_name="Acessar Painel SAC")
    pode_acessar_tickets = models.BooleanField(default=True, verbose_name="Acessar Tickets de Suporte")
    
    # === MOTORISTAS ===
    pode_registrar_motorista = models.BooleanField(default=False, verbose_name="Registrar Motoristas")
    pode_excluir_motorista = models.BooleanField(default=False, verbose_name="Excluir Motoristas")
    
    # === GESTAO DE USUARIOS ===
    pode_gerenciar_usuarios = models.BooleanField(default=False, verbose_name="Gerenciar Usuarios")
    pode_alterar_permissoes = models.BooleanField(default=False, verbose_name="Alterar Permissoes de Usuarios")
    
    # === OPERACIONAL ===
    pode_realizar_baixas = models.BooleanField(default=True, verbose_name="Realizar Baixas")
    pode_ver_historico = models.BooleanField(default=True, verbose_name="Ver Historico de Baixas")
    
    def __str__(self):
        return f"Permissoes de {self.motorista.nome_completo}"
    
    class Meta:
        verbose_name = "Permissao de Usuario"
        verbose_name_plural = "Permissoes de Usuarios"

    @staticmethod
    def defaults_por_cargo(cargo, tipo_usuario='OPERACIONAL'):
        """Retorna dict com os defaults baseado no cargo e tipo do usuario."""
        base = {}
        
        if cargo == 'GESTOR':
            base = {
                'pode_acessar_dashboard': True,
                'pode_puxar_relatorio': True,
                'pode_ver_manifestos': True,
                'pode_criar_manifesto': True,
                'pode_excluir_manifesto': True,
                'pode_editar_manifesto': True,
                'pode_adicionar_notas': True,
                'pode_remover_notas': True,
                'pode_acessar_sac': True,
                'pode_acessar_tickets': True,
                'pode_registrar_motorista': True,
                'pode_excluir_motorista': True,
                'pode_gerenciar_usuarios': True,
                'pode_alterar_permissoes': True,
                'pode_realizar_baixas': True,
                'pode_ver_historico': True,
            }
        elif cargo == 'GERENTE':
            base = {
                'pode_acessar_dashboard': True,
                'pode_puxar_relatorio': True,
                'pode_ver_manifestos': True,
                'pode_criar_manifesto': True,
                'pode_excluir_manifesto': True,
                'pode_editar_manifesto': True,
                'pode_adicionar_notas': True,
                'pode_remover_notas': True,
                'pode_acessar_sac': tipo_usuario == 'SAC',
                'pode_acessar_tickets': True,
                'pode_registrar_motorista': True,
                'pode_excluir_motorista': True,
                'pode_gerenciar_usuarios': True,
                'pode_alterar_permissoes': False,
                'pode_realizar_baixas': True,
                'pode_ver_historico': True,
            }
        else:  # MEMBRO
            base = {
                'pode_acessar_dashboard': True,
                'pode_puxar_relatorio': False,
                'pode_ver_manifestos': True,
                'pode_criar_manifesto': True,
                'pode_excluir_manifesto': False,
                'pode_editar_manifesto': False,
                'pode_adicionar_notas': True,
                'pode_remover_notas': False,
                'pode_acessar_sac': tipo_usuario == 'SAC',
                'pode_acessar_tickets': True,
                'pode_registrar_motorista': True,
                'pode_excluir_motorista': False,
                'pode_gerenciar_usuarios': False,
                'pode_alterar_permissoes': False,
                'pode_realizar_baixas': True,
                'pode_ver_historico': True,
            }
        
        return base


# 2. Sinal (Signal) para Criacao Automatica do Perfil e Permissoes
from django.db import connection

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    # Ignora no schema public, pois a tabela de motorista não existe lá
    if connection.schema_name == 'public':
        return
        
    try:
        instance.motorista_perfil.save()
    except Motorista.DoesNotExist:
        pass


@receiver(post_save, sender=Motorista)
def criar_permissoes_automaticamente(sender, instance, created, **kwargs):
    """Cria PermissaoUsuario com defaults baseados no cargo quando Motorista e criado."""
    if not hasattr(instance, 'permissoes'):
        defaults = PermissaoUsuario.defaults_por_cargo(instance.cargo, instance.tipo_usuario)
        PermissaoUsuario.objects.create(motorista=instance, **defaults)

# Criaçao modelo de filial
class Filial(models.Model):
    nome = models.CharField(max_length=100)
    cnpj = models.CharField(
        max_length=255, 
        blank=True, 
        null=True, 
        verbose_name="CNPJ(s) da Filial", 
        help_text="Informe um ou mais CNPJs separados por vírgula (ex: 14539546000120, 14539546000200). Usado para unificar manifestos recebidos via Webhook."
    )
    id_filial_tms = models.CharField(
        max_length=50, 
        blank=True, 
        null=True, 
        verbose_name="ID da Filial na ESL", 
        help_text="ID numérico da ESL Cloud (usado na Busca Manual)"
    )
    horario_rebusca_esl = models.TimeField(null=True, blank=True, verbose_name="Horário da Rebusca Automática (ESL)")
    operacao_ativa = models.BooleanField(
        default=True,
        null=True,
        blank=True,
        verbose_name="Operação Ativa no App",
        help_text="Se desmarcado, o webhook ignorará novos manifestos desta filial para evitar acúmulo de rotas não utilizadas."
    )
    
    # --- ENDEREÇO COMPLETO DA BASE/GALPÃO ---
    logradouro = models.CharField(max_length=255, blank=True, null=True, verbose_name="Logradouro")
    numero = models.CharField(max_length=20, blank=True, null=True, verbose_name="Número")
    complemento = models.CharField(max_length=100, blank=True, null=True, verbose_name="Complemento")
    bairro = models.CharField(max_length=100, blank=True, null=True, verbose_name="Bairro")
    cidade = models.CharField(max_length=100, blank=True, null=True, verbose_name="Cidade")
    uf = models.CharField(max_length=2, blank=True, null=True, verbose_name="UF")
    cep = models.CharField(max_length=9, blank=True, null=True, verbose_name="CEP")
    
    # --- GEOLOCALIZAÇÃO (Preenchida automaticamente pelo backend via CEP/Endereço) ---
    latitude = models.FloatField(null=True, blank=True, verbose_name="Latitude")
    longitude = models.FloatField(null=True, blank=True, verbose_name="Longitude")
    
    # WhatsApp — Informar a partir do DDD (ex: 21999999999). O sistema adiciona o 55 automaticamente.
    whatsapp_operacional = models.CharField(
        max_length=20, blank=True, null=True,
        verbose_name="WhatsApp Operacional",
        help_text="Número do WhatsApp do operacional da filial. Informe a partir do DDD (ex: 21999999999)."
    )
    whatsapp_sac = models.CharField(
        max_length=20, blank=True, null=True,
        verbose_name="WhatsApp SAC",
        help_text="Número do WhatsApp do SAC da filial. Informe a partir do DDD (ex: 21999999999)."
    )

    @property
    def whatsapp_operacional_completo(self):
        """Retorna o número com prefixo 55 para uso no link wa.me"""
        if self.whatsapp_operacional:
            import re
            nums = re.sub(r'\D', '', str(self.whatsapp_operacional))
            if nums:
                if nums.startswith('55') and len(nums) >= 12:
                    return nums
                return f"55{nums}"
        return None

    @property
    def endereco_completo(self):
        """Retorna o endereço formatado para exibição."""
        partes = [p for p in [self.logradouro, self.numero, self.bairro, self.cidade, self.uf] if p]
        return ', '.join(partes) if partes else None

    def save(self, *args, **kwargs):
        """
        Ao salvar, se o endereço foi preenchido/alterado e lat/lng estão vazios,
        tenta geocodificar automaticamente usando o geocoding.py existente.
        """
        # Detecta se deve tentar geocodificar (endereço presente mas sem coordenadas)
        tem_endereco = bool(self.cep or (self.logradouro and self.cidade))
        sem_coordenadas = not self.latitude or not self.longitude
        
        if tem_endereco and sem_coordenadas:
            try:
                from common.geocoding import buscar_lat_lng_endereco
                endereco_texto = self.endereco_completo
                lat, lng = buscar_lat_lng_endereco(cep=self.cep, endereco=endereco_texto)
                if lat and lng:
                    self.latitude = lat
                    self.longitude = lng
            except Exception:
                pass  # Nunca bloqueia o save por falha de geocodificação
        
        super().save(*args, **kwargs)

    def __str__(self):
        return self.nome

# --- NOVO: Pré-Cadastro para Equipe SAC ---
class PreCadastroSAC(models.Model):
    """
    Cadastra previamente os CPFs da equipe de SAC.
    Quando o CPF logar pela primeira vez no app/painel, a conta e o perfil (SAC) são criados automaticamente.
    """
    cpf = models.CharField(max_length=11, unique=True, verbose_name="CPF (Apenas números)")
    nome = models.CharField(max_length=255, verbose_name="Nome Completo")
    email = models.EmailField(verbose_name="E-mail", help_text="Obrigatório para o envio do link de convite.", default='', blank=True)
    filial = models.ForeignKey(
        'Filial',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sac_cadastrados',
        verbose_name="Filial Responsável"
    )
    is_gestor = models.BooleanField(default=False, verbose_name="Visão Global (Gestor)?")
    ativo = models.BooleanField(default=True, verbose_name="Cadastro Ativo?")
    
    def __str__(self):
        tag = "Gestor" if self.is_gestor else "SAC"
        return f"[{tag}] {self.nome} ({self.cpf})"
        
    class Meta:
        verbose_name = "Pré-Cadastro SAC"
        verbose_name_plural = "Pré-Cadastros SAC"

@receiver(post_save, sender=PreCadastroSAC)
def enviar_email_convite_sac(sender, instance, created, **kwargs):
    if instance.email:
        try:
            from django.core.mail import send_mail
            from django.template.loader import render_to_string
            from django.utils.html import strip_tags
            from django.conf import settings
            
            # TODO: We need a way to get the domain here, since request is not available in signals.
            # We will use settings.ALLOWED_HOSTS[0] or a default environment variable for now.
            import os
            host = os.getenv('ALLOWED_HOSTS', '127.0.0.1,localhost').split(',')[0]
            dominio = f"https://{host}" if host != '127.0.0.1' else "http://localhost:8000"

            context = {'nome': instance.nome, 'cpf': instance.cpf, 'dominio': dominio}
            html_message = render_to_string('emails/convite_sac.html', context)
            plain_message = strip_tags(html_message)
            
            send_mail(
                'Convite para Equipe - RXTrack',
                plain_message,
                settings.EMAIL_HOST_USER,
                [instance.email],
                html_message=html_message,
                fail_silently=False
            )
        except Exception as e:
            print(f"Erro ao enviar email de convite SAC: {e}")


# =====================================================
# Device Token — Login persistente para APK (Capacitor)
# =====================================================
class DeviceToken(models.Model):
    """
    Token de dispositivo para auto-login no APK.
    Salvo no SharedPreferences nativo do Android via @capacitor/preferences.
    Sobrevive ao app ser matado, celular reiniciado, etc.
    NÃO é usado pelo PWA (que funciona normal com sessão/cookies).
    """
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='device_tokens',
        verbose_name="Usuário"
    )
    token = models.CharField(max_length=64, unique=True, db_index=True, verbose_name="Token do Dispositivo")
    device_info = models.CharField(max_length=255, blank=True, default='APK Android', verbose_name="Info do Dispositivo")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")
    ultimo_uso = models.DateTimeField(auto_now=True, verbose_name="Último Uso")
    ativo = models.BooleanField(default=True, verbose_name="Ativo")

    class Meta:
        verbose_name = "Device Token"
        verbose_name_plural = "Device Tokens"

    def __str__(self):
        return f"Device {self.user.username} - {self.token[:8]}..."


# =====================================================
# Log de Notificações Push enviadas via Firebase FCM
# =====================================================
class NotificacaoPushLog(models.Model):
    """
    Registra o histórico de notificações push enviadas aos motoristas no APK.
    """
    TIPO_CHOICES = [
        ('SISTEMA', 'Aviso do Sistema'),
        ('LEMBRETE', 'Lembrete de Routine / GPS'),
        ('MANIFESTO', 'Atualização de Manifesto'),
        ('ALERTA', 'Alerta Operacional'),
        ('MANUAL', 'Disparo Manual Admin'),
    ]

    motorista = models.ForeignKey(
        Motorista,
        on_delete=models.CASCADE,
        related_name='logs_notificacoes_push',
        verbose_name="Motorista"
    )
    titulo = models.CharField(max_length=255, verbose_name="Título")
    mensagem = models.TextField(verbose_name="Mensagem")
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default='SISTEMA', verbose_name="Tipo")
    dados_payload = models.JSONField(blank=True, null=True, verbose_name="Dados Extras (JSON)")
    
    sucesso = models.BooleanField(default=False, verbose_name="Enviado com Sucesso")
    response_message_id = models.CharField(max_length=255, blank=True, null=True, verbose_name="ID Resposta Firebase")
    erro_detalhes = models.TextField(blank=True, null=True, verbose_name="Detalhes de Erro")
    
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado / Enviado em")

    class Meta:
        verbose_name = "Log de Notificação Push"
        verbose_name_plural = "Logs de Notificações Push"
        ordering = ['-criado_em']

    def __str__(self):
        return f"[{self.tipo}] {self.motorista.nome_completo} - {self.titulo} ({'✅' if self.sucesso else '❌'})"