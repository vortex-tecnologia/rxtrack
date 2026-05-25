# manifestos/serializers.py

from rest_framework import serializers
from .models import Manifesto, NotaFiscal, BaixaNF, Ocorrencia, HistoricoOcorrencia
from usuarios.serializers import MotoristaPerfilSerializer 
from django.utils import timezone

# --- Componentes Menores ---

class OcorrenciaSerializer(serializers.ModelSerializer):
    """
    Serializador para listar todos os códigos de ocorrência (GET /api/ocorrencias/).
    """
    class Meta:
        model = Ocorrencia
        fields = ['codigo_tms', 'descricao', 'tipo']


class ManifestoBuscaSerializer(serializers.Serializer):
    """
    Serializador de entrada para a busca de manifesto (POST /api/manifesto/busca/).
    """
    numero_manifesto = serializers.CharField(max_length=50)


# --- Serializers de Saída ---

class HistoricoOcorrenciaSerializer(serializers.ModelSerializer):
    """
    Serializador para o histórico detalhado de eventos de rastreamento de uma NF.
    """
    class Meta:
        model = HistoricoOcorrencia
        fields = ['codigo_tms', 'data_ocorrencia', 'comentarios']


class BaixaNFRetrieveSerializer(serializers.ModelSerializer):
    """
    Serializador para retornar os dados da baixa já realizada (se houver).
    """
    ocorrencia_info = OcorrenciaSerializer(source='ocorrencia', read_only=True)
    
    class Meta:
        model = BaixaNF
        fields = ['tipo', 'comprovante_foto', 'observacao', 'data_baixa', 'ocorrencia_info']


class NotaFiscalSerializer(serializers.ModelSerializer):
    """
    Serializador principal para Notas Fiscais (retorno para o app).
    """
    # Adiciona o serializer de baixa, se houver um registro de BaixaNF
    baixa_info = BaixaNFRetrieveSerializer(read_only=True) 
    
    # Adiciona o histórico de eventos (útil para debug e visualização)
    # historico = HistoricoOcorrenciaSerializer(many=True, read_only=True) 

    class Meta:
        model = NotaFiscal
        fields = [
            'id', 
            'chave_acesso', 
            'numero_nota', 
            'destinatario', 
            'endereco_entrega', 
            'status', 
            'baixa_info',
            # 'historico' (opcional)
        ]


class ManifestoSerializer(serializers.ModelSerializer):
    """
    Serializador completo para o manifesto ativo (GET /api/manifesto/status/).
    """
    motorista = MotoristaPerfilSerializer(read_only=True)
    notas_fiscais = NotaFiscalSerializer(many=True, read_only=True)

    class Meta:
        model = Manifesto
        fields = [
            'id', 
            'numero_manifesto', 
            'motorista', 
            'km_inicial', 
            'km_final', 
            'finalizado', 
            'data_criacao', 
            'notas_fiscais'
        ]


# --- Serializer de Entrada (Para a Baixa) ---

class BaixaNFCreateSerializer(serializers.Serializer):
    """
    Define os campos de entrada para registrar uma nova baixa (POST /api/nf/<pk>/baixa/).
    Como o upload de arquivos é complexo, usamos Serializer base em vez de ModelSerializer.
    """
    # Tipo: 'ENTREGA' ou 'OCORRENCIA'
    tipo = serializers.ChoiceField(choices=['ENTREGA', 'OCORRENCIA'])
    
    # Recebe o arquivo da foto (multi-part form data)
    comprovante_foto = serializers.ImageField(required=False)
    
    # Recebe o código TMS (Ex: '1' para entrega, '126' para cliente ausente)
    codigo_ocorrencia = serializers.CharField(max_length=10) 
    
    observacao = serializers.CharField(required=False)
    
    def validate(self, data):
        # Validação personalizada para garantir que 'ENTREGA' ou 'OCORRENCIA' tenham um código válido
        codigo = data.get('codigo_ocorrencia')
        if not codigo:
             raise serializers.ValidationError({"codigo_ocorrencia": "O código de ocorrência é obrigatório."})
        
        # Validação para garantir que o código exista no DB
        try:
            Ocorrencia.objects.get(codigo_tms=codigo)
        except Ocorrencia.DoesNotExist:
             raise serializers.ValidationError({"codigo_ocorrencia": "Código de ocorrência inválido ou inexistente."})

        # Validação: Se for ENTREGA, a foto é geralmente esperada
        if data.get('tipo') == 'ENTREGA' and not data.get('comprovante_foto'):
            # Pode ser uma validação mais branda dependendo da regra do negócio
            pass # Por enquanto, deixamos opcional, mas você pode mudar para raise aqui.

        return data