import redis
from django.conf import settings

def get_redis_client():
    """
    Returns a Redis client instance using settings from Django.
    """
    # Try to get from CHANNEL_LAYERS config first
    try:
        hosts = settings.CHANNEL_LAYERS.get('default', {}).get('CONFIG', {}).get('hosts', [])
        if hosts:
            host, port = hosts[0]
            return redis.Redis(host=host, port=port, db=0, decode_responses=True)
    except Exception:
        pass
    
    # Fallback to CELERY_BROKER_URL or defaults
    return redis.Redis(host='redis', port=6379, db=0, decode_responses=True)
