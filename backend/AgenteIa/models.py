from django.db import models
import os

class ProcessamentoCanhoto(models.Model):
    # Relaciona com sua tabela de fotos/entregas existente
    # Supondo que sua model principal se chame 'FotoEntrega'
    foto_original = models.OneToOneField(
        'manifesto.BaixaNF', 
        on_delete=models.CASCADE,
        related_name='processamento_ia'
    )
    
    # Logs do YOLO
    data_processamento = models.DateTimeField(auto_now_add=True)
    confianca_yolo = models.FloatField(null=True, blank=True) # Nível de certeza (0.0 a 1.0)
    teve_sucesso = models.BooleanField(default=False)
    
    # Controle de Treinamento (O que você pediu)
    foi_para_treino = models.BooleanField(
        default=False, 
        help_text="Marcar se esta imagem de falha foi usada para melhorar o modelo"
    )
    observacao_erro = models.TextField(blank=True, null=True)

    def __str__(self):
        status = "Sucesso" if self.teve_sucesso else "Falha"
        return f"Processamento {self.id} - {status} ({self.foto_original.id})"

    class Meta:
        verbose_name = "Processamento de IA"
        verbose_name_plural = "Processamentos de IA"