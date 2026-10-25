import multiprocessing
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
workers = int(os.environ.get("WEB_CONCURRENCY", max(2, min(4, multiprocessing.cpu_count()))))
threads = int(os.environ.get("WEB_THREADS", 4))
worker_class = "gthread"
timeout = int(os.environ.get("WEB_TIMEOUT", 60))
graceful_timeout = 30
keepalive = 5
max_requests = 2000
max_requests_jitter = 200
accesslog = None
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info").lower()
forwarded_allow_ips = os.environ.get("FORWARDED_ALLOW_IPS", "*")
