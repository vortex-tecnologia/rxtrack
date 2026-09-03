# Copyright (c) 2026 Luiz Gustavo. Todos os direitos reservados. Licença Proprietária.
# financeiro/models.py

from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class ConfiguracaoFinanceiro(models.Model):
    """
    Singleton de configuração financeira por tenant.
    Define quais ocorrências contam como pagamento para entregas e coletas.
    """
    # Ocorrências que, quando presentes na baixa, contam como "entrega paga"
    # (motorista foi ao local, independente de ter entregue ou não)
    ocorrencias_pagamento_entrega = models.ManyToManyField(
        'manifesto.Ocorrencia',
        blank=True,
        related_name='config_pagamento_entrega',
        verbose_name="Ocorrências que contam como Entrega Paga",
        help_text="Selecione os códigos de ocorrência onde o motorista compareceu ao local e deve ser remunerado pela entrega."
    )
    
    # Ocorrências que contam como "coleta paga"
    ocorrencias_pagamento_coleta = models.ManyToManyField(
        'manifesto.Ocorrencia',
        blank=True,
        related_name='config_pagamento_coleta',
        verbose_name="Ocorrências que contam como Coleta Paga",
        help_text="Selecione os códigos de ocorrência onde o motorista compareceu ao local e deve ser remunerado pela coleta."
    )
    
    atualizado_em = models.DateTimeField(auto_now=True)
    atualizado_por = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name="Última alteração por"
    )

    class Meta:
        verbose_name = "Configuração Financeira"
        verbose_name_plural = "Configuração Financeira"

    def __str__(self):
        return "Configuração Financeira"

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class ClienteBasePagadora(models.Model):
    """
    Mapeamento de Clientes (Pagadores/Remetentes de frete ou solicitantes de coleta)
    para a Filial Responsável (Base Pagadora).
    Exemplo: Cliente 'UNILEVER' -> Filial 'QUICK SAO PAULO (SP)'.
    Se um agregado do Rio fizer entrega/coleta desse cliente, o custo é atribuído a SP.
    """
    nome = models.CharField(max_length=255, unique=True, verbose_name="Nome do Cliente / Pagador")
    documento = models.CharField(max_length=50, blank=True, null=True, verbose_name="CNPJ / CPF")
    filial_responsavel = models.ForeignKey(
        'usuarios.Filial',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='clientes_financeiro',
        verbose_name="Filial Pagadora Responsável"
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Cliente / Base Pagadora"
        verbose_name_plural = "Clientes / Bases Pagadoras"
        ordering = ['nome']

    def __str__(self):
        filial_nome = self.filial_responsavel.nome if self.filial_responsavel else "Pendente de Filial"
        return f"{self.nome} -> {filial_nome}"


class TarifaAgregado(models.Model):
    """
    Tabela de valores/tarifas por filial de operação.
    O responsável financeiro define os preços praticados em cada base.
    """
    filial = models.ForeignKey(
        'usuarios.Filial',
        on_delete=models.CASCADE,
        related_name='tarifas_agregado',
        verbose_name="Filial / Base"
    )
    valor_diaria = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        verbose_name="Valor da Diária (R$)",
        help_text="Valor fixo por dia rodado pelo motorista agregado."
    )
    valor_por_entrega = models.DecimalField(
        max_digits=10, decimal_places=2, default=5.00,
        verbose_name="Valor por Entrega (R$)",
        help_text="Valor pago por cada nota fiscal entregue com sucesso."
    )
    valor_por_coleta = models.DecimalField(
        max_digits=10, decimal_places=2, default=10.00,
        verbose_name="Valor por Coleta (R$)",
        help_text="Valor pago por cada coleta válida realizada com sucesso."
    )
    vigencia_inicio = models.DateField(
        default=timezone.now,
        verbose_name="Vigência a partir de",
        help_text="Data a partir da qual essa tarifa passa a valer."
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    criado_por = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name="Criado por"
    )

    class Meta:
        verbose_name = "Tarifa de Agregado"
        verbose_name_plural = "Tarifas de Agregados"
        ordering = ['-vigencia_inicio', 'filial__nome']

    def __str__(self):
        return f"Tarifa {self.filial.nome} - Diária R${self.valor_diaria} | Entrega R${self.valor_por_entrega} | Coleta R${self.valor_por_coleta}"


