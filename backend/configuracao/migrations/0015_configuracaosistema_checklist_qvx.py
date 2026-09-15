from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('configuracao', '0014_alter_configuracaosistema_tms_provider'),
    ]

    operations = [
        migrations.AddField(
            model_name='configuracaosistema',
            name='habilitar_checklist_qvx',
            field=models.BooleanField(
                default=True,
                help_text='Envia status em trânsito e finalizado para a API do Checklist QVX',
                verbose_name='📋 Enviar Status para Checklist (QVX)',
            ),
        ),
        migrations.AddField(
            model_name='configuracaosistema',
            name='checklist_qvx_url',
            field=models.CharField(
                default='https://checklist.qvx.com.br/api/v1/drivers',
                help_text='Endpoint para onde o manifesto será enviado (POST)',
                max_length=300,
                verbose_name='URL da API do Checklist',
            ),
        ),
        migrations.AddField(
            model_name='configuracaosistema',
            name='checklist_qvx_token',
            field=models.CharField(
                default='rx_live_t3wlOG4Y4vS0nFXycFIfftmD_GY4fiq5XWGZ1pvDqcY',
                help_text='Bearer token da API do Checklist',
                max_length=200,
                verbose_name='Token de Autorização Checklist',
            ),
        ),
    ]
