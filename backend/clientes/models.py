# clientes/models.py
# Copyright (c) 2026 Luiz Gustavo. Todos os direitos reservados. Licença Proprietária.

from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class UsuarioCliente(models.Model):
    """
    Perfil de um usuário do tipo Cliente (Pagador de Frete / Embarcador).
    Completamente isolado do modelo Motorista — não compartilha tabela nem lógica.
    O cliente acessa pelo mesmo /login/ e é redirecionado para /portal-cliente/.
    """
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='cliente_perfil',
        verbose_name="Conta de Usuário",
        null=True,
        blank=True,
        help_text="Vinculado ao auth.User para autenticação via sessão."
    )
    nome_completo = models.CharField(max_length=255, verbose_name="Nome Completo")
    cpf = models.CharField(max_length=11, unique=True, verbose_name="CPF")
    email = models.EmailField(verbose_name="E-mail")
    telefone = models.CharField(max_length=20, blank=True, null=True, verbose_name="Telefone")

    ativo = models.BooleanField(default=True, verbose_name="Ativo")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")
    ultimo_acesso = models.DateTimeField(null=True, blank=True, verbose_name="Último Acesso")

    def clean(self):
        import re
        if self.cpf:
            self.cpf = re.sub(r'\D', '', str(self.cpf))
        super().clean()

    def save(self, *args, **kwargs):
        import re
        if self.cpf:
            self.cpf = re.sub(r'\D', '', str(self.cpf))
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.nome_completo} (CPF: {self.cpf})"

    class Meta:
        verbose_name = "Usuário Cliente"
        verbose_name_plural = "Usuários Clientes"
        ordering = ['nome_completo']


class VinculoPagador(models.Model):
    """
    Relação M:N entre um UsuarioCliente e os pagadores de frete (CNPJs) que ele pode visualizar.
    O match é feito pelo campo pagador_nome, que corresponde ao Frete.pagador_nome no banco.
    Um cliente pode ter múltiplos CNPJs vinculados (ex: AMBEV SP, AMBEV RJ, AMBEV MG).
    """
    usuario_cliente = models.ForeignKey(
        UsuarioCliente,
        on_delete=models.CASCADE,
        related_name='vinculos',
        verbose_name="Usuário Cliente"
    )
    pagador_nome = models.CharField(
        max_length=255,
        verbose_name="Nome do Pagador",
        help_text="Deve corresponder exatamente ao Frete.pagador_nome no sistema."
    )
    pagador_documento = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name="CNPJ do Pagador",
        help_text="CNPJ para referência visual. O match principal é pelo nome."
    )
    ativo = models.BooleanField(default=True, verbose_name="Ativo")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")

    def save(self, *args, **kwargs):
        # Auto-preenche pagador_documento se estiver em branco
        if not self.pagador_documento and self.pagador_nome:
            try:
                from manifesto.models import Frete
                f = Frete.objects.filter(pagador_nome=self.pagador_nome).exclude(pagador_documento__isnull=True).exclude(pagador_documento='').first()
                if f and f.pagador_documento:
                    self.pagador_documento = f.pagador_documento
                else:
                    from financeiro.models import ClienteBasePagadora
                    cbp = ClienteBasePagadora.objects.filter(nome=self.pagador_nome).exclude(documento__isnull=True).exclude(documento='').first()
                    if cbp and cbp.documento:
                        self.pagador_documento = cbp.documento
            except Exception:
                pass
        super().save(*args, **kwargs)

    def __str__(self):
        doc = f" ({self.pagador_documento})" if self.pagador_documento else ""
        return f"{self.usuario_cliente.nome_completo} → {self.pagador_nome}{doc}"

    class Meta:
        verbose_name = "Vínculo de Pagador"
        verbose_name_plural = "Vínculos de Pagadores"
        unique_together = ('usuario_cliente', 'pagador_nome')
        ordering = ['pagador_nome']
