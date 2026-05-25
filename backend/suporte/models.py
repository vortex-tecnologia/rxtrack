from django.db import models
from django.contrib.auth.models import User
from usuarios.models import Motorista, Filial
from manifesto.models import NotaFiscal

class TicketSuporte(models.Model):
    STATUS_CHOICES = [
        ('CANAL_ABERTO', 'Aberto (Aguardando Atendimento)'),
        ('EM_ATENDIMENTO', 'Em Atendimento'),
        ('RESOLVIDO', 'Resolvido'),
        ('FECHADO', 'Fechado'),
    ]

    CATEGORIA_CHOICES = [
        ('DUVIDA_NF', 'Dúvida sobre Nota Fiscal'),
        ('PROBLEMA_ENDERECO', 'Problema no Endereço / Telefone Errado'),
        ('PROBLEMA_APP', 'Problema no Aplicativo'),
        ('AVARIA_CARGA', 'Avaria na Carga / Acidente'),
        ('AGUARDE_RETORNO', 'Preciso de liberação / Aguardo retorno'),
        ('OUTROS', 'Outro Motivo')
    ]

    motorista = models.ForeignKey(Motorista, on_delete=models.CASCADE, related_name='tickets_suporte', verbose_name="Motorista")
    filial = models.ForeignKey(Filial, on_delete=models.CASCADE, related_name='tickets_suporte', verbose_name="Filial")
    
    # Optional assigned agent
    atendente = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='tickets_atendidos', verbose_name="Atendente (SAC)")
    
    # Optional Nota Fiscal
    nota_fiscal = models.ForeignKey(NotaFiscal, on_delete=models.SET_NULL, null=True, blank=True, related_name='tickets_suporte', verbose_name="Nota Fiscal Relacionada")
    
    categoria = models.CharField(max_length=50, choices=CATEGORIA_CHOICES, verbose_name="Categoria do Chamado")
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='CANAL_ABERTO', verbose_name="Status")
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Criado Em")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Última Atualização")
    closed_at = models.DateTimeField(null=True, blank=True, verbose_name="Fechado Em")

    def __str__(self):
        return f"Ticket #{self.id} - {self.get_categoria_display()} ({self.get_status_display()})"

    class Meta:
        verbose_name = "Ticket de Suporte"
        verbose_name_plural = "Tickets de Suporte"
        ordering = ['-created_at']


class MensagemSuporte(models.Model):
    TIPO_CHOICES = [
        ('TEXTO', 'Texto'),
        ('AUDIO', 'Áudio'),
        ('IMAGEM', 'Imagem'),
        ('VIDEO', 'Vídeo'),
        ('SISTEMA', 'Mensagem do Sistema')
    ]

    ticket = models.ForeignKey(TicketSuporte, on_delete=models.CASCADE, related_name='mensagens', verbose_name="Ticket")
    
    # Identify sender: Either Motorista or Atendente or System
    enviado_por_motorista = models.BooleanField(default=True, verbose_name="Enviado pelo Motorista?")
    
    # Se enviado por atendente, guarda quem foi
    atendente = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='mensagens_enviadas', verbose_name="Enviado por (Atendente)")
    
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default='TEXTO', verbose_name="Tipo de Mensagem")
    texto = models.TextField(blank=True, null=True, verbose_name="Conteúdo em Texto")
    
    # Arquivos anexos
    arquivo = models.FileField(upload_to='suporte/anexos/', blank=True, null=True, verbose_name="Arquivo Anexo")
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Enviada Em")

    # Flag for read receipts
    lida = models.BooleanField(default=False, verbose_name="Lida?")

    def __str__(self):
        return f"Msg #{self.id} no Ticket #{self.ticket.id}"

    class Meta:
        verbose_name = "Mensagem do Suporte"
        verbose_name_plural = "Mensagens do Suporte"
        ordering = ['created_at']
