# wsgi.py
from app import app as application

# Si tu aplicación Flask se llama 'app' en app.py,
# simplemente importamos 'app' y la renombramos a 'application'
# para cumplir con la convención de Vercel.