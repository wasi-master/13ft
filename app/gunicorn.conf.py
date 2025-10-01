from os import environ

# https://docs.gunicorn.org/en/stable/settings.html#settings
bind = f"0.0.0.0:{environ.get('PORT', 5000)}"