class FechamentoAgregado(models.Model):
    """
    Representa um período de fechamento/faturamento dos agregados.
    O responsável define o intervalo de datas e o sistema gera as linhas automaticamente.
    """
    STATUS_CHOICES = [
        ('ABERTO', 'Aberto'),
        ('FECHADO', 'Fechado'),
        ('PAGO', 'Pago'),
    ]

    periodo_inicio = models.DateField(verbose_name="Início do Período")
    periodo_fim = models.DateField(verbose_name="Fim do Período")
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default='ABERTO',
        verbose_name="Status"
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    criado_por = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='fechamentos_criados',
        verbose_name="Criado por"
    )
    finalizado_em = models.DateTimeField(null=True, blank=True)
    finalizado_por = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='fechamentos_finalizados',
        verbose_name="Finalizado por"
    )

    class Meta:
        verbose_name = "Fechamento de Agregado"
        verbose_name_plural = "Fechamentos de Agregados"
        ordering = ['-periodo_inicio']

    def __str__(self):
        return f"Fechamento {self.periodo_inicio.strftime('%d/%m/%Y')} a {self.periodo_fim.strftime('%d/%m/%Y')} ({self.get_status_display()})"


class LinhaFechamento(models.Model):
    """
    Cada linha = 1 manifesto de 1 motorista agregado dentro do período de fechamento.
    Equivalente a uma linha na aba individual do motorista na planilha Excel.
    """
    fechamento = models.ForeignKey(
        FechamentoAgregado,
        on_delete=models.CASCADE,
        related_name='linhas',
        verbose_name="Fechamento"
    )
    motorista = models.ForeignKey(
        'usuarios.Motorista',
        on_delete=models.CASCADE,
        related_name='linhas_fechamento',
        verbose_name="Motorista"
    )
    manifesto = models.ForeignKey(
        'manifesto.Manifesto',
        on_delete=models.CASCADE,
        related_name='linhas_fechamento',
        verbose_name="Manifesto"
    )
    filial_operacao = models.ForeignKey(
        'usuarios.Filial',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        verbose_name="Base de Operação"
    )
    data = models.DateField(verbose_name="Data")

    # === DADOS AUTOMÁTICOS (preenchidos pelo motor de cálculo) ===
    qtd_entregas = models.IntegerField(default=0, verbose_name="Entregas Realizadas")
    qtd_coletas = models.IntegerField(default=0, verbose_name="Nº de Coletas")
    qtd_coletas_validas = models.IntegerField(default=0, verbose_name="Coletas Válidas")
    qtd_ctes = models.IntegerField(default=0, verbose_name="Nº CT-es")
    qtd_ctes_realizados = models.IntegerField(default=0, verbose_name="Nº CT-es Realizados")
    total_embarques = models.IntegerField(default=0, verbose_name="Total Embarques")

    # === VALORES CALCULADOS (tarifa × quantidade) ===
    valor_diaria = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Diária (R$)")
    valor_entregas = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Valor Entregas (R$)")
    valor_coletas = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Valor Coletas (R$)")

    # === AJUSTES MANUAIS (preenchidos pelo responsável) ===
    valor_extra = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        verbose_name="Valores Extras (R$)",
        help_text="Valores adicionais por localidades especiais, etc."
    )
    localidade_extra = models.CharField(
        max_length=50, null=True, blank=True,
        verbose_name="Localidade do Extra",
        help_text="UF ou nome da localidade referente ao valor extra (ex: RJ, SP)"
    )
    observacao = models.TextField(null=True, blank=True, verbose_name="Observação")

    # === TOTAL DO DIA ===
    total_dia = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        verbose_name="Total do Dia (R$)"
    )

    # === BREAKDOWN POR BASE (entregas/coletas separadas por UF da filial_operacao) ===
    # Armazenado como JSON para flexibilidade com bases dinâmicas
    # Formato: {"RJ": {"entregas": 5, "coletas": 3}, "SP": {"entregas": 2, "coletas": 1}}
    breakdown_bases = models.JSONField(
        default=dict, blank=True,
        verbose_name="Detalhamento por Base",
        help_text="Contagem de entregas e coletas separadas por UF da filial de operação."
    )

    class Meta:
        verbose_name = "Linha de Fechamento"
        verbose_name_plural = "Linhas de Fechamento"
        ordering = ['motorista__nome_completo', 'data']
        unique_together = ('fechamento', 'manifesto')

    def __str__(self):
        return f"{self.motorista.nome_completo} - MFT {self.manifesto.numero_manifesto} ({self.data})"

    def calcular_total(self):
        """Recalcula o total do dia com base nos valores atuais."""
        self.total_dia = (
            self.valor_diaria +
            self.valor_entregas +
            self.valor_coletas +
            self.valor_extra
        )
        return self.total_dia


