from django.db import models

class RegraClassificacaoErro(models.Model):
    """
    Regra para classificar erros automaticamente baseado no texto da mensagem.
    O sistema percorre as regras por prioridade e aplica a primeira que bater.
    Configurável no Django Admin por tenant.
    """
    PUBLICO_CHOICES = [
        ('OPERACIONAL', 'Operacional'),
        ('SAC', 'SAC / Suporte'),
        ('AMBOS', 'Ambos'),
    ]
    
    SEVERIDADE_CHOICES = [
        ('CRITICO', 'Crítico'),
        ('ATENCAO', 'Atenção'),
        ('INFO', 'Informação'),
    ]
    
    nome = models.CharField(max_length=100, verbose_name="Nome da Regra",
        help_text="Ex: 'Manifesto em trânsito', 'Ocorrência duplicada'")
    
    pattern = models.CharField(max_length=255, verbose_name="Texto para buscar",
        help_text="Trecho de texto que deve aparecer na mensagem de erro. Case-insensitive. Ex: 'manifesto em trânsito'")
    
    usar_regex = models.BooleanField(default=False, verbose_name="Usar Regex?",
        help_text="Se marcado, o pattern é interpretado como expressão regular")
    
    severidade = models.CharField(max_length=10, choices=SEVERIDADE_CHOICES, default='ATENCAO')
    publico_alvo = models.CharField(max_length=15, choices=PUBLICO_CHOICES, default='AMBOS',
        verbose_name="Público-alvo",
        help_text="Define quem vê este tipo de erro na torre")
    
    exibir_torre = models.BooleanField(default=True, verbose_name="Exibir na Torre?",
        help_text="Se desmarcado, o erro é logado mas NÃO aparece na torre de controle")
    
    prioridade = models.IntegerField(default=100, verbose_name="Prioridade",
        help_text="Menor número = maior prioridade. A primeira regra que bater é usada.")
    
    ativo = models.BooleanField(default=True)
    
    class Meta:
        verbose_name = "Regra de Classificação de Erro"
        verbose_name_plural = "Regras de Classificação de Erros"
        ordering = ['prioridade']
    
    def __str__(self):
        return f"[{self.severidade}] {self.nome} → {self.publico_alvo}"


class LogErroOperacional(models.Model):
    SEVERIDADE_CHOICES = [
        ('CRITICO', 'Crítico'),
        ('ATENCAO', 'Atenção'),
        ('INFO', 'Informação'),
    ]
    
    CATEGORIA_CHOICES = [
        ('INTEGRACAO_BAIXA', 'Integração de Baixa (NF-e)'),
        ('INTEGRACAO_COLETA', 'Integração de Coleta'),
        ('INTEGRACAO_MINUTA', 'Integração de Minuta'),
        ('FINALIZACAO_MANIFESTO', 'Finalização de Manifesto'),
        ('SINCRONIZACAO_NFE', 'Sincronização de NF-e'),
        ('WEBHOOK_MANIFESTO', 'Webhook de Manifesto'),
        ('BUSCA_MANIFESTO', 'Busca/Importação de Manifesto'),
        ('ERRO_MOTORISTA', 'Erro do Motorista'),
        ('OUTRO', 'Outro'),
    ]
    
    STATUS_CHOICES = [
        ('ABERTO', 'Aberto'),
        ('RESOLVIDO', 'Resolvido (Manual)'),
        ('AUTO_RESOLVIDO', 'Resolvido (Automático)'),
        ('IGNORADO', 'Ignorado'),
    ]

    filial = models.ForeignKey('usuarios.Filial', on_delete=models.CASCADE,
        related_name='erros_operacionais')
    categoria = models.CharField(max_length=30, choices=CATEGORIA_CHOICES)
    severidade = models.CharField(max_length=10, choices=SEVERIDADE_CHOICES, default='ATENCAO')
    publico_alvo = models.CharField(max_length=15, default='AMBOS',
        help_text="Herdado da regra de classificação")
    
    titulo = models.CharField(max_length=255)
    descricao = models.TextField()
    erro_raw = models.TextField(blank=True, null=True,
        verbose_name="Mensagem de erro original",
        help_text="Texto completo retornado pelo TMS para auditoria")
    
    # Referências para rastreabilidade
    manifesto_numero = models.CharField(max_length=50, blank=True, null=True)
    nota_fiscal_numero = models.CharField(max_length=50, blank=True, null=True)
    motorista_nome = models.CharField(max_length=255, blank=True, null=True)
    
    # Agrupamento e Contador de Retentativas
    qtd_tentativas = models.IntegerField(default=1, verbose_name="Qtd de Tentativas", help_text="Quantidade de vezes que este exato erro ocorreu")
    historico_tentativas = models.JSONField(default=list, blank=True, verbose_name="Histórico de Tentativas", help_text="Lista de datas/horas de cada ocorrência")

    # Regra que classificou (null = classificação padrão)
    regra_aplicada = models.ForeignKey(RegraClassificacaoErro, null=True, blank=True,
        on_delete=models.SET_NULL, verbose_name="Regra que classificou")
    
    # Status de resolução
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='ABERTO')
    resolvido_por = models.ForeignKey('auth.User', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='erros_resolvidos')
    data_resolucao = models.DateTimeField(null=True, blank=True)
    resolucao_automatica = models.BooleanField(default=False, 
        help_text="Indica se o erro foi resolvido automaticamente por uma retentativa bem-sucedida")
    observacao_resolucao = models.TextField(blank=True, null=True,
        verbose_name="Observação da Resolução", help_text="Anotação opcional do operador")
    
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Log de Erro Operacional"
        verbose_name_plural = "Logs de Erros Operacionais"
        ordering = ['-criado_em']
        indexes = [
            models.Index(fields=['filial', 'status', '-criado_em']),
            models.Index(fields=['severidade', 'status']),
        ]


class TutorialUsuario(models.Model):
    """
    Rastreia quais tutoriais guiados (onboarding tours) cada usuário já concluiu.
    Se o registro existe com concluido=True, o tour não dispara automaticamente.
    """
    usuario = models.ForeignKey('auth.User', on_delete=models.CASCADE, related_name='tutoriais_vistos')
    pagina = models.CharField(max_length=100, verbose_name="Identificador da Página",
        help_text="Ex: 'torre_erros', 'dashboard', 'manifestos'")
    concluido = models.BooleanField(default=False)
    data_conclusao = models.DateTimeField(null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Tutorial do Usuário"
        verbose_name_plural = "Tutoriais dos Usuários"
        unique_together = ('usuario', 'pagina')

    def __str__(self):
        status = "✅" if self.concluido else "⏳"
        return f"{status} {self.usuario.username} - {self.pagina}"
