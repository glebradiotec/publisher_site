from flask import render_template, request, jsonify, abort
from sqlalchemy.orm import joinedload, subqueryload

from models import db, Journal, Issue, Article, ArticleAuthor


def normalize_text(text):
    """Нормализация текста для поиска."""
    if not text:
        return ""
    text = text.lower()
    text = text.replace('ё', 'е')
    return text


def register_public_routes(app):
    """Публичные маршруты сайта (без авторизации)."""

    # ==================== ГЛАВНАЯ ====================
    @app.route('/')
    def index():
        """Главная страница — список журналов + последние выпуски."""
        journals = (
            Journal.query
            .filter_by(is_active=True)
            .order_by(Journal.order, Journal.name)
            .all()
        )

        # Последние опубликованные выпуски
        recent_issues = (
            Issue.query
            .filter_by(is_published=True)
            .options(joinedload(Issue.journal))
            .order_by(Issue.year.desc(), Issue.number.desc())
            .limit(6)
            .all()
        )

        # Статистика для главной
        total_articles = (
            db.session.query(db.func.count(Article.id))
            .join(Issue)
            .filter(Issue.is_published == True, Article.is_published == True)
            .scalar() or 0
        )
        stats = {
            'journals': len(journals),
            'issues': Issue.query.filter_by(is_published=True).count(),
            'articles': total_articles,
        }

        # Текущий выпуск (самый свежий с деталями)
        latest_issue = None
        if recent_issues:
            latest_issue = (
                Issue.query
                .filter_by(id=recent_issues[0].id)
                .options(
                    joinedload(Issue.journal),
                    subqueryload(Issue.articles).subqueryload(Article.authors)
                )
                .first()
            )

        # Избранная статья
        featured_article = (
            Article.query
            .join(Issue)
            .join(Journal)
            .filter(Issue.is_published == True, Article.is_published == True)
            .options(
                joinedload(Article.issue).joinedload(Issue.journal),
                joinedload(Article.authors)
            )
            .order_by(Article.id.desc())
            .first()
        )

        return render_template('index.html',
            journals=journals,
            recent_issues=recent_issues,
            stats=stats,
            latest_issue=latest_issue,
            featured_article=featured_article,
        )

    # ==================== ЖУРНАЛЫ ====================
    @app.route('/journals')
    def journals_list():
        """Список всех журналов."""
        journals = (
            Journal.query
            .filter_by(is_active=True)
            .order_by(Journal.order, Journal.name)
            .all()
        )

        # Подсчёт выпусков и статей для каждого журнала
        for journal in journals:
            journal.published_issues_count = (
                Issue.query
                .filter_by(journal_id=journal.id, is_published=True)
                .count()
            )
            journal.articles_count = (
                Article.query
                .join(Issue)
                .filter(Issue.journal_id == journal.id, Article.is_published == True)
                .count()
            )

        total_articles = Article.query.filter_by(is_published=True).count()

        return render_template('journals.html', journals=journals, total_articles=total_articles)

    # ==================== ЖУРНАЛ ====================
    @app.route('/journal/<slug>')
    def journal_page(slug):
        """Страница журнала с архивом выпусков."""
        journal = Journal.query.filter_by(slug=slug, is_active=True).first_or_404()

        issues = (
            Issue.query
            .filter_by(journal_id=journal.id, is_published=True)
            .options(subqueryload(Issue.articles).subqueryload(Article.authors))
            .order_by(Issue.year.desc(), Issue.number.desc())
            .all()
        )

        # Группировка по годам
        years = {}
        for issue in issues:
            years.setdefault(issue.year, []).append(issue)

        # Статистика
        total_issues = len(issues)
        total_articles = sum(
            len([a for a in issue.articles if a.is_published])
            for issue in issues
        )

        # Последний выпуск
        latest_issue = issues[0] if issues else None

        return render_template('journal.html',
            journal=journal, issues=issues, years=years,
            total_issues=total_issues, total_articles=total_articles,
            latest_issue=latest_issue)

    # ==================== ВЫПУСК ====================
    @app.route('/journal/<slug>/issue/<int:issue_id>')
    def issue_page(slug, issue_id):
        """Содержание выпуска — список статей."""
        journal = Journal.query.filter_by(slug=slug, is_active=True).first_or_404()

        issue = (
            Issue.query
            .filter_by(id=issue_id, journal_id=journal.id, is_published=True)
            .options(
                subqueryload(Issue.articles).subqueryload(Article.authors)
            )
            .first_or_404()
        )

        articles = [a for a in issue.articles if a.is_published]

        return render_template('issue.html', journal=journal, issue=issue, articles=articles)

    # ==================== СТАТЬЯ ====================
    @app.route('/article/<int:article_id>')
    def article_page(article_id):
        """Страница статьи с полными метаданными."""
        article = (
            Article.query
            .options(
                joinedload(Article.authors),
                joinedload(Article.issue).joinedload(Issue.journal)
            )
            .get_or_404(article_id)
        )

        if not article.is_published:
            abort(404)

        issue = article.issue
        journal = issue.journal if issue else None

        if issue and journal and not issue.is_published:
            abort(404)

        return render_template('article.html', article=article, issue=issue, journal=journal)

    # ==================== ПОИСК ====================
    @app.route('/search')
    def search():
        """Поиск по статьям."""
        query = request.args.get('q', '').strip()
        results = []

        if query and len(query) >= 2:
            like_pattern = f'%{query}%'
            results = (
                Article.query
                .join(Issue)
                .join(Journal)
                .filter(
                    Issue.is_published == True,
                    Article.is_published == True,
                    db.or_(
                        Article.title.ilike(like_pattern),
                        Article.abstract.ilike(like_pattern),
                        Article.keywords.ilike(like_pattern),
                    )
                )
                .options(
                    joinedload(Article.issue).joinedload(Issue.journal),
                    joinedload(Article.authors)
                )
                .order_by(Article.id.desc())
                .limit(50)
                .all()
            )

            # Дополнительный поиск по авторам
            if not results:
                author_results = (
                    Article.query
                    .join(Issue)
                    .join(Journal)
                    .join(ArticleAuthor)
                    .filter(
                        Issue.is_published == True,
                        Article.is_published == True,
                        ArticleAuthor.full_name.ilike(like_pattern)
                    )
                    .options(
                        joinedload(Article.issue).joinedload(Issue.journal),
                        joinedload(Article.authors)
                    )
                    .order_by(Article.id.desc())
                    .limit(50)
                    .all()
                )
                results = author_results

        return render_template('search.html', query=query, results=results)

    # ==================== API ====================
    @app.route('/api/search')
    def api_search():
        """JSON API для клиентского поиска."""
        query = request.args.get('q', '').strip()
        if not query or len(query) < 2:
            return jsonify([])

        like_pattern = f'%{query}%'
        articles = (
            Article.query
            .join(Issue)
            .join(Journal)
            .filter(
                Issue.is_published == True,
                Article.is_published == True,
                db.or_(
                    Article.title.ilike(like_pattern),
                    Article.abstract.ilike(like_pattern),
                    Article.keywords.ilike(like_pattern),
                )
            )
            .options(
                joinedload(Article.issue).joinedload(Issue.journal),
                joinedload(Article.authors)
            )
            .order_by(Article.id.desc())
            .limit(20)
            .all()
        )

        return jsonify([{
            'id': a.id,
            'title': a.title,
            'authors': a.authors_str,
            'journal': a.issue.journal.name if a.issue and a.issue.journal else '',
            'issue': f'№{a.issue.number}/{a.issue.year}' if a.issue else '',
            'pages': a.pages_str,
            'doi': a.doi or '',
        } for a in articles])

    # ==================== ОШИБКИ ====================
    @app.errorhandler(404)
    def page_not_found(e):
        return render_template('404.html'), 404
