from django.db import models
from django.contrib.auth import get_user_model
from usuarios.models import Filial

User = get_user_model()

class WebPushSubscription(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='webpush_subscriptions')
    endpoint = models.URLField(max_length=500, unique=True)
    p256dh = models.CharField(max_length=255)
    auth = models.CharField(max_length=255)
    browser = models.CharField(max_length=200, blank=True, null=True)
    group = models.CharField(max_length=100, default='motoristas')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user} - {self.endpoint[:30]}"
    

class BuscaDiariaManifestos(models.Model):
    filial = models.ForeignKey(Filial, on_delete=models.CASCADE, related_name='notificacoes')
    data_criacao = models.DateTimeField(auto_now_add=True)
    json = models.JSONField()

    def __str__(self):
        return f"{self.filial} - {self.data_criacao}"

    class Meta:
        ordering = ['-data_criacao']

class ManifestoNotificado(models.Model):
    manifesto = models.CharField(max_length=50)
    motorista = models.ForeignKey(User, on_delete=models.CASCADE)
    ultima_notificacao = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('manifesto', 'motorista')