class ResumoMotorista(models.Model):
    """
    Totalizador/resumo por motorista dentro de um fechamento.
    Equivalente ao rodapé da aba individual na planilha Excel.
    """
    fechamento = models.ForeignKey(
        FechamentoAgregado,
        on_delete=models.CASCADE,
        related_name='resumos',
        verbose_name="Fechamento"
    )
    motorista = models.ForeignKey(
        'usuarios.Motorista',
        on_delete=models.CASCADE,
        related_name='resumos_fechamento',
        verbose_name="Motorista"
    )

    total_diarias = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Total Diárias (R$)")
    total_servicos = models.IntegerField(default=0, verbose_name="Total Serviços")
    diaria_por_servico = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Diária/Serviço (R$)")
    total_parcial = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Total Parcial (R$)")

    # Ajustes manuais
    valor_pedagio = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        verbose_name="Total Pedágio (R$)"
    )
    valor_desconto = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        verbose_name="Descontos (R$)",
        help_text="Valor de desconto (informar como negativo ou positivo, será subtraído)."
    )
    total_final = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Total Final (R$)")

    # Breakdown por base — JSON dinâmico
    # Formato: {"RJ": {"entregas": 10, "coletas": 5, "valor_entregas": 50, "valor_coletas": 50, "valor_total": 100}, ...}
    breakdown_bases = models.JSONField(
        default=dict, blank=True,
        verbose_name="Totais por Base"
    )

    # Observação geral do motorista no período
    observacao = models.TextField(null=True, blank=True, verbose_name="Observação Geral")

    class Meta:
        verbose_name = "Resumo por Motorista"
        verbose_name_plural = "Resumos por Motorista"
        unique_together = ('fechamento', 'motorista')

    def __str__(self):
        return f"Resumo {self.motorista.nome_completo} - R$ {self.total_final}"


class DadosBancariosAgregado(models.Model):
    """
    Dados bancários do motorista agregado para pagamento.
    Separado do cadastro geral do motorista, visível apenas no módulo financeiro.
    """
    motorista = models.OneToOneField(
        'usuarios.Motorista',
        on_delete=models.CASCADE,
        related_name='dados_bancarios',
        verbose_name="Motorista"
    )
    dados_bancarios = models.TextField(
        null=True, blank=True,
        verbose_name="Dados Bancários",
        help_text="Agência, Conta, Banco. Ex: AG:0001 C/C 12345-6 NUBANK"
    )
    chave_pix = models.CharField(
        max_length=200, null=True, blank=True,
        verbose_name="Chave PIX",
        help_text="CPF, E-mail, Telefone ou Chave aleatória"
    )
    titular_pagamento = models.CharField(
        max_length=200, null=True, blank=True,
        verbose_name="Titular do Pagamento",
        help_text="Nome do titular da conta bancária (se diferente do motorista)"
    )

    class Meta:
        verbose_name = "Dados Bancários (Agregado)"
        verbose_name_plural = "Dados Bancários (Agregados)"

    def __str__(self):
        return f"Banco: {self.motorista.nome_completo}"
