from rest_framework.views import APIView
from rest_framework.response import Response
from manifesto.models import Ocorrencia
from django.db.models import Q

class ListarOcorrenciasView(APIView):
    def get(self, request):
        is_coleta = request.query_params.get('is_coleta')
        is_entrega = request.query_params.get('is_entrega')
        tipo_op = (request.query_params.get('tipo_operacao') or '').upper()
        
        queryset = Ocorrencia.objects.all()
        
        if is_coleta == 'true' or tipo_op == 'COLETA':
            queryset = queryset.filter(Q(is_coleta=True) | Q(tipo='ENTREGA') | Q(codigo_referencia='01') | Q(codigo_tms='01'))
        elif is_entrega == 'true' or tipo_op in ['ENTREGA', 'TRANSFERENCIA', 'DESPACHO', 'RETIRADA', 'OUTROS']:
            queryset = queryset.filter(Q(is_entrega=True) | Q(tipo='ENTREGA') | Q(codigo_referencia__in=['01', '02']) | Q(codigo_tms__in=['01', '02', '1', '2']))
            
        ocorrencias = queryset.order_by('codigo_tms')
        
        data = [
            {
                'id': occ.id,
                'codigo_tms': occ.codigo_tms,
                'codigo_referencia': occ.codigo_referencia or occ.codigo_tms,
                'descricao': occ.descricao,
                'tipo': occ.tipo,
                'is_coleta': occ.is_coleta,
                'is_entrega': occ.is_entrega
            }
            for occ in ocorrencias
        ]
        
        return Response(data)