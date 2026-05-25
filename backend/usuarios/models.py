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
    
    nome_completo = models.CharField(max_length=255, verbose_name="Nome Completo")
    cnh_numero = models.CharField(max_length=20, blank=True, null=True, verbose_name="Número da CNH")
    
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

    # Cargo define o nível de permissão DENTRO do sistema (separado de tipo_usuario)
    CARGO_CHOICES = [
        ('MEMBRO', 'Membro'),
        ('GERENTE', 'Gerente'),
        ('GESTOR', 'Gestor'),
    ]
    cargo = models.CharField(
        max_length=10,
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

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
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