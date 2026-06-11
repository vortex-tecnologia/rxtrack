# Copyright (c) 2026 Luiz Gustavo. Todos os direitos reservados. Licença Proprietária.
# manifestos/models.py

from django.db import models
from django.contrib.auth.models import User
from usuarios.models import Motorista, Filial
from django.utils import timezone
from django.utils.html import format_html


# WEBHOOK EVENTO MANIFESTO - ARMAZENA TODOS OS POSTS RECEBIDOS PELO WEBHOOK
class WebhookEventoManifestoESL(models.Model):
    origem = models.CharField(max_length=50, default="ESL")
    tipo = models.CharField(max_length=50)
    numero_manifesto = models.CharField(max_length=50, null=True, blank=True)
    payload = models.JSONField()
    status = models.CharField(
        max_length=20,
        default="PENDENTE"
    )
    erro = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

class WebhookTokenControl(models.Model):
    """
    Controla o uso mensal de tokens para o Webhook comercial.
    Permite bloqueio manual e monitoramento de limites (soft limit).
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='webhook_control')
    limite_mensal = models.IntegerField(default=5000, verbose_name="Limite do Plano")
    total_mes_atual = models.IntegerField(default=0, verbose_name="Consumido no Mês")
    mes_referencia = models.DateField(default=timezone.now, verbose_name="Mês de Referência")
    ativo = models.BooleanField(default=True, verbose_name="Token Ativo")
    data_atualizacao = models.DateTimeField(auto_now=True)

    def reset_if_new_month(self):
        """Zera o contador se o mês mudou."""
        agora = timezone.now().date().replace(day=1)
        if self.mes_referencia != agora:
            self.total_mes_atual = 0
            self.mes_referencia = agora
            self.save()

    def __str__(self):
        return f"Controle: {self.user.username} - {self.total_mes_atual}/{self.limite_mensal}"

    class Meta:
        verbose_name = "Controle de Token Webhook"
        verbose_name_plural = "Controle de Tokens Webhook"

class ManifestoBuscaLog(models.Model):
    STATUS_CHOICES = (
        ('AGUARDANDO', 'Aguardando'),
        ('PRONTO_PREVIEW', 'Pronto para Preview'),
        ('PROCESSADO', 'Processado'),
        ('ERRO', 'Erro'),
    )

    numero_manifesto = models.CharField(max_length=50)
    motorista = models.ForeignKey(Motorista, on_delete=models.CASCADE)

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='AGUARDANDO'
    )

    mensagem_erro = models.TextField(blank=True, null=True)

    # ✅ AGORA CORRETO
    payload = models.JSONField(blank=True, null=True)
    quantidade_notas = models.IntegerField(default=0, verbose_name="Quantidade de Notas")
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Busca {self.numero_manifesto} - {self.motorista.nome_completo} - {self.status}"

    class Meta:
        verbose_name = "Busca de Manifesto"
        verbose_name_plural = "Buscas de Manifestos"
        unique_together = ('numero_manifesto', 'motorista')

# 1. Códigos de Ocorrência do TMS
class Ocorrencia(models.Model):
    """
    Tabela para mapear todos os códigos de retorno (Entrega, Coleta, Problema) exigidos pelo TMS.
    """
    codigo_tms = models.CharField(max_length=10, unique=True, verbose_name="Código TMS") 
    descricao = models.CharField(max_length=255)
    
    TIPO_CHOICES = [
        ('ENTREGA', 'Entrega/Coleta (Sucesso)'),
        ('PROBLEMA', 'Problema (Rejeição/Não Realizada)'),
    ]
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES, default='PROBLEMA')
    is_coleta = models.BooleanField(default=False, verbose_name="Exibir em Coletas", help_text="Marque se esta ocorrência deve aparecer nas opções do aplicativo para recusa de coletas.")

    def __str__(self):
        return f"[{self.codigo_tms}] {self.descricao}"
    
    class Meta:
        verbose_name = "Código de Ocorrência"
        verbose_name_plural = "Códigos de Ocorrências"


# 2. Manifesto de Carga
class Manifesto(models.Model):
    STATUS_CHOICES = [
        ('AGUARDANDO', 'Aguardando'),
        ('EM_TRANSPORTE', 'Em Transporte'),
        ('FINALIZADO', 'Finalizado'),
        ('CANCELADO', 'Cancelado'),
    ]

    numero_manifesto = models.CharField(
        max_length=50,
        unique=True,
        verbose_name="Número do Manifesto"
    )
    manifesto_id_tms = models.CharField(max_length=50, null=True, blank=True)

    motorista = models.ForeignKey(
        Motorista,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='manifestos',
        verbose_name="Motorista"
    )
    
    # NOVAS: Informações de Monitoramento por Manifesto (Específicas da Viagem)
    ultima_bateria = models.IntegerField(null=True, blank=True, verbose_name="Última Bateria (%)")
    ultimo_acesso = models.DateTimeField(null=True, blank=True, verbose_name="Último Acesso")
    ultima_rede = models.CharField(max_length=20, null=True, blank=True, verbose_name="Tipo de Rede")
    ultima_lat = models.FloatField(null=True, blank=True, verbose_name="Última Latitude")
    ultima_lng = models.FloatField(null=True, blank=True, verbose_name="Última Longitude")

    filial = models.ForeignKey(
        Filial,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='manifestos',
        verbose_name="Filial"
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='EM_TRANSPORTE'
    )
    qtd_transferencia = models.IntegerField(default=0, verbose_name="Qtd Transferência",null=True, blank=True)
    qtd_despacho = models.IntegerField(default=0, verbose_name="Qtd Despacho", null=True, blank=True)
    qtd_entrega = models.IntegerField(default=0, verbose_name="Qtd Entrega", null=True, blank=True)
    qtd_retirada = models.IntegerField(default=0, verbose_name="Qtd Retirada", null=True, blank=True)

    km_inicial = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    km_final = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    finalizado = models.BooleanField(default=False)

    data_criacao = models.DateTimeField(auto_now_add=True)
    data_finalizacao = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Manifesto {self.numero_manifesto}"

    class Meta:
        verbose_name = "Manifesto"
        verbose_name_plural = "Manifestos"
        constraints = [
            models.UniqueConstraint(
                fields=['motorista'],
                condition=models.Q(status='EM_TRANSPORTE'),
                name='um_manifesto_em_transporte_por_motorista'
            )
        ]

# 3. Notas Fiscais (Itens do Manifesto)
class NotaFiscal(models.Model):
    TIPO_OPERACAO_CHOICES = [
        ('TRANSFERENCIA', 'Transferência'),
        ('DESPACHO', 'Despacho'),
        ('ENTREGA', 'Entrega'),
        ('COLETA', 'Coleta'),
        ('RETIRADA', 'Retirada'),
        ('OUTROS', 'Outros'),
    ]
    """
    Representa uma NF-e dentro de um manifesto. A NF-e pode se repetir em outros manifestos.
    """
    manifesto = models.ForeignKey(Manifesto, on_delete=models.CASCADE, related_name='notas_fiscais')
    freight_id_tms = models.CharField(max_length=50, null=True, blank=True)
    
    # Chave de acesso e Número não são únicos globalmente, mas são únicos DENTRO DESTE MANIFESTO
    chave_acesso = models.CharField(max_length=44, null=True, blank=True, verbose_name="Chave de Acesso") 
    numero_nota = models.CharField(max_length=20, verbose_name="Número NF")
    
    destinatario = models.CharField(max_length=255, verbose_name="Destinatário")
    endereco_entrega = models.CharField(max_length=255, verbose_name="Endereço de Entrega")
    tipo_operacao = models.CharField(
        max_length=20, 
        choices=TIPO_OPERACAO_CHOICES, 
        default='ENTREGA', null=True, blank=True
    )
    
    # Campo para Coletas
    numero_coleta = models.CharField(max_length=50, null=True, blank=True, verbose_name="Número da Coleta")
    
    # Campos para CT-e (Usado quando não há NF-e ou para Minutas)
    numero_cte = models.CharField(max_length=50, null=True, blank=True, verbose_name="Número do CT-e")
    chave_cte = models.CharField(max_length=44, null=True, blank=True, verbose_name="Chave do CT-e")
    STATUS_CHOICES = [
        ('PENDENTE', 'Pendente'),
        ('BAIXADA', 'Baixada/Entregue'),
        ('OCORRENCIA', 'Ocorrência Registrada'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDENTE')

    def __str__(self):
        return f"NF {self.numero_nota} ({self.manifesto.numero_manifesto})"
    
    class Meta:
        verbose_name = "Nota Fiscal"
        verbose_name_plural = "Notas Fiscais"
        # RESTRIÇÃO CHAVE: Garante que a NF-e não seja duplicada no mesmo manifesto
        indexes = [
            models.Index(fields=['chave_acesso']),
            models.Index(fields=['numero_nota']),
        ]

    # Helper para evitar N+1 no template ao buscar última baixa
    @property
    def ultima_baixa(self):
        if hasattr(self, '_prefetched_ultima_baixa'):
            return self._prefetched_ultima_baixa[0] if self._prefetched_ultima_baixa else None
        return self.baixa_info.all().last()


# 4. Histórico de Ocorrências (Rastreamento)
class HistoricoOcorrencia(models.Model):
    """
    Armazena CADA evento de rastreamento recebido do Data Export para uma Nota Fiscal.
    Usado para determinar a última ocorrência (data mais recente).
    """
    nota_fiscal = models.ForeignKey(NotaFiscal, on_delete=models.CASCADE, related_name='historico')
    
    codigo_tms = models.CharField(max_length=10, verbose_name="Código Ocorrência TMS")
    data_ocorrencia = models.DateTimeField(null=True, blank=True)
    
    comentarios = models.TextField(null=True, blank=True)
    manifesto_evento = models.CharField(max_length=50, verbose_name="Cód. do Manifesto do Evento")

    def __str__(self):
        return f"NF {self.nota_fiscal.numero_nota}: Código {self.codigo_tms} em {self.data_ocorrencia}"

    class Meta:
        verbose_name = "Histórico de Ocorrência"
        verbose_name_plural = "Históricos de Ocorrências"
        # Garante a unicidade do evento (NF + Cód + Data)
        unique_together = ('nota_fiscal', 'codigo_tms', 'data_ocorrencia') 
        indexes = [models.Index(fields=['data_ocorrencia'])]


# 5. Registro de Baixa (Comprovante final de entrega ou ocorrência)
class BaixaNF(models.Model):
    """
    Registra a foto do canhoto ou o código da ocorrência FINAL enviado pelo motorista.
    """
    nota_fiscal = models.ForeignKey(NotaFiscal, on_delete=models.CASCADE, related_name='baixa_info')
    
    TIPO_CHOICES = [
        ('ENTREGA', 'Entrega/Coleta'),
        ('OCORRENCIA', 'Ocorrência'),
    ]
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES)
    
    comprovante_foto = models.ImageField(upload_to='comprovantes/', null=True, blank=True)
    comprovante_foto_url = models.CharField(max_length=500, null=True, blank=True)
    comprovante_original_url = models.CharField(max_length=500, null=True, blank=True)
    
    # Vincula o código de ocorrência do TMS (o que o motorista escolheu no app)
    ocorrencia = models.ForeignKey(Ocorrencia, on_delete=models.SET_NULL, null=True, blank=True)
  
    recebedor = models.CharField(max_length=100, null=True, blank=True)
    documento_recebedor = models.CharField(max_length=20, null=True, blank=True)
    observacao = models.TextField(blank=True, null=True)
    
    # NOVO: Autor da baixa (usado especialmente quando um SAC altera ou registra a nota)
    autor_baixa = models.ForeignKey('usuarios.Motorista', null=True, blank=True, on_delete=models.SET_NULL, related_name='baixas_realizadas', verbose_name="Autor da Baixa")
    
    data_baixa = models.DateTimeField(default=timezone.now)
    
    MOTIVO_CHOICES = [
        ('APP_ERROR', 'Erro de Aplicativo/Hardware'),
        ('MOTORISTA_DESLEIXO', 'Não Finalizado pelo Motorista (Penalidade)'),
        ('OPERACAO_NORMAL', 'Operação Normal (Motorista)'),
    ]
    motivo_baixa = models.CharField(max_length=50, choices=MOTIVO_CHOICES, default='OPERACAO_NORMAL', verbose_name="Motivo da Baixa (Auditoria)")
    
    processado_tms = models.BooleanField(default=False, verbose_name="Integrado com ESL")
    data_integracao = models.DateTimeField(null=True, blank=True)
    log_erro_tms = models.TextField(null=True, blank=True, verbose_name="Log de Erro ESL")
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    integrado_tms = models.BooleanField(default=False, null=True, blank=True, verbose_name="Integrado ESL")
    payload_enviado = models.JSONField(null=True, blank=True, verbose_name="JSON enviado para ESL")
    
    # Campo de Status da IA
    ia_yolo_status = models.BooleanField(default=False, verbose_name="YOLO: Canhoto Detectado")
    ia_ocr_status = models.BooleanField(default=False, verbose_name="OCR: Leitura Realizada")

    def save(self, *args, **kwargs):
        # Se temos uma URL de foto mas o backup original está vazio, 
        # significa que é o registro inicial. Salvamos o backup.
        if self.comprovante_foto_url and not self.comprovante_original_url:
            self.comprovante_original_url = self.comprovante_foto_url
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Baixa de {self.nota_fiscal.numero_nota} ({self.tipo})"
    
    class Meta:
        verbose_name = "Nota Fiscal Baixada"
        verbose_name_plural = "Notas Fiscais Baixadas"