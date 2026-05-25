#!/bin/sh
echo "=== QuickTrack Entrypoint ==="
echo "Esperando o banco de dados MySQL..."

python - <<END
import time
import os
import MySQLdb

max_retries = 30
retry = 0

while retry < max_retries:
    try:
        conn = MySQLdb.connect(
            db=os.environ.get('DB_NAME', 'st63136_dev_app_transportadora'),
            user=os.environ.get('DB_USER', 'st63136_quickdelivery'),
            passwd=os.environ.get('DB_PASSWORD', ''),
            host=os.environ.get('DB_HOST', 'host.docker.internal'),
            port=int(os.environ.get('DB_PORT', 3308)),
            connect_timeout=5
        )
        conn.close()
        print("Conexão estabelecida com sucesso!")
        break
    except Exception as e:
        retry += 1
        print(f"Tentativa {retry}/{max_retries} - Aguardando MySQL: {e}")
        time.sleep(2)

if retry >= max_retries:
    print("ERRO: Não foi possível conectar ao banco de dados.")
    exit(1)
END

echo "Banco pronto!"

# ============================================================
# SETUP AUTOMÁTICO (apenas no container backend principal)
# A variável RUN_SETUP=true é definida SOMENTE no service backend
# do docker-compose.yml. Celery workers/beat NÃO a possuem.
# ============================================================
if [ "$RUN_SETUP" = "true" ]; then
    echo ">>> Rodando migrações do banco de dados..."
    python manage.py migrate --noinput

    echo ">>> Coletando arquivos estáticos..."
    python manage.py collectstatic --noinput

    echo ">>> Configurando superusuário privado..."
    python manage.py setup_private_admin

    echo "=== Setup completo! ==="
fi

echo "Executando comando: $@"
exec "$@"
