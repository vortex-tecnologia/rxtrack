from django.urls import path
from .views.soap_integracao import UploadRouteSoapView

urlpatterns = [
    path('soap/uploadRoute/', UploadRouteSoapView.as_view(), name='soap_upload_route'),
]
