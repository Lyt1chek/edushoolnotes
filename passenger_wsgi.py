import sys
import os

# Указываем путь к корневой папке приложения
# (SpaceWeb сам подставит правильный путь, но для универсальности оставляем)
sys.path.append(os.path.dirname(__file__))

# Импортируем ваше Flask-приложение из app.py
from app import app as application