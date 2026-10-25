import os

os.environ.setdefault("APP_ENV", "development")

from flask_migrate import upgrade

from app import create_app
from app.cli import bootstrap_admin, seed_default_users

app = create_app()

if __name__ == "__main__":
    with app.app_context():
        upgrade(directory="migrations")
        seed_default_users()
        password = bootstrap_admin(generate_in_dev=True)
        if password:
            user = app.config["ADMIN_USERNAME"] or "admin"
            print("\n" + "=" * 64)
            print(f"  Staff sign-in created  ->  username: {user}   password: {password}")
            print("  (shown once - set ADMIN_USERNAME / ADMIN_PASSWORD in .env to choose your own)")
            print("=" * 64 + "\n")
    host, port = os.environ.get("HOST", "127.0.0.1"), int(os.environ.get("PORT", "5000"))
    try:
        from waitress import serve
    except ImportError:
        app.run(host=host, port=port, debug=False, threaded=True)
    else:
        print(f"WaterCast is running at http://{'localhost' if host in ('127.0.0.1', '0.0.0.0') else host}:{port}")
        serve(app, host=host, port=port, threads=int(os.environ.get("WEB_THREADS", "12")), connection_limit=200,
              channel_timeout=120, cleanup_interval=30, ident="WaterCast")
