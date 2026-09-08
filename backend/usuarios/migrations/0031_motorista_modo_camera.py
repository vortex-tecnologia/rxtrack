from django.db import migrations, models


def converter_galeria_para_modo_camera(apps, schema_editor):
    """
    Migration de dados: converte o booleano permitir_upload_galeria 
    para o novo campo modo_camera.
    - permitir_upload_galeria=True → modo_camera='galeria'
    - permitir_upload_galeria=False → modo_camera='camera_padrao' (default)
    """
    Motorista = apps.get_model('usuarios', 'Motorista')
    Motorista.objects.filter(
        permitir_upload_galeria=True
    ).update(modo_camera='galeria')


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0030_alter_motorista_tipo_usuario'),
    ]

    operations = [
        # 1. Adiciona o campo modo_camera com default camera_padrao
        migrations.AddField(
            model_name='motorista',
            name='modo_camera',
            field=models.CharField(
                choices=[
                    ('camera_padrao', 'Câmera Padrão'),
                    ('camera_interna', 'Câmera Interna do Track'),
                    ('galeria', 'Galeria'),
                ],
                default='camera_padrao',
                help_text="Define como o motorista captura fotos de canhoto no app. "
                          "Câmera Padrão abre a câmera nativa do Android. "
                          "Câmera Interna usa preview dentro do Track (recomendado para aparelhos fracos). "
                          "Galeria permite selecionar uma imagem já existente.",
                max_length=20,
                verbose_name='Modo de Captura do Canhoto',
            ),
        ),
        # 2. Converte dados existentes
        migrations.RunPython(
            converter_galeria_para_modo_camera,
            reverse_code=migrations.RunPython.noop,
        ),
        # 3. Atualiza verbose_name/help_text do campo legado
        migrations.AlterField(
            model_name='motorista',
            name='permitir_upload_galeria',
            field=models.BooleanField(
                default=False,
                help_text="DEPRECATED — Use 'Modo de Captura do Canhoto' abaixo.",
                verbose_name='[Legado] Permitir Upload da Galeria',
            ),
        ),
    ]
