from django.db import models
from django.utils import timezone
from datetime import date


class WhatsAppProvedor(models.Model):
    """
    Cada registro = 1 provedor de envio de mensagens WhatsApp.
    O admin pode ter vários provedores (Evolution API, Z-API, etc.) e
    desativar/ativar rapidamente caso um deles caia.
    """
    PROVEDOR_CHOICES = [
        ('evolution_api', 'Evolution API'),
        ('z_api', 'Z-API'),
        ('wppconnect', 'WPPConnect'),
        ('codechat', 'CodeChat'),
    ]

    nome = models.CharField(
        max_length=30, choices=PROVEDOR_CHOICES, unique=True,
        verbose_name="Provedor"
    )
    url_base = models.URLField(
        verbose_name="URL do Servidor",
        help_text="URL base do servidor (ex: https://evo.seudominio.com.br)"
    )
    api_key = models.CharField(
        max_length=200, verbose_name="API Key / Token Global",
        help_text="Token de autenticação global do servidor"
    )
    ativo = models.BooleanField(
        default=True, verbose_name="✅ Ativo",
        help_text="Desmarque para desativar este provedor imediatamente. O sistema passará a usar o próximo na fila."
    )
    prioridade = models.IntegerField(
        default=0, verbose_name="Prioridade",
        help_text="Menor número = maior prioridade. Se o provedor principal cair, o próximo assume."
    )

    class Meta:
        verbose_name = "Provedor WhatsApp"
        verbose_name_plural = "Provedores WhatsApp"
        ordering = ['prioridade']

    def __str__(self):
        status = "✅" if self.ativo else "❌"
        return f"{status} {self.get_nome_display()} (Prioridade: {self.prioridade})"


class WhatsAppInstancia(models.Model):
    """
    Cada filial tem sua própria instância (número WhatsApp) vinculada a um provedor.
    Ex: Filial SP usa instância 'filial_sp' na Evolution API com número 5511999...
    """
    filial = models.OneToOneField(
        'usuarios.Filial', on_delete=models.CASCADE,
        related_name='instancia_whatsapp',
        verbose_name="Filial"
    )
    provedor = models.ForeignKey(
        WhatsAppProvedor, on_delete=models.CASCADE,
        related_name='instancias',
        verbose_name="Provedor de Envio"
    )
    nome_instancia = models.CharField(
        max_length=100, verbose_name="Nome da Instância",
        help_text="Nome cadastrado na Evolution/Z-API (ex: filial_sp, bot_rj)"
    )
    numero_whatsapp = models.CharField(
        max_length=20, verbose_name="Número WhatsApp",
        help_text="Formato internacional: 5511999999999"
    )
    ativo = models.BooleanField(
        default=True, verbose_name="✅ Instância Ativa",
        help_text="Desmarque para pausar envios desta filial"
    )

    class Meta:
        verbose_name = "Instância WhatsApp (Filial)"
        verbose_name_plural = "Instâncias WhatsApp (Filiais)"

    def __str__(self):
        status = "✅" if self.ativo else "⏸️"
        return f"{status} {self.filial.nome} — {self.numero_whatsapp} ({self.provedor.get_nome_display()})"


class ManifestoBotCache(models.Model):
    """
    Armazena o JSON retornado pelo TMS para minimizar requisições.
    Um registro por filial por dia. Atualizado apenas nas rodadas com busca TMS (11h, 14h, 16h).
    Nas rodadas intermediárias (12h, 15h), o sistema relê este cache sem chamar o TMS.
    """
    filial = models.ForeignKey(
        'usuarios.Filial', on_delete=models.CASCADE,
        related_name='bot_cache'
    )
    data_referencia = models.DateField(verbose_name="Data de Referência")
    payload_tms = models.JSONField(
        default=list, verbose_name="JSON Bruto do TMS",
        help_text="Resposta completa da API do TMS para auditoria"
    )
    manifestos_encontrados = models.JSONField(
        default=list, verbose_name="Manifestos Encontrados",
        help_text="Lista de números de manifesto retornados pelo TMS"
    )
    total_manifestos = models.IntegerField(default=0, verbose_name="Total de Manifestos")
    atualizado_em = models.DateTimeField(auto_now=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Cache de Manifestos (Bot)"
        verbose_name_plural = "Cache de Manifestos (Bot)"
        unique_together = ('filial', 'data_referencia')

    def __str__(self):
        return f"Cache {self.filial.nome} — {self.data_referencia} ({self.total_manifestos} MFTs)"


class NotificacaoManifestoLog(models.Model):
    """
    Log de cada mensagem enviada pelo bot. Serve para:
    1. Auditoria (quem recebeu, quando, qual mensagem)
    2. Controle de reenvio (não enviar 2x na mesma rodada)
    3. Métricas (taxa de sucesso de envio)
    """
    TIPO_CHOICES = [
        ('ATIVACAO', 'Lembrete de Ativação'),
        ('PENDENCIA', 'Manifesto Anterior Pendente'),
    ]
    STATUS_CHOICES = [
        ('ENVIADO', 'Enviado com Sucesso'),
        ('ERRO', 'Erro no Envio'),
        ('SEM_TELEFONE', 'Motorista Sem Telefone'),
    ]

    motorista = models.ForeignKey(
        'usuarios.Motorista', on_delete=models.CASCADE,
        related_name='notificacoes_bot'
    )
    manifesto = models.ForeignKey(
        'manifesto.Manifesto', on_delete=models.CASCADE,
        related_name='notificacoes_bot'
    )
    filial = models.ForeignKey(
        'usuarios.Filial', on_delete=models.CASCADE,
        related_name='notificacoes_bot'
    )
    data_referencia = models.DateField(
        default=date.today, verbose_name="Data de Referência"
    )
    rodada = models.IntegerField(
        verbose_name="Rodada do Dia",
        help_text="1=11h, 2=12h, 3=14h, 4=15h, 5=16h"
    )
    tipo_mensagem = models.CharField(max_length=20, choices=TIPO_CHOICES)
    mensagem_enviada = models.TextField(verbose_name="Mensagem Enviada")
    provedor_usado = models.CharField(max_length=30, verbose_name="Provedor Utilizado")
    instancia_usada = models.CharField(max_length=100, verbose_name="Instância Utilizada")
    numero_destino = models.CharField(max_length=20, verbose_name="Número de Destino")

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ENVIADO')
    erro_detalhe = models.TextField(null=True, blank=True, verbose_name="Detalhe do Erro")
    resposta_api = models.JSONField(null=True, blank=True, verbose_name="Resposta da API")

    enviado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Log de Notificação (Bot)"
        verbose_name_plural = "Logs de Notificações (Bot)"
        ordering = ['-enviado_em']
        # Garante: 1 mensagem por motorista, por manifesto, por rodada, por dia
        unique_together = ('motorista', 'manifesto', 'rodada', 'data_referencia')

    def __str__(self):
        return f"R{self.rodada} — {self.motorista.nome_completo} — MFT #{self.manifesto.numero_manifesto} ({self.status})"
