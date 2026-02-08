import json
import os
import re
from datetime import datetime, timezone
from functools import wraps

from flask import (
    render_template, request, jsonify, redirect,
    url_for, flash, current_app, send_file,
)
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename

from models import db, User, Journal, Issue, Article, ArticleAuthor


ALLOWED_IMAGE = {'jpg', 'jpeg', 'png', 'gif', 'webp', 'svg'}
ALLOWED_PDF = {'pdf'}


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


def allowed_image(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE


def allowed_pdf(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_PDF


def slugify(text):
    """Простая транслитерация + slugify для русского текста."""
    translit_map = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo',
        'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
        'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
        'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'shch',
        'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
    }
    text = text.lower().strip()
    result = []
    for char in text:
        if char in translit_map:
            result.append(translit_map[char])
        elif char.isalnum():
            result.append(char)
        elif char in (' ', '-', '_'):
            result.append('-')
    slug = re.sub(r'-+', '-', ''.join(result)).strip('-')
    return slug or 'journal'


def admin_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated


def _save_image(file, upload_folder):
    """Сохраняет изображение, возвращает имя файла."""
    if file and file.filename and allowed_image(file.filename):
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_')
        filename = secure_filename(timestamp + file.filename)
        file.save(os.path.join(upload_folder, filename))
        return filename
    return None


def _save_pdf(file, upload_folder):
    """Сохраняет PDF, возвращает имя файла."""
    if file and file.filename and allowed_pdf(file.filename):
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_')
        filename = secure_filename(timestamp + file.filename)
        file.save(os.path.join(upload_folder, filename))
        return filename
    return None


def register_admin_routes(app):
    """Маршруты админ-панели (CMS)."""

    # ==================== AUTH ====================
    @app.route('/admin/login', methods=['GET', 'POST'])
    def admin_login():
        if current_user.is_authenticated:
            return redirect(url_for('admin_dashboard'))
        if request.method == 'POST':
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')
            user = User.query.filter_by(username=username).first()
            if user and user.is_active_user and user.check_password(password):
                login_user(user, remember=True)
                return redirect(url_for('admin_dashboard'))
            flash('Неверный логин или пароль', 'error')
        return render_template('admin/login.html')

    @app.route('/admin/logout')
    @login_required
    def admin_logout():
        logout_user()
        return redirect(url_for('admin_login'))

    # ==================== DASHBOARD ====================
    @app.route('/admin')
    @app.route('/admin/dashboard')
    @admin_required
    def admin_dashboard():
        # Основная статистика
        journals_total = Journal.query.count()
        journals_active = Journal.query.filter_by(is_active=True).count()
        issues_total = Issue.query.count()
        issues_published = Issue.query.filter_by(is_published=True).count()
        issues_draft = issues_total - issues_published
        articles_total = Article.query.count()
        articles_with_pdf = Article.query.filter(Article.pdf_file.isnot(None), Article.pdf_file != '').count()
        articles_with_doi = Article.query.filter(Article.doi.isnot(None), Article.doi != '').count()
        users_total = User.query.count()

        stats = {
            'journals_total': journals_total,
            'journals_active': journals_active,
            'issues_total': issues_total,
            'issues_published': issues_published,
            'issues_draft': issues_draft,
            'articles_total': articles_total,
            'articles_with_pdf': articles_with_pdf,
            'articles_with_doi': articles_with_doi,
            'users_total': users_total,
        }

        # Сводка по журналам
        journals = (
            Journal.query
            .options(db.subqueryload(Journal.issues).subqueryload(Issue.articles))
            .order_by(Journal.order, Journal.name)
            .all()
        )
        journal_summaries = []
        for j in journals:
            total_issues = len(j.issues)
            published_issues = sum(1 for i in j.issues if i.is_published)
            total_articles = sum(len(i.articles) for i in j.issues)
            latest_issue = j.issues[0] if j.issues else None
            journal_summaries.append({
                'journal': j,
                'total_issues': total_issues,
                'published_issues': published_issues,
                'total_articles': total_articles,
                'latest_issue': latest_issue,
            })

        # Предупреждения о контенте
        warnings = []
        articles_no_pdf = Article.query.filter(
            db.or_(Article.pdf_file.is_(None), Article.pdf_file == '')
        ).count()
        if articles_no_pdf:
            warnings.append({
                'type': 'warning',
                'message': f'{articles_no_pdf} {pluralize_ru(articles_no_pdf, "статья", "статьи", "статей")} без PDF-файла',
            })

        articles_no_abstract = Article.query.filter(
            db.or_(Article.abstract.is_(None), Article.abstract == '')
        ).count()
        if articles_no_abstract:
            warnings.append({
                'type': 'info',
                'message': f'{articles_no_abstract} {pluralize_ru(articles_no_abstract, "статья", "статьи", "статей")} без аннотации',
            })

        articles_no_doi = articles_total - articles_with_doi
        if articles_no_doi:
            warnings.append({
                'type': 'info',
                'message': f'{articles_no_doi} {pluralize_ru(articles_no_doi, "статья", "статьи", "статей")} без DOI',
            })

        empty_issues = Issue.query.filter(~Issue.articles.any()).count()
        if empty_issues:
            warnings.append({
                'type': 'warning',
                'message': f'{empty_issues} {pluralize_ru(empty_issues, "выпуск", "выпуска", "выпусков")} без статей',
            })

        if issues_draft:
            warnings.append({
                'type': 'info',
                'message': f'{issues_draft} {pluralize_ru(issues_draft, "выпуск", "выпуска", "выпусков")} в черновиках (не опубликованы)',
            })

        # Последние статьи
        recent_articles = (
            Article.query
            .options(
                db.joinedload(Article.issue).joinedload(Issue.journal),
                db.joinedload(Article.authors)
            )
            .order_by(Article.id.desc())
            .limit(10)
            .all()
        )

        return render_template(
            'admin/dashboard.html',
            stats=stats,
            journal_summaries=journal_summaries,
            warnings=warnings,
            recent_articles=recent_articles,
        )

    # ==================== ЖУРНАЛЫ ====================
    @app.route('/admin/journals')
    @admin_required
    def admin_journals():
        journals = Journal.query.order_by(Journal.order, Journal.name).all()
        return render_template('admin/journals.html', journals=journals)

    @app.route('/admin/journals/add', methods=['GET', 'POST'])
    @admin_required
    def admin_journal_add():
        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            if not name:
                flash('Название обязательно', 'error')
                return redirect(url_for('admin_journal_add'))

            slug = request.form.get('slug', '').strip() or slugify(name)

            # Уникальность slug
            existing = Journal.query.filter_by(slug=slug).first()
            if existing:
                slug = slug + '-' + str(Journal.query.count() + 1)

            journal = Journal(
                name=name,
                slug=slug,
                issn=request.form.get('issn', '').strip() or None,
                eissn=request.form.get('eissn', '').strip() or None,
                description=request.form.get('description', '').strip() or None,
                aims_scope=request.form.get('aims_scope', '').strip() or None,
                editorial_board=request.form.get('editorial_board', '').strip() or None,
                submission_info=request.form.get('submission_info', '').strip() or None,
                is_active=('is_active' in request.form),
                order=int(request.form.get('order', 0) or 0),
            )

            cover = request.files.get('cover_image')
            saved = _save_image(cover, current_app.config['UPLOAD_COVERS'])
            if saved:
                journal.cover_image = saved

            db.session.add(journal)
            db.session.commit()
            flash(f'Журнал «{journal.name}» создан', 'success')
            return redirect(url_for('admin_journals'))

        return render_template('admin/journal_edit.html', journal=None)

    @app.route('/admin/journals/<int:journal_id>/edit', methods=['GET', 'POST'])
    @admin_required
    def admin_journal_edit(journal_id):
        journal = Journal.query.get_or_404(journal_id)

        if request.method == 'POST':
            journal.name = request.form.get('name', journal.name).strip()
            journal.slug = request.form.get('slug', journal.slug).strip() or slugify(journal.name)
            journal.issn = request.form.get('issn', '').strip() or None
            journal.eissn = request.form.get('eissn', '').strip() or None
            journal.description = request.form.get('description', '').strip() or None
            journal.aims_scope = request.form.get('aims_scope', '').strip() or None
            journal.editorial_board = request.form.get('editorial_board', '').strip() or None
            journal.submission_info = request.form.get('submission_info', '').strip() or None
            journal.is_active = ('is_active' in request.form)
            journal.order = int(request.form.get('order', 0) or 0)

            cover = request.files.get('cover_image')
            saved = _save_image(cover, current_app.config['UPLOAD_COVERS'])
            if saved:
                journal.cover_image = saved

            if request.form.get('delete_cover'):
                journal.cover_image = None

            db.session.commit()
            flash('Журнал обновлён', 'success')
            return redirect(url_for('admin_journals'))

        return render_template('admin/journal_edit.html', journal=journal)

    @app.route('/admin/journals/<int:journal_id>/toggle-active', methods=['POST'])
    @admin_required
    def admin_journal_toggle_active(journal_id):
        journal = Journal.query.get_or_404(journal_id)
        journal.is_active = not journal.is_active
        db.session.commit()
        return jsonify({'success': True, 'is_active': journal.is_active})

    @app.route('/admin/journals/<int:journal_id>/delete', methods=['POST'])
    @admin_required
    def admin_journal_delete(journal_id):
        journal = Journal.query.get_or_404(journal_id)
        issue_count = Issue.query.filter_by(journal_id=journal_id).count()
        if issue_count > 0:
            return jsonify({'success': False, 'error': f'Сначала удалите все выпуски ({issue_count})'}), 400
        db.session.delete(journal)
        db.session.commit()
        flash(f'Журнал «{journal.name}» удалён', 'success')
        return jsonify({'success': True})

    # ==================== ВЫПУСКИ ====================
    @app.route('/admin/journal/<int:journal_id>/issues')
    @admin_required
    def admin_issues(journal_id):
        journal = Journal.query.get_or_404(journal_id)
        issues = (
            Issue.query
            .filter_by(journal_id=journal_id)
            .options(db.subqueryload(Issue.articles))
            .order_by(Issue.year.desc(), Issue.number.desc())
            .all()
        )
        return render_template('admin/issues.html', journal=journal, issues=issues)

    @app.route('/admin/journal/<int:journal_id>/issues/add', methods=['GET', 'POST'])
    @admin_required
    def admin_issue_add(journal_id):
        journal = Journal.query.get_or_404(journal_id)

        if request.method == 'POST':
            issue = Issue(
                journal_id=journal_id,
                volume=int(request.form.get('volume') or 0) or None,
                number=int(request.form.get('number', 1)),
                year=int(request.form.get('year', datetime.now().year)),
                publication_date=request.form.get('publication_date', '').strip() or None,
                description=request.form.get('description', '').strip() or None,
                is_published=('is_published' in request.form),
            )

            cover = request.files.get('cover_image')
            saved = _save_image(cover, current_app.config['UPLOAD_COVERS'])
            if saved:
                issue.cover_image = saved

            db.session.add(issue)
            db.session.commit()
            flash(f'Выпуск №{issue.number}/{issue.year} создан', 'success')
            return redirect(url_for('admin_issues', journal_id=journal_id))

        return render_template('admin/issue_edit.html', journal=journal, issue=None)

    @app.route('/admin/issues/<int:issue_id>/edit', methods=['GET', 'POST'])
    @admin_required
    def admin_issue_edit(issue_id):
        issue = Issue.query.options(db.joinedload(Issue.journal)).get_or_404(issue_id)
        journal = issue.journal

        if request.method == 'POST':
            issue.volume = int(request.form.get('volume') or 0) or None
            issue.number = int(request.form.get('number', issue.number))
            issue.year = int(request.form.get('year', issue.year))
            issue.publication_date = request.form.get('publication_date', '').strip() or None
            issue.description = request.form.get('description', '').strip() or None
            issue.is_published = ('is_published' in request.form)

            cover = request.files.get('cover_image')
            saved = _save_image(cover, current_app.config['UPLOAD_COVERS'])
            if saved:
                issue.cover_image = saved

            if request.form.get('delete_cover'):
                issue.cover_image = None

            db.session.commit()
            flash('Выпуск обновлён', 'success')
            return redirect(url_for('admin_issues', journal_id=journal.id))

        return render_template('admin/issue_edit.html', journal=journal, issue=issue)

    @app.route('/admin/issues/<int:issue_id>/delete', methods=['POST'])
    @admin_required
    def admin_issue_delete(issue_id):
        issue = Issue.query.get_or_404(issue_id)
        journal_id = issue.journal_id
        db.session.delete(issue)
        db.session.commit()
        flash(f'Выпуск №{issue.number}/{issue.year} удалён', 'success')
        return jsonify({'success': True, 'redirect': url_for('admin_issues', journal_id=journal_id)})

    @app.route('/admin/issues/<int:issue_id>/toggle-published', methods=['POST'])
    @admin_required
    def admin_issue_toggle_published(issue_id):
        issue = Issue.query.get_or_404(issue_id)
        issue.is_published = not issue.is_published
        db.session.commit()
        return jsonify({'success': True, 'is_published': issue.is_published})

    # ==================== СТАТЬИ ====================
    @app.route('/admin/issues/<int:issue_id>/articles/add', methods=['GET', 'POST'])
    @admin_required
    def admin_article_add(issue_id):
        issue = Issue.query.options(db.joinedload(Issue.journal)).get_or_404(issue_id)
        journal = issue.journal

        if request.method == 'POST':
            article = Article(
                issue_id=issue_id,
                title=request.form.get('title', '').strip(),
                title_en=request.form.get('title_en', '').strip() or None,
                abstract=request.form.get('abstract', '').strip() or None,
                abstract_en=request.form.get('abstract_en', '').strip() or None,
                keywords=request.form.get('keywords', '').strip() or None,
                keywords_en=request.form.get('keywords_en', '').strip() or None,
                doi=request.form.get('doi', '').strip() or None,
                pages_from=int(request.form.get('pages_from') or 0) or None,
                pages_to=int(request.form.get('pages_to') or 0) or None,
                language=request.form.get('language', 'ru'),
                is_published=('is_published' in request.form),
            )

            # PDF
            pdf = request.files.get('pdf_file')
            saved = _save_pdf(pdf, current_app.config['UPLOAD_PDFS'])
            if saved:
                article.pdf_file = saved

            db.session.add(article)
            db.session.flush()

            # Авторы
            _process_authors(article)

            # Порядок — в конец
            max_order = db.session.query(db.func.max(Article.order)).filter_by(issue_id=issue_id).scalar() or 0
            article.order = max_order + 1

            db.session.commit()
            flash('Статья добавлена', 'success')
            return redirect(url_for('admin_issue_articles', issue_id=issue_id))

        return render_template('admin/article_edit.html', journal=journal, issue=issue, article=None)

    @app.route('/admin/issues/<int:issue_id>/articles')
    @admin_required
    def admin_issue_articles(issue_id):
        issue = Issue.query.options(db.joinedload(Issue.journal)).get_or_404(issue_id)
        articles = (
            Article.query
            .filter_by(issue_id=issue_id)
            .options(db.subqueryload(Article.authors))
            .order_by(Article.order)
            .all()
        )
        return render_template('admin/articles.html', journal=issue.journal, issue=issue, articles=articles)

    @app.route('/admin/articles/<int:article_id>/edit', methods=['GET', 'POST'])
    @admin_required
    def admin_article_edit(article_id):
        article = Article.query.options(
            db.joinedload(Article.authors),
            db.joinedload(Article.issue).joinedload(Issue.journal)
        ).get_or_404(article_id)
        issue = article.issue
        journal = issue.journal

        if request.method == 'POST':
            article.title = request.form.get('title', article.title).strip()
            article.title_en = request.form.get('title_en', '').strip() or None
            article.abstract = request.form.get('abstract', '').strip() or None
            article.abstract_en = request.form.get('abstract_en', '').strip() or None
            article.keywords = request.form.get('keywords', '').strip() or None
            article.keywords_en = request.form.get('keywords_en', '').strip() or None
            article.doi = request.form.get('doi', '').strip() or None
            article.pages_from = int(request.form.get('pages_from') or 0) or None
            article.pages_to = int(request.form.get('pages_to') or 0) or None
            article.language = request.form.get('language', 'ru')
            article.is_published = ('is_published' in request.form)

            # PDF
            pdf = request.files.get('pdf_file')
            saved = _save_pdf(pdf, current_app.config['UPLOAD_PDFS'])
            if saved:
                article.pdf_file = saved

            if request.form.get('delete_pdf'):
                article.pdf_file = None

            # Обновляем авторов
            ArticleAuthor.query.filter_by(article_id=article.id).delete()
            _process_authors(article)

            db.session.commit()
            flash('Статья обновлена', 'success')
            return redirect(url_for('admin_issue_articles', issue_id=issue.id))

        return render_template('admin/article_edit.html', journal=journal, issue=issue, article=article)

    @app.route('/admin/articles/<int:article_id>/delete', methods=['POST'])
    @admin_required
    def admin_article_delete(article_id):
        article = Article.query.get_or_404(article_id)
        issue_id = article.issue_id
        db.session.delete(article)
        db.session.commit()
        flash('Статья удалена', 'success')
        return jsonify({'success': True, 'redirect': url_for('admin_issue_articles', issue_id=issue_id)})

    @app.route('/admin/articles/<int:article_id>/toggle-published', methods=['POST'])
    @admin_required
    def admin_article_toggle_published(article_id):
        article = Article.query.get_or_404(article_id)
        article.is_published = not article.is_published
        db.session.commit()
        return jsonify({'success': True, 'is_published': article.is_published})

    # ==================== БЭКАПЫ ====================
    @app.route('/admin/backups')
    @admin_required
    def admin_backups():
        base_dir = os.path.dirname(os.path.abspath(__file__))
        backups_dir = os.path.join(base_dir, 'backups')
        os.makedirs(backups_dir, exist_ok=True)

        backups = []
        for f in sorted(os.listdir(backups_dir), reverse=True):
            if f.endswith('.db'):
                path = os.path.join(backups_dir, f)
                size = os.path.getsize(path)
                mtime = datetime.fromtimestamp(os.path.getmtime(path))
                backups.append({'name': f, 'size': size, 'date': mtime})

        db_path = os.path.join(base_dir, 'instance', 'publisher.db')
        db_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0

        return render_template('admin/backups.html', backups=backups, db_size=db_size)

    @app.route('/admin/backups/create', methods=['POST'])
    @admin_required
    def admin_backup_create():
        from backup import create_backup
        create_backup()
        return jsonify({'success': True, 'message': 'Бэкап создан'})

    @app.route('/admin/backups/download/<filename>')
    @admin_required
    def admin_backup_download(filename):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        backups_dir = os.path.join(base_dir, 'backups')
        safe = secure_filename(filename)
        path = os.path.join(backups_dir, safe)
        if not os.path.exists(path):
            return 'Файл не найден', 404
        return send_file(path, as_attachment=True, download_name=safe)

    # ==================== USERS ====================
    @app.route('/admin/users')
    @admin_required
    def admin_users():
        users = User.query.order_by(User.role.desc(), User.display_name).all()
        return render_template('admin/users.html', users=users)

    @app.route('/admin/users/add', methods=['POST'])
    @admin_required
    def admin_user_add():
        data = request.form
        username = data.get('username', '').strip()
        display_name = data.get('display_name', '').strip()
        password = data.get('password', '').strip()
        role = data.get('role', 'editor')

        if not username or not display_name or not password:
            return jsonify({'success': False, 'error': 'Заполните все поля'}), 400

        if User.query.filter_by(username=username).first():
            return jsonify({'success': False, 'error': 'Логин занят'}), 400

        user = User(username=username, display_name=display_name, role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash(f'Пользователь «{display_name}» создан', 'success')
        return jsonify({'success': True})

    @app.route('/admin/users/<int:user_id>/delete', methods=['POST'])
    @admin_required
    def admin_user_delete(user_id):
        user = User.query.get_or_404(user_id)
        if user.id == current_user.id:
            return jsonify({'success': False, 'error': 'Нельзя удалить себя'}), 400
        db.session.delete(user)
        db.session.commit()
        return jsonify({'success': True})


def _process_authors(article):
    """Парсит авторов из формы и привязывает к статье."""
    names = request.form.getlist('author_name[]')
    names_en = request.form.getlist('author_name_en[]')
    affiliations = request.form.getlist('author_affiliation[]')
    affiliations_en = request.form.getlist('author_affiliation_en[]')
    emails = request.form.getlist('author_email[]')
    orcids = request.form.getlist('author_orcid[]')

    for i, name in enumerate(names):
        if not name.strip():
            continue
        author = ArticleAuthor(
            article_id=article.id,
            full_name=name.strip(),
            full_name_en=names_en[i].strip() if i < len(names_en) else None,
            affiliation=affiliations[i].strip() if i < len(affiliations) else None,
            affiliation_en=affiliations_en[i].strip() if i < len(affiliations_en) else None,
            email=emails[i].strip() if i < len(emails) else None,
            orcid=orcids[i].strip() if i < len(orcids) else None,
            order=i,
        )
        db.session.add(author)
