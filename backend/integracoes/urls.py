from django.urls import path
from .views.soap_integracao import UploadRouteSoapView
from .views.api_tms import (
    iniciar_transporte_tms,
    adicionar_nota_manifesto_tms,
    finalizar_manifesto_tms,
    registrar_nota_tms,
    status_ocorrencia_tms,
    comprovante_nota_tms,
    remover_nota_tms
)

urlpatterns = [
    path('soap/uploadRoute/', UploadRouteSoapView.as_view(), name='soap_upload_route'),
    
    # Manifestos
    path('tms/manifesto/iniciar/', iniciar_transporte_tms, name='tms_iniciar_manifesto'),
    path('tms/manifesto/finalizar/', finalizar_manifesto_tms, name='tms_finalizar_manifesto'),
    path('tms/manifesto/nota/adicionar/', adicionar_nota_manifesto_tms, name='tms_adicionar_nota_manifesto'),

    # Notas Fiscais
    path('tms/nota/registrar/', registrar_nota_tms, name='tms_registrar_nota'),
    path('tms/nota/status/', status_ocorrencia_tms, name='tms_status_ocorrencia'),
    path('tms/nota/comprovante/', comprovante_nota_tms, name='tms_comprovante_nota'),
    path('tms/nota/deletar/', remover_nota_tms, name='tms_remover_nota'),
]
