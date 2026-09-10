from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('configuracao', '0013_add_patch_v2_5_0'),
    ]

    operations = [
        migrations.AlterField(
            model_name='configuracaosistema',
            name='tms_provider',
            field=models.CharField(
                choices=[
                    ('esl_cloud', 'ESL Cloud'),
                    ('brudam', 'Brudam TMS'),
                    ('totvs', 'TOTVS'),
                    ('sap_tm', 'SAP TM'),
                    ('intelipost', 'Intelipost'),
                    ('nenhum', 'Sem integração TMS'),
                ],
                default='esl_cloud',
                help_text='Define qual sistema TMS este cliente usa para integração de manifestos.',
                max_length=30,
                verbose_name='🔗 Provedor TMS',
            ),
        ),
    ]
