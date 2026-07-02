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
    id_filial_tms = models.CharField(max_length=50, blank=True, null=True)

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
                'Convite para Equipe - QuickTrack',
                plain_message,
                settings.EMAIL_HOST_USER,
                [instance.email],
                html_message=html_message,
                fail_silently=False
            )
        except Exception as e:
            print(f"Erro ao enviar email de convite SAC: {e}")