"""
Migration script: imports data from the old MySQL dump into the new SQLite database.

Old DB structure:
  journals (journ_id, journ_name, link, issn, descript, redkol, cover, jr_active, ...)
  nomera (num_id, jr_num -> journals, num_year, num_num, num_act, ...)
  razdel_numbers (razd_id, number -> nomera.num_id, razd_name, ...)
  articles (art_id, razd_id -> razdel_numbers, art_page, authors, art_name, descript,
            authors_eng, art_name_eng, descript_eng, keyword, keyword_eng, doi, file, ...)

New DB models:
  Journal (id, name, slug, issn, description, is_active)
  Issue (id, journal_id, number, year, is_published)
  Article (id, issue_id, title, title_en, abstract, abstract_en, keywords, keywords_en,
           doi, pages_from, pages_to, pdf_file, is_published)
  ArticleAuthor (id, article_id, full_name, full_name_en, order)
"""
import re
import sys
import html

SQL_FILE = "Old/_live.radiotec_main4.2292296.sql"

# Try multiple encodings
ENCODINGS_TO_TRY = ["utf-8", "cp1251", "cp866", "koi8-r", "latin1"]


def detect_encoding():
    """Detect the best encoding for the SQL file."""
    test_words = ["Радиотехника", "журнал", "статья", "научн"]
    for enc in ENCODINGS_TO_TRY:
        try:
            with open(SQL_FILE, "r", encoding=enc, errors="strict") as f:
                chunk = f.read(500000)
                # Check if we can find known Russian words
                found = sum(1 for w in test_words if w in chunk)
                if found >= 2:
                    print(f"Encoding detected: {enc} (found {found} test words)")
                    return enc
        except (UnicodeDecodeError, UnicodeError):
            continue
    # Fallback
    print("Warning: Could not detect encoding, using utf-8 with replace")
    return "utf-8"


def parse_values(insert_line):
    """Parse MySQL INSERT VALUES into list of tuples.
    Handles: strings with escaped quotes, NULL, numbers, decimals.
    """
    # Find the VALUES part
    m = re.search(r"VALUES\s*", insert_line)
    if not m:
        return []

    data = insert_line[m.end():]
    # Remove trailing semicolon
    data = data.rstrip().rstrip(";")

    rows = []
    current_row = []
    current_val = ""
    in_string = False
    escape_next = False
    paren_depth = 0

    i = 0
    while i < len(data):
        ch = data[i]

        if escape_next:
            current_val += ch
            escape_next = False
            i += 1
            continue

        if ch == "\\" and in_string:
            escape_next = True
            current_val += ch
            i += 1
            continue

        if ch == "'" and not in_string:
            in_string = True
            i += 1
            continue
        elif ch == "'" and in_string:
            # Check for ''
            if i + 1 < len(data) and data[i + 1] == "'":
                current_val += "'"
                i += 2
                continue
            in_string = False
            i += 1
            continue

        if in_string:
            current_val += ch
            i += 1
            continue

        # Not in string
        if ch == "(":
            paren_depth += 1
            if paren_depth == 1:
                current_val = ""
                i += 1
                continue
        elif ch == ")":
            paren_depth -= 1
            if paren_depth == 0:
                # End of row
                current_row.append(current_val.strip())
                rows.append(tuple(current_row))
                current_row = []
                current_val = ""
                i += 1
                continue
        elif ch == "," and paren_depth == 1:
            current_row.append(current_val.strip())
            current_val = ""
            i += 1
            continue
        elif ch == "," and paren_depth == 0:
            i += 1
            continue
        else:
            current_val += ch
            i += 1
            continue

        i += 1

    return rows


def clean_val(val):
    """Convert a parsed value: NULL -> None, numbers -> int/float, strings stay."""
    if val == "NULL" or val == "":
        return None
    # Try number
    try:
        if "." in val:
            return float(val)
        return int(val)
    except ValueError:
        pass
    # Unescape MySQL
    val = val.replace("\\'", "'").replace('\\"', '"').replace("\\n", "\n").replace("\\r", "\r")
    val = val.replace("\\\\", "\\")
    # Clean HTML entities
    val = html.unescape(val)
    return val


def strip_html(text):
    """Remove HTML tags from text."""
    if not text:
        return text
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_table_data(encoding, table_name):
    """Extract all rows from INSERT statements for a table."""
    marker = f"INSERT INTO `{table_name}`"
    all_rows = []
    with open(SQL_FILE, "r", encoding=encoding, errors="replace") as f:
        for line in f:
            if marker in line:
                rows = parse_values(line)
                all_rows.extend(rows)
    return all_rows


def slugify(text):
    """Transliterate and slugify Russian text."""
    translit = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo',
        'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
        'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
        'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'shch',
        'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
    }
    text = text.lower().strip()
    result = []
    for ch in text:
        if ch in translit:
            result.append(translit[ch])
        elif ch.isalnum():
            result.append(ch)
        elif ch in " -_":
            result.append("-")
    slug = re.sub(r"-+", "-", "".join(result)).strip("-")
    return slug or "journal"


