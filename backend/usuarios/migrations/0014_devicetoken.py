from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
        ('usuarios', '0013_motorista_permitir_upload_galeria'),
    ]

    operations = [
        migrations.CreateModel(
            name='DeviceToken',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('token', models.CharField(db_index=True, max_length=64, unique=True, verbose_name='Token do Dispositivo')),
                ('device_info', models.CharField(blank=True, default='APK Android', max_length=255, verbose_name='Info do Dispositivo')),
                ('criado_em', models.DateTimeField(auto_now_add=True, verbose_name='Criado em')),
                ('ultimo_uso', models.DateTimeField(auto_now=True, verbose_name='Ultimo Uso')),
                ('ativo', models.BooleanField(default=True, verbose_name='Ativo')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='device_tokens', to='auth.user', verbose_name='Usuario')),
            ],
            options={
                'verbose_name': 'Device Token',
                'verbose_name_plural': 'Device Tokens',
            },
        ),
    ]
