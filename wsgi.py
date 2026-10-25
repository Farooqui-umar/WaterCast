from app import create_app
from app.startup import prepare_database

app = create_app()

if app.config.get("AUTO_MIGRATE"):
    prepare_database(app)