def parse_pages(pages_str):
    """Parse pages string like '12-25' or '12' into (from, to)."""
    if not pages_str:
        return None, None
    pages_str = str(pages_str).strip().replace("–", "-").replace("—", "-")
    m = re.match(r"(\d+)\s*[-]\s*(\d+)", pages_str)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.match(r"(\d+)", pages_str)
    if m:
        return int(m.group(1)), None
    return None, None


def run_migration():
    print("=" * 60)
    print("MIGRATION: Old MySQL dump -> New SQLite DB")
    print("=" * 60)

    # Detect encoding
    enc = detect_encoding()

    # Extract data
    print("\nExtracting journals...")
    journals_raw = extract_table_data(enc, "journals")
    print(f"  Found {len(journals_raw)} journals")

    print("Extracting nomera (issues)...")
    nomera_raw = extract_table_data(enc, "nomera")
    print(f"  Found {len(nomera_raw)} issues")

    print("Extracting razdel_numbers (sections)...")
    razdel_raw = extract_table_data(enc, "razdel_numbers")
    print(f"  Found {len(razdel_raw)} sections")

    print("Extracting articles...")
    articles_raw = extract_table_data(enc, "articles")
    print(f"  Found {len(articles_raw)} articles")

    # Build lookup maps
    # razdel_numbers: razd_id -> number (nomera.num_id)
    # Fields: razd_id(0), number(1), razd_name(2), post(3), jr_in_jr(4), r_sort(5), razd_name_eng(6)
    razd_to_nomer = {}
    for row in razdel_raw:
        razd_id = clean_val(row[0])
        nomer_id = clean_val(row[1])
        if razd_id is not None and nomer_id is not None:
            razd_to_nomer[razd_id] = nomer_id

    # nomera: num_id -> (jr_num, num_year, num_num, num_act)
    # Fields: num_id(0), jr_num(1), num_year(2), num_num(3), num_descript(4), num_act(5), file(6), price(7), num_descript_eng(8)
    nomer_map = {}
    for row in nomera_raw:
        num_id = clean_val(row[0])
        jr_num = clean_val(row[1])
        num_year = clean_val(row[2])
        num_num = clean_val(row[3])
        num_act = clean_val(row[5])
        if num_id is not None:
            nomer_map[num_id] = {
                "jr_num": jr_num,
                "year": num_year,
                "number": str(num_num) if num_num else "1",
                "is_published": (num_act == 1),
            }

    # Now import into the Flask app
    print("\nImporting into new database...")

    # Import Flask app
    from app import app, db
    from models import Journal, Issue, Article, ArticleAuthor, User

    with app.app_context():
        # Clear existing data if any
        existing = Journal.query.count()
        if existing > 0:
            print(f"\nDatabase has {existing} journals. Clearing for re-import...")
            ArticleAuthor.query.delete()
            Article.query.delete()
            Issue.query.delete()
            Journal.query.delete()
            db.session.commit()
            print("Cleared existing data.")

        # Import journals
        # Fields: journ_id(0), menu_name(1), type(2), journ_name(3), link(4), redaktor(5),
        #   descript(6), redkol(7), num_year(8), komplekt(9), undercover(10), vak(11),
        #   rospech(12), pochta(13), issn(14), cover(15), numbers(16), title(17),
        #   keywords(18), description(19), jr_active(20), ...many more fields...
        #   menu_name_eng(42?), journ_name_eng(44?), ...
        old_to_new_journal = {}
        journal_order = 0
        for row in journals_raw:
            old_id = clean_val(row[0])
            name = clean_val(row[3]) or clean_val(row[1]) or f"Journal {old_id}"
            name = strip_html(name)
            slug = clean_val(row[4])  # 'link' field used as slug
            if not slug:
                slug = slugify(name)
            slug = slug.lower().strip().replace(" ", "-")

            description = clean_val(row[6])
            if description:
                description = strip_html(description)
                if len(description) > 1000:
                    description = description[:1000] + "..."

            issn = clean_val(row[14])
            is_active = (clean_val(row[20]) == 1) if len(row) > 20 else True

            journal = Journal(
                name=name,
                slug=slug,
                issn=issn,
                description=description,
                editorial_board=strip_html(clean_val(row[7])) if len(row) > 7 else None,
                is_active=is_active,
                order=journal_order,
            )
            db.session.add(journal)
            db.session.flush()
            old_to_new_journal[old_id] = journal.id
            journal_order += 1
            print(f"  Journal: {name} (old_id={old_id} -> new_id={journal.id})")

        # Import issues (nomera)
        old_to_new_issue = {}
        issue_count = 0
        for row in nomera_raw:
            num_id = clean_val(row[0])
            jr_num = clean_val(row[1])
            num_year = clean_val(row[2])
            num_num = clean_val(row[3])
            num_act = clean_val(row[5])

            new_journal_id = old_to_new_journal.get(jr_num)
            if not new_journal_id:
                continue

            # Parse number (can be "5-6" or "1")
            number_str = str(num_num) if num_num else "1"
            try:
                number_int = int(re.match(r"(\d+)", number_str).group(1))
            except (AttributeError, ValueError):
                number_int = 1

            issue = Issue(
                journal_id=new_journal_id,
                number=number_int,
                year=num_year if num_year else 2000,
                is_published=(num_act == 1),
            )
            db.session.add(issue)
            db.session.flush()
            old_to_new_issue[num_id] = issue.id
            issue_count += 1

        print(f"  Imported {issue_count} issues")

        # Import articles
        # Fields: art_id(0), razd_id(1), art_page(2), authors(3), art_name(4),
        #   descript(5), literature(6), authors_eng(7), art_name_eng(8),
        #   descript_eng(9), literature_eng(10), keyword(11), keyword_eng(12),
        #   article_type(13), udk(14), doi(15), citata(16), data_recieved(17),
        #   data_approved(18), data_accepted(19), citata_eng(20), rubr_vak(21),
        #   article_text(22), file(23), price(24)
        article_count = 0
        author_count = 0
        skipped = 0

        for row in articles_raw:
            art_id = clean_val(row[0])
            razd_id = clean_val(row[1])
            art_page = clean_val(row[2])
            authors_str = clean_val(row[3])
            art_name = clean_val(row[4])
            descript = clean_val(row[5])
            authors_eng = clean_val(row[7]) if len(row) > 7 else None
            art_name_eng = clean_val(row[8]) if len(row) > 8 else None
            descript_eng = clean_val(row[9]) if len(row) > 9 else None
            keyword = clean_val(row[11]) if len(row) > 11 else None
            keyword_eng = clean_val(row[12]) if len(row) > 12 else None
            doi = clean_val(row[15]) if len(row) > 15 else None
            pdf_file = clean_val(row[23]) if len(row) > 23 else None

            if not art_name:
                skipped += 1
                continue

            # Resolve issue: article -> razdel -> nomer -> issue
            nomer_id = razd_to_nomer.get(razd_id)
            if nomer_id is None:
                skipped += 1
                continue

            new_issue_id = old_to_new_issue.get(nomer_id)
            if new_issue_id is None:
                skipped += 1
                continue

            # Parse pages
            pages_from, pages_to = parse_pages(art_page)

            # Clean text
            art_name = strip_html(art_name)
            if art_name_eng:
                art_name_eng = strip_html(art_name_eng)
            if descript:
                descript = strip_html(descript)
            if descript_eng:
                descript_eng = strip_html(descript_eng)

            article = Article(
                issue_id=new_issue_id,
                title=art_name,
                title_en=art_name_eng if art_name_eng else None,
                abstract=descript if descript else None,
                abstract_en=descript_eng if descript_eng else None,
                keywords=keyword if keyword else None,
                keywords_en=keyword_eng if keyword_eng else None,
                doi=doi if doi else None,
                pages_from=pages_from,
                pages_to=pages_to,
                pdf_file=pdf_file if pdf_file else None,
                order=article_count,
                is_published=True,
            )
            db.session.add(article)
            db.session.flush()
            article_count += 1

            # Parse authors (comma-separated)
            if authors_str:
                authors_list = [a.strip() for a in authors_str.split(",") if a.strip()]
                authors_eng_list = []
                if authors_eng:
                    authors_eng_list = [a.strip() for a in authors_eng.split(",") if a.strip()]

                for idx, author_name in enumerate(authors_list):
                    author_name = strip_html(author_name)
                    if not author_name:
                        continue
                    eng_name = None
                    if idx < len(authors_eng_list):
                        eng_name = strip_html(authors_eng_list[idx])

                    author = ArticleAuthor(
                        article_id=article.id,
                        full_name=author_name,
                        full_name_en=eng_name,
                        order=idx,
                    )
                    db.session.add(author)
                    author_count += 1

        db.session.commit()

        print(f"\n{'=' * 60}")
        print(f"MIGRATION COMPLETE!")
        print(f"{'=' * 60}")
        print(f"  Journals:  {Journal.query.count()}")
        print(f"  Issues:    {Issue.query.count()}")
        print(f"  Articles:  {Article.query.count()}")
        print(f"  Authors:   {ArticleAuthor.query.count()}")
        print(f"  Skipped:   {skipped} articles (no issue link)")

        # Ensure admin user exists
        if User.query.count() == 0:
            admin = User(username="admin", display_name="Администратор", role="admin")
            admin.set_password("admin2026")
            db.session.add(admin)
            db.session.commit()
            print("  Created admin user (admin / admin2026)")


if __name__ == "__main__":
    run_migration()
