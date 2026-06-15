from django.db import models
from django_tenants.models import TenantMixin, DomainMixin

class Client(TenantMixin):
    name = models.CharField(max_length=100)
    created_on = models.DateField(auto_now_add=True)

    # O schema será automaticamente criado no banco quando o cliente for salvo
    auto_create_schema = True

    def __str__(self):
        return f"{self.name} (Schema: {self.schema_name})"

class Domain(DomainMixin):
    def __str__(self):
        return self.domain
