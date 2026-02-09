import os
from pathlib import Path

from flask import Flask, redirect, url_for, request
from flask_compress import Compress
from flask_login import LoginManager, current_user
from werkzeug.middleware.proxy_fix import ProxyFix

from models import db, User, Journal, Issue, Article
from routes_public import register_public_routes
from routes_admin import register_admin_routes


BASE_DIR = Path(__file__).parent

# Создаём папку instance если её нет
(BASE_DIR / 'instance').mkdir(exist_ok=True)


app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
Compress(app)  # Gzip/Brotli сжатие

# Настройки
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-insecure-key-change-me')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///publisher.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 31536000

# Кэширование шаблонов
app.jinja_env.auto_reload = os.environ.get('FLASK_DEBUG', '1') == '1'

# Папки для загрузок
UPLOAD_COVERS = str(BASE_DIR / 'static' / 'uploads' / 'covers')
UPLOAD_PDFS = str(BASE_DIR / 'static' / 'uploads' / 'pdfs')
app.config['UPLOAD_COVERS'] = UPLOAD_COVERS
app.config['UPLOAD_PDFS'] = UPLOAD_PDFS
os.makedirs(UPLOAD_COVERS, exist_ok=True)
os.makedirs(UPLOAD_PDFS, exist_ok=True)

# Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'admin_login'
login_manager.login_message = 'Войдите в систему для доступа.'
login_manager.login_message_category = 'info'


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ============================================================
#   ЗАКРЫТЫЙ РЕЖИМ: весь сайт требует авторизации.
#   Чтобы открыть сайт для всех — установите SITE_PUBLIC=1
#   или удалите/закомментируйте этот блок.
# ============================================================
SITE_PUBLIC = os.environ.get('SITE_PUBLIC', '0') == '1'


@app.before_request
def require_login():
    """Если сайт не публичный — требуем авторизацию на всех страницах."""
    if SITE_PUBLIC:
        return  # сайт открыт для всех

    # Пропускаем без проверки: страницу логина, статику, logout
    if request.endpoint and request.endpoint in ('admin_login', 'static'):
        return

    # Если не авторизован — на страницу входа (с сохранением куда шёл)
    if not current_user.is_authenticated:
        return redirect(url_for('admin_login', next=request.path))


# Инициализация БД и маршрутов
db.init_app(app)
register_public_routes(app)
register_admin_routes(app)

with app.app_context():
    db.create_all()


# Jinja2 фильтры
def pluralize_ru(number, form1, form2, form5):
    """Склонение слов: 1 статья, 2 статьи, 5 статей."""
    n = abs(number) % 100
    if 11 <= n <= 19:
        return form5
    n = n % 10
    if n == 1:
        return form1
    if 2 <= n <= 4:
        return form2
    return form5


app.jinja_env.filters['pluralize_ru'] = pluralize_ru


def init_data():
    """Создание начальных данных."""
    with app.app_context():
        # Создаём админа если нет пользователей
        if User.query.count() == 0:
            print("Создаём администратора...")
            admin = User(username='admin', display_name='Администратор', role='admin')
            admin.set_password('admin2026')
            db.session.add(admin)
            db.session.commit()
            print("Администратор создан (admin / admin2026)")
        else:
            print(f"Пользователей: {User.query.count()}")

        print(f"Журналов: {Journal.query.count()}")
        print(f"Выпусков: {Issue.query.count()}")
        print(f"Статей: {Article.query.count()}")


if __name__ == "__main__":
    print("Starting publisher site...")
    init_data()
    print("Сервер стартует на http://127.0.0.1:5000")
    app.run(debug=True)
