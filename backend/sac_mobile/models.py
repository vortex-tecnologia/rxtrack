from django.db import models
from django.contrib.auth.models import User

class HistoricoBaixaSAC(models.Model):
    STATUS_CHOICES = [
        ('PENDENTE', 'Pendente'),
        ('SUCESSO', 'Sucesso (TMS)'),
        ('ERRO', 'Erro (TMS)')
    ]

    # Vínculo com Usuário
    usuario = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Operador do SAC")
    
    # Identificadores da Nota/Minuta
    chave_acesso = models.CharField(max_length=44, blank=True, null=True, verbose_name="Chave de Acesso", db_index=True)
    freight_id = models.CharField(max_length=50, blank=True, null=True, verbose_name="ID do Frete (Minuta)")
    numero_nota = models.CharField(max_length=50, blank=True, null=True, verbose_name="Número da Nota / Minuta")
    
    # Dados da Ocorrência
    ocorrencia_codigo = models.CharField(max_length=10, blank=True, null=True, verbose_name="Cód. Ocorrência")
    somente_comprovante = models.BooleanField(default=False, verbose_name="Somente Comprovante?")
    observacao = models.TextField(blank=True, null=True, verbose_name="Observação")
    
    # Fotos (Original e IA)
    url_foto_original = models.URLField(max_length=1000, blank=True, null=True, verbose_name="Foto Original")
    url_foto_recortada = models.URLField(max_length=1000, blank=True, null=True, verbose_name="Foto Recortada (IA)")
    
    # Controle IA
    ia_yolo_status = models.BooleanField(default=False, verbose_name="Processado na IA?")
    
    # Integração TMS
    status_tms = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDENTE', verbose_name="Status Integração")
    log_erro_tms = models.TextField(blank=True, null=True, verbose_name="Log de Erro (TMS)")
    
    # Data de Criação
    data_criacao = models.DateTimeField(auto_now_add=True, verbose_name="Data da Baixa")

    class Meta:
        verbose_name = "Histórico de Baixa (SAC)"
        verbose_name_plural = "Histórico de Baixas (SAC)"
        ordering = ['-data_criacao']

    def __str__(self):
        ident = self.chave_acesso if self.chave_acesso else f"Frete: {self.freight_id}"
        return f"Baixa SAC - {ident}"
