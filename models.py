from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash


db = SQLAlchemy()


def _utcnow():
    """UTC now, совместимо с Python 3.12+."""
    return datetime.now(timezone.utc)


# =============================================
#   ПОЛЬЗОВАТЕЛИ (админы CMS)
# =============================================
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    display_name = db.Column(db.String(150), nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='editor')  # 'admin' или 'editor'
    is_active_user = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=_utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role == 'admin'


# =============================================
#   ЖУРНАЛЫ
# =============================================
class Journal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(200), unique=True, nullable=False)
    issn = db.Column(db.String(20))
    eissn = db.Column(db.String(20))  # электронный ISSN
    description = db.Column(db.Text)  # описание журнала
    aims_scope = db.Column(db.Text)  # цели и область
    cover_image = db.Column(db.String(500))  # обложка журнала (16:9)
    bg_image = db.Column(db.String(500))  # фоновая картинка для hover на странице журналов
    editorial_board = db.Column(db.Text)  # редколлегия (HTML или текст)
    submission_info = db.Column(db.Text)  # информация для авторов
    is_active = db.Column(db.Boolean, default=True)
    order = db.Column(db.Integer, default=0)  # порядок отображения
    created_at = db.Column(db.DateTime, default=_utcnow)

    issues = db.relationship('Issue', backref='journal', cascade='all, delete-orphan',
                             order_by='Issue.year.desc(), Issue.number.desc()')


# =============================================
#   ВЫПУСКИ
# =============================================
class Issue(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    journal_id = db.Column(db.Integer, db.ForeignKey('journal.id'), nullable=False, index=True)
    volume = db.Column(db.Integer)  # том
    number = db.Column(db.Integer, nullable=False)  # номер
    year = db.Column(db.Integer, nullable=False)
    publication_date = db.Column(db.String(50))  # дата публикации
    cover_image = db.Column(db.String(500))  # обложка выпуска
    description = db.Column(db.Text)  # описание / от редакции
    is_published = db.Column(db.Boolean, default=False)  # опубликован на сайте?
    created_at = db.Column(db.DateTime, default=_utcnow)

    articles = db.relationship('Article', backref='issue', cascade='all, delete-orphan',
                               order_by='Article.order')


# =============================================
#   СТАТЬИ
# =============================================
class Article(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    issue_id = db.Column(db.Integer, db.ForeignKey('issue.id'), nullable=False, index=True)

    # Основные данные
    title = db.Column(db.String(500), nullable=False)
    title_en = db.Column(db.String(500))  # название на английском
    abstract = db.Column(db.Text)  # аннотация
    abstract_en = db.Column(db.Text)  # аннотация на английском
    keywords = db.Column(db.String(500))  # ключевые слова (через запятую)
    keywords_en = db.Column(db.String(500))  # ключевые слова EN

    # Библиографические данные
    doi = db.Column(db.String(100))
    pages_from = db.Column(db.Integer)
    pages_to = db.Column(db.Integer)
    language = db.Column(db.String(20), default='ru')  # ru, en

    # Файлы
    pdf_file = db.Column(db.String(500))  # PDF статьи

    # Метаданные
    order = db.Column(db.Integer, default=0)  # порядок в выпуске
    is_published = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=_utcnow)

    # Авторы
    authors = db.relationship('ArticleAuthor', backref='article', cascade='all, delete-orphan',
                              order_by='ArticleAuthor.order')

    @staticmethod
    def _looks_like_name(text):
        """Проверяет, похожа ли строка на ФИО (а не должность/аффилиацию)."""
        import re
        t = text.strip()
        if not t or len(t) > 40:
            return False
        # Содержит явные признаки мусора
        if any(w in t.lower() for w in [
            'кафедр', 'универси', 'институт', 'факультет', 'лаборатор',
            'отдел', 'e-mail', 'email', 'mail.ru', 'yandex',
            'сотрудник', 'начальник', 'директор', 'заведующ',
            'академи', 'доцент', 'профессор',
            'органической', 'технической', 'государствен',
        ]):
            return False
        # Содержит паттерн ФИО (русское или латиница)
        if re.search(r'[А-ЯЁ][а-яё]+\s+[А-ЯЁ]\.', t):
            return True
        if re.search(r'[А-ЯЁ]\.\s?[А-ЯЁ]?\.?\s?[А-ЯЁ][а-яё]+', t):
            return True
        if re.search(r'[A-Z][a-z]+\s+[A-Z]\.', t):
            return True
        if re.search(r'[A-Z]\.\s?[A-Z]?\.?\s?[A-Z][a-z]+', t):
            return True
        # Короткое (<=25) из 2-3 слов, все с заглавной — вероятно имя
        words = t.split()
        if len(words) in (2, 3) and len(t) <= 25 and all(w[0].isupper() for w in words if w):
            return True
        return False

    @staticmethod
    def _clean_name(text):
        """Убирает цифры-индексы из конца имени."""
        import re
        # Убираем trailing цифры, пробелы, дефисы, суперскрипты
        return re.sub(r'[\s\d\−\–⁰¹²³⁴⁵⁶⁷⁸⁹]+$', '', text).strip()

    @property
    def authors_str(self):
        """Строка с именами авторов через запятую (только ФИО, без должностей)."""
        names = [self._clean_name(a.full_name) for a in self.authors if self._looks_like_name(a.full_name)]
        return ', '.join(names) if names else ''

    @property
    def pages_str(self):
        """Строка со страницами: '12-25' или ''."""
        if self.pages_from and self.pages_to:
            return f'{self.pages_from}–{self.pages_to}'
        elif self.pages_from:
            return str(self.pages_from)
        return ''


# =============================================
#   АВТОРЫ СТАТЕЙ
# =============================================
class ArticleAuthor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    article_id = db.Column(db.Integer, db.ForeignKey('article.id'), nullable=False, index=True)

    full_name = db.Column(db.String(200), nullable=False)
    full_name_en = db.Column(db.String(200))  # ФИО на английском
    affiliation = db.Column(db.String(500))  # организация
    affiliation_en = db.Column(db.String(500))
    email = db.Column(db.String(100))
    orcid = db.Column(db.String(50))  # ORCID ID
    order = db.Column(db.Integer, default=0)

    def __repr__(self):
        return self.full_name or f'Author #{self.id}'
