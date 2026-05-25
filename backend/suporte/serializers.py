from rest_framework import serializers
from .models import TicketSuporte, MensagemSuporte

class MensagemSuporteSerializer(serializers.ModelSerializer):
    remetente_nome = serializers.SerializerMethodField()
    arquivo_url = serializers.SerializerMethodField()

    class Meta:
        model = MensagemSuporte
        fields = ['id', 'ticket', 'enviado_por_motorista', 'atendente', 'remetente_nome', 'tipo', 'texto', 'arquivo', 'arquivo_url', 'created_at', 'lida']
        read_only_fields = ['id', 'created_at', 'atendente', 'remetente_nome', 'arquivo_url']

    def get_remetente_nome(self, obj):
        if obj.enviado_por_motorista and obj.ticket.motorista:
            return obj.ticket.motorista.nome_completo
        elif obj.atendente:
            return obj.atendente.get_full_name() or obj.atendente.username
        return "Sistema"

    def get_arquivo_url(self, obj):
        if not obj.arquivo:
            return None
        # Se o valor armazenado ja e uma URL completa (FTP upload), retorna direto
        valor = str(obj.arquivo)
        if valor.startswith('http://') or valor.startswith('https://'):
            return valor
        # Senao, tenta gerar URL local
        try:
            return obj.arquivo.url
        except Exception:
            return valor

class TicketSuporteSerializer(serializers.ModelSerializer):
    mensagens = MensagemSuporteSerializer(many=True, read_only=True)
    categoria_display = serializers.CharField(source='get_categoria_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    motorista_str = serializers.SerializerMethodField()
    
    class Meta:
        model = TicketSuporte
        fields = '__all__'
        read_only_fields = ['motorista', 'filial', 'atendente', 'status', 'created_at', 'updated_at', 'closed_at']
    
    def get_motorista_str(self, obj):
        if obj.motorista:
            return obj.motorista.nome_completo
        return "Motorista"
