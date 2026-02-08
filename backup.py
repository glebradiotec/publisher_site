import os
import shutil
from datetime import datetime
from pathlib import Path


def create_backup():
    """Создаёт бэкап БД."""
    base_dir = Path(__file__).parent
    db_path = base_dir / 'instance' / 'publisher.db'

    if not db_path.exists():
        print("БД не найдена, бэкап не создан")
        return None

    backups_dir = base_dir / 'backups'
    backups_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    backup_name = f'publisher_backup_{timestamp}.db'
    backup_path = backups_dir / backup_name

    shutil.copy2(db_path, backup_path)
    print(f"Бэкап создан: {backup_name}")

    # Удаляем старые бэкапы (оставляем последние 10)
    backups = sorted(backups_dir.glob('*.db'), key=lambda f: f.stat().st_mtime, reverse=True)
    for old_backup in backups[10:]:
        old_backup.unlink()
        print(f"Удалён старый бэкап: {old_backup.name}")

    return backup_path
