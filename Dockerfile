FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    FLASK_APP=wsgi:app \
    APP_ENV=production \
    PORT=8000
WORKDIR /srv/app
RUN groupadd --system app && useradd --system --gid app --home-dir /srv/app --shell /usr/sbin/nologin app
COPY requirements.lock ./
RUN pip install -r requirements.lock
COPY --chown=app:app . .
RUN sed -i 's/\r$//' deploy/entrypoint.sh && chmod +x deploy/entrypoint.sh \
    && mkdir -p /srv/app/instance && chown app:app /srv/app/instance
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT','8000'), timeout=4)"
ENTRYPOINT ["deploy/entrypoint.sh"]
CMD ["gunicorn", "-c", "gunicorn.conf.py", "wsgi:app"]
