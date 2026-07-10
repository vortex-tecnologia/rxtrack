from django.db import models
from django.contrib.auth.models import User


class LogExclusaoOcorrencia(models.Model):
    """
    Registra cada exclusão de ocorrência feita pelo painel operacional.
    Mantém um snapshot completo dos dados deletados para fins de auditoria.
    """
    usuario = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        verbose_name="Operador que excluiu"
    )
    usuario_nome = models.CharField(
        max_length=255, blank=True,
        verbose_name="Nome do Operador",
        help_text="Salvo como texto para manter registro mesmo se o usuário for excluído"
    )

    # Dados da nota afetada
    nota_fiscal_id = models.IntegerField(verbose_name="ID da Nota Fiscal")
    nota_fiscal_numero = models.CharField(max_length=20, verbose_name="Número NF")
    chave_acesso = models.CharField(max_length=44, blank=True, null=True, verbose_name="Chave de Acesso")
    manifesto_numero = models.CharField(max_length=50, verbose_name="Nº Manifesto")
    motorista_nome = models.CharField(max_length=255, blank=True, verbose_name="Motorista")

    # Dados da ocorrência deletada
    ocorrencia_codigo = models.CharField(max_length=30, blank=True, verbose_name="Código Ocorrência TMS")
    ocorrencia_descricao = models.CharField(max_length=255, blank=True, verbose_name="Descrição Ocorrência")
    tipo_baixa = models.CharField(max_length=20, blank=True, verbose_name="Tipo da Baixa")
    estava_integrado_tms = models.BooleanField(default=False, verbose_name="Estava integrado no TMS?")

    # Motivo informado pelo operador
    motivo_exclusao = models.TextField(verbose_name="Motivo da Exclusão")

    # Snapshot completo para auditoria
    dados_baixa_json = models.JSONField(
        null=True, blank=True,
        verbose_name="Dados Completos da Baixa (Backup)",
        help_text="JSON com todos os campos do registro de BaixaNF antes da exclusão"
    )

    data_exclusao = models.DateTimeField(auto_now_add=True, verbose_name="Data/Hora da Exclusão")

    def __str__(self):
        return f"Exclusão NF {self.nota_fiscal_numero} por {self.usuario_nome} em {self.data_exclusao}"

    class Meta:
        verbose_name = "Log de Exclusão de Ocorrência"
        verbose_name_plural = "Logs de Exclusão de Ocorrências"
        ordering = ['-data_exclusao']
