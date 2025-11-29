import os
import time
import json
import sys
import shutil
import subprocess
import winsound
import zipfile
import hashlib
import threading
import requests
import webbrowser 
from datetime import datetime, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

# --- БЛОК 0: СТРОГИЕ ИМПОРТЫ ---
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.layout import Layout
    from rich.live import Live
    from rich.text import Text
    from rich.align import Align
    from rich.prompt import Prompt
    from rich import box
    from plyer import notification
    # PIL должен быть импортирован до pystray для корректной работы иконки
    from PIL import Image
    from pystray import Icon as TrayIcon, Menu as TrayMenu, MenuItem as TrayMenuItem
    from mutagen.mp3 import MP3
    from mutagen.id3 import ID3NoHeaderError
    from flask import Flask, render_template_string, redirect, url_for, request, flash 
except ImportError as e:
    print("❌ КРИТИЧЕСКАЯ ОШИБКА ИМПОРТА:")
    print(f"Не найден модуль: {e}. Пожалуйста, вручную установите все зависимости:")
    print("pip install watchdog rich plyer pystray Pillow Flask mutagen")
    sys.exit(1)


# --- ГЛОБАЛЬНЫЕ КОНСТАНТЫ ---
CONFIG_FILE = "settings_rus.json"
LOG_FILE = "history.log"
APP_NAME = "X4 SORTER"
VERSION = "ULTRA STABLE v10.1" 
DUPLICATE_FOLDER = "98_Дубликаты"
QUARANTINE_FOLDER = "97_Карантин"
WEB_PORT = 5000
# 45 MB лимит для бота Telegram
TELEGRAM_FILE_LIMIT_BYTES = 47185920 

# --- БАЗА РАСШИРЕНИЙ  ---
EXTENSIONS_DB = {
    "01_Изображения": [".jpg", ".png", ".gif", ".webp", ".heic", ".psd", ".ai", ".raw", ".tiff", ".svg", ".ico", ".cr2", ".nef", ".orf"],
    "02_Видео": [".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".vob", ".3gp"],
    "03_Документы": [".pdf", ".docx", ".doc", ".xlsx", ".csv", ".pptx", ".txt", ".rtf", ".epub", ".djvu", ".odt"],
    "04_Архивы": [".zip", ".rar", ".7z", ".tar", ".gz", ".iso", ".torrent", ".bz2"],
    "05_Аудио": [".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a", ".mid"],
    "06_Программы": [".exe", ".msi", ".bat", ".apk", ".jar", ".cmd", ".appimage", ".deb", ".rpm"],
    "07_Код_и_Скрипты": [".py", ".js", ".html", ".css", ".json", ".cpp", ".c", ".php", ".sql", ".ts", ".go", ".rs", ".lua", ".sh"],
    "08_3D_и_Графика": [".obj", ".fbx", ".blend", ".stl", ".dae"],
    "09_Шрифты": [".ttf", ".otf", ".woff", ".woff2"],
    "10_Системные": [".dll", ".sys", ".cfg", ".ini", ".dmp", ".log", ".bak"],
}

# --- НАСТРОЙКИ ПО УМОЛЧАНИЮ ---
# Убеждаемся, что все пути сохраняются корректно при первом запуске
DEFAULT_CONFIG = {
    "theme": "Cyberpunk",
    "first_run_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 
    "source_folder": str(Path.home() / "Downloads"), 
    "base_destination": str(Path(__file__).resolve().parent), 
    "stats": {
        "total_files": 0, 
        "last_run": "", 
        "file_type_counts": {},
        "file_first_seen": {} 
    },
    "features": {
        "sort_by_date": True, 
        "sound_enabled": True,
        "notifications": True,
        "auto_unpack": False,
        "deep_clean": True,
        "deduplication": True,
        "quarantine_mode": True, 
        "retention_days": 30,
        "sort_by_metadata": True
    },
    "telegram": {
        "enabled": False,
        "token": "",
        "chat_id": "",
        "upload_enabled": False, 
        # Устанавливаем лимит по умолчанию 45 MB, но даем возможность изменить
        "upload_max_size_mb": 45, 
        "notify_duplicate": True, 
        "notify_quarantine": True, 
        "notify_success": True 
    },
    "quarantine_blacklist": [".exe", ".bat", ".vbs", ".js", ".apk", ".msi"],
    "ignore_list": [".tmp", ".crdownload", ".part", ".ini", "desktop.ini", CONFIG_FILE, LOG_FILE]
}

# --- ЦВЕТОВЫЕ ТЕМЫ ---
THEMES = {
    "Hacker": {"primary": "#00ff00", "secondary": "#00cc00", "dark": "#111111", "medium": "#1a1a1a", "text": "white", "border": "green", "accent": "#00ffcc"},
    "Cyberpunk": {"primary": "#ff33cc", "secondary": "#00ffff", "dark": "#200a28", "medium": "#2f1138", "text": "white", "border": "magenta", "accent": "#ff66ff"},
    "Ocean": {"primary": "#00aaff", "secondary": "#00ccff", "dark": "#0a1f28", "medium": "#113344", "text": "white", "border": "blue", "accent": "#66ccff"},
    "Royal": {"primary": "#ffcc00", "secondary": "#ccaa00", "dark": "#282810", "medium": "#383815", "text": "black", "border": "gold1", "accent": "#ffdd55"}
}

# Инициализация консоли Rich
console = Console()

# --- МЕНЕДЖЕР НАСТРОЕК ---
class ConfigManager:
    """Управляет загрузкой, сохранением и целостностью файла настроек."""
    def __init__(self):
        self.data = self.load()
        self.update_theme()

    def load(self):
        path = Path(__file__).resolve().parent / CONFIG_FILE
        if not path.exists(): return self.save(DEFAULT_CONFIG)
        try:
            with open(path, 'r', encoding='utf-8') as f: data = json.load(f)
            # Всегда проверяем целостность после загрузки
            return self.check_integrity(data) 
        except Exception as e: 
            # Если файл битый, сбрасываем на дефолтные
            print(f"⚠️ Предупреждение: Ошибка чтения настроек ({e}). Использование настроек по умолчанию.")
            return self.save(DEFAULT_CONFIG)

    def check_integrity(self, data):
        changed = False
        
        def check_dict(default, current):
            nonlocal changed
            # Проверяем на наличие новых ключей из DEFAULT
            for k, v in default.items():
                if k not in current:
                    current[k] = v
                    changed = True
                elif isinstance(v, dict) and isinstance(current.get(k), dict):
                    # Рекурсивный вызов для вложенных словарей
                    check_dict(v, current[k])
                # Обработка случая, когда в текущих настройках не словарь, а должен быть
                elif isinstance(v, dict) and not isinstance(current.get(k), dict):
                     current[k] = v.copy() # Перезаписываем неверный тип на дефолтный словарь
                     changed = True

        check_dict(DEFAULT_CONFIG, data)
        
        # ИСПРАВЛЕНИЕ 3: Обработка старого ключа organize_by_date -> sort_by_date
        if 'organize_by_date' in data.get('features', {}): 
             data['features']['sort_by_date'] = data['features'].pop('organize_by_date')
             changed = True
        
        if changed: self.save(data)
        return data

    def save(self, data=None):
        if data: self.data = data
        path = Path(__file__).resolve().parent / CONFIG_FILE
        try:
             # Гарантируем корректное сохранение путей (Path в str)
             temp_data = self.data.copy()
             temp_data['source_folder'] = str(Path(temp_data['source_folder']).resolve())
             temp_data['base_destination'] = str(Path(temp_data['base_destination']).resolve())
             
             with open(path, 'w', encoding='utf-8') as f:
                json.dump(temp_data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"⚠️ Предупреждение: Не удалось сохранить настройки в {path}. {e}")
        return self.data

    def update_val(self, category, key, value):
        if category:
            if category not in self.data: self.data[category] = {} # Безопасность
            self.data[category][key] = value
        else:
            self.data[key] = value
        self.save()
        self.update_theme()

    def increment_stats(self, category_name=None, filename=None):
        self.data["stats"]["total_files"] += 1
        self.data["stats"]["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        if category_name:
            if category_name not in self.data["stats"]["file_type_counts"]:
                 self.data["stats"]["file_type_counts"][category_name] = 0
            self.data["stats"]["file_type_counts"][category_name] += 1

        if filename and filename not in self.data["stats"]["file_first_seen"]:
            self.data["stats"]["file_first_seen"][filename] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        self.save()

    def get_file_first_seen(self, filename):
        return self.data["stats"]["file_first_seen"].get(filename, "N/A")

    def update_theme(self):
        t_name = self.data.get("theme", "Hacker")
        self.current_theme = THEMES.get(t_name, THEMES["Hacker"])

cfg = ConfigManager()

# --- УТИЛИТЫ ---
def calculate_hash(path, algorithm='sha256'):
    hasher = hashlib.new(algorithm)
    try:
        with open(path, 'rb') as file:
            while True:
                chunk = file.read(8192)
                if not chunk: break
                hasher.update(chunk)
        return hasher.hexdigest()
    except:
        return None

def send_telegram_message(message, level="INFO"):
    tg_conf = cfg.data.get('telegram', {}) # Безопасный доступ
    if not tg_conf.get('enabled') or not tg_conf.get('token') or not tg_conf.get('chat_id'): return

    should_send = False
    emoji = "ℹ️"
    if level == "SUCCESS" and tg_conf.get('notify_success'): emoji = "✅"; should_send = True
    elif level == "DUPLICATE" and tg_conf.get('notify_duplicate'): emoji = "🗃️"; should_send = True
    elif level == "QUARANTINE" and tg_conf.get('notify_quarantine'): emoji = "⚠️"; should_send = True
    elif level == "ERROR": emoji = "🚨"; should_send = True
    elif level == "INFO": should_send = True # Отправляем информационные сообщения всегда, если включено
    
    if not should_send: return
    
    final_message = f"{emoji} *{APP_NAME} Уведомление*:\n\n{message}"

    url = f"https://api.telegram.org/bot{tg_conf['token']}/sendMessage"
    payload = {
        'chat_id': tg_conf['chat_id'],
        'text': final_message,
        # Экранирование символов Markdown V2, которые могут быть в путях/именах
        'parse_mode': 'Markdown',
    }
    try:
        requests.post(url, data=payload, timeout=5)
    except:
        pass

def send_file_to_telegram(file_path):
    tg_conf = cfg.data.get('telegram', {})
    if not tg_conf.get('enabled') or not tg_conf.get('token') or not tg_conf.get('chat_id') or not tg_conf.get('upload_enabled'): 
        return False, "Загрузка в ТГ отключена"
    
    token = tg_conf['token']
    chat_id = tg_conf['chat_id']
    
    try:
        file_size = os.path.getsize(file_path)
    except OSError:
        return False, "Файл не существует или недоступен."
    
    upload_limit = tg_conf.get('upload_max_size_mb', 45) * 1024 * 1024
    if file_size > upload_limit:
        return False, f"Файл слишком большой ({file_size/1024/1024:.2f}MB). Лимит: {upload_limit/1024/1024:.0f}MB."

    ext = Path(file_path).suffix.lower()
    if ext in [".jpg", ".png", ".gif", ".webp"]: method = 'sendPhoto'; param_name = 'photo'
    elif ext in [".mp4", ".mkv", ".mov"]: method = 'sendVideo'; param_name = 'video'
    elif ext in [".mp3", ".wav", ".flac"]: method = 'sendAudio'; param_name = 'audio'
    else: method = 'sendDocument'; param_name = 'document'

    url = f"https://api.telegram.org/bot{token}/{method}"
    
    try:
        with open(file_path, 'rb') as f:
            files = {param_name: f}
            first_seen_date = cfg.get_file_first_seen(Path(file_path).name)
            
            # Безопасный вывод пути относительно base_destination
            try:
                relative_path = Path(file_path).relative_to(cfg.data['base_destination'])
            except ValueError:
                relative_path = Path(file_path).name
                
            data = {
                'chat_id': chat_id, 
                'caption': f"📂 *Отсортировано:* `{Path(file_path).name}`\n\n_Локация:_ `{relative_path}`\n_Первое обнаружение:_ {first_seen_date}", 
                'parse_mode': 'Markdown'
            }
            response = requests.post(url, files=files, data=data, timeout=60)
            
            if response.status_code == 200:
                return True, "Файл успешно загружен в Telegram."
            else:
                return False, f"Ошибка API Telegram ({response.status_code}): {response.text}"
    except Exception as e:
        return False, f"Критическая ошибка загрузки: {e}"


def get_metadata_date(file_path):
    path = Path(file_path)
    
    # Изображения (EXIF Date/Time Original - 36867)
    if path.suffix.lower() in [".jpg", ".jpeg", ".tiff"]:
        try:
            img = Image.open(path)
            # Необходимо явно вызвать load(), чтобы гарантировать чтение метаданных
            img.load() 
            exif_data = img._getexif()
            if exif_data and 36867 in exif_data:
                return datetime.strptime(exif_data[36867], '%Y:%m:%d %H:%M:%S').date()
        except: pass
    
    # MP3 (ID3v2)
    elif path.suffix.lower() in [".mp3"]:
        try:
            audio = MP3(path)
            # TDRC (Recording Date) - более современный тег
            if 'TDRC' in audio:
                # TDRC может быть диапазоном или датой, берем только год
                year_str = str(audio['TDRC']).split('-')[0].split()[0]
                if len(year_str) == 4 and year_str.isdigit():
                    return datetime.strptime(year_str, '%Y').date()
            # TYER (Year) - старый тег
            elif 'TYER' in audio:
                year_str = str(audio['TYER']).split()[0]
                if len(year_str) == 4 and year_str.isdigit():
                    return datetime.strptime(year_str, '%Y').date()
        except ID3NoHeaderError: pass
        except: pass
    
    return None

def get_metadata_folder(file_path):
    path = Path(file_path)
    # Безопасный доступ к настройке
    if not cfg.data.get('features', {}).get('sort_by_metadata'): return None 
    
    if path.suffix.lower() in [".mp3"]:
        try:
            audio = MP3(path)
            # TPE1 (Artist) и TALB (Album)
            # .get() возвращает список объектов ID3Value, берем первый элемент
            artist_list = audio.get('TPE1', [])
            album_list = audio.get('TALB', [])
            
            artist = str(artist_list[0]).strip() if artist_list else ""
            album = str(album_list[0]).strip() if album_list else ""
            
            if not artist or artist == "Unknown Artist": artist = "Неизвестный Исполнитель"
            if not album or album == "Unknown Album": album = "Неизвестный Альбом"
            
            # Функция для очистки имени от недопустимых символов
            def sanitize(name):
                 # Удаляем символы, недопустимые в именах папок Windows/Linux
                 invalid_chars = '<>:"/\\|?*\n'
                 clean_name = "".join(c for c in name if c not in invalid_chars).strip()
                 # Заменяем несколько пробелов на один
                 return ' '.join(clean_name.split())
            
            clean_artist = sanitize(artist)
            clean_album = sanitize(album)
            
            # Только если удалось извлечь осмысленные данные
            if clean_artist and clean_album and clean_artist != "Неизвестный Исполнитель":
                return Path(clean_artist) / clean_album
        except: pass
    
    return None

# --- ГЛАВНЫЙ ДВИЖОК СОРТИРОВКИ ---
class CoreSorter(FileSystemEventHandler):
    def __init__(self, ui_callback=None):
        self.ui_callback = ui_callback
        self._is_paused = False
        self._lock = threading.Lock() # Добавлен лок для безопасной работы с переменными состояния
        
        # ИСПРАВЛЕНИЕ 1: Инициализация ThreadPoolExecutor перед вызовом reload_settings
        self.executor = ThreadPoolExecutor(max_workers=5) 
        self._retention_thread = None 
        
        self.reload_settings() 

        # ИСПРАВЛЕНИЕ 2: Запуск потока очистки и хранения в отдельном демон-потоке
        # Гарантируем, что поток запускается только один раз
        if not self._retention_thread or not self._retention_thread.is_alive():
             self._retention_thread = threading.Thread(target=self._worker_retention_policy, daemon=True)
             self._retention_thread.start()


    def reload_settings(self):
        # Перезагрузка настроек
        self.config = cfg.load()
        self.ext_map = {ext.lower(): folder for folder, exts in EXTENSIONS_DB.items() for ext in exts}
        
        s_path = self.config['source_folder']
        
        try:
            # ИСПРАВЛЕНИЕ 7: Убеждаемся, что пути корректно разрешаются
            self.src = Path(s_path).resolve() 
            if not self.src.exists():
                # Fallback: Если папка не найдена, ставим Downloads, но предупреждаем
                default_src = Path.home() / "Downloads"
                self.src = default_src.resolve() if default_src.exists() else Path(__file__).resolve().parent
                if not self.src.exists():
                     print(f"⚠️ Папка источника '{s_path}' не найдена. Проверьте настройки.")
                self.config['source_folder'] = str(self.src)
                cfg.save(self.config)
                
        except Exception as e:
            print(f"Критическая ошибка пути источника: {e}. Проверьте путь в settings_rus.json.")
            # Не завершаем программу, а используем рабочий путь
            self.src = Path(__file__).resolve().parent
            self.config['source_folder'] = str(self.src)
            cfg.save(self.config)

        self.dest = Path(self.config['base_destination']).resolve()
        self.dest.mkdir(parents=True, exist_ok=True)
        self.duplicate_dir = self.dest / DUPLICATE_FOLDER
        self.quarantine_dir = self.dest / QUARANTINE_FOLDER
        self.duplicate_dir.mkdir(parents=True, exist_ok=True)
        self.quarantine_dir.mkdir(parents=True, exist_ok=True)
        

    # --- ИСПРАВЛЕННЫЙ ПОТОК ХРАНЕНИЯ/ОЧИСТКИ ---
    def _worker_retention_policy(self):
        # Поток для периодического запуска хранения и очистки
        while True:
            # Ждем 24 часа для следующей проверки
            time.sleep(timedelta(hours=24).total_seconds()) 
            
            self.config = cfg.load()
            
            with self._lock:
                if self._is_paused: continue
            
            # 1. Политика хранения (Retention)
            days = self.config['features'].get('retention_days', 30)
            if days > 0:
                cutoff_date = datetime.now() - timedelta(days=days)
                for folder in [self.duplicate_dir, self.quarantine_dir]:
                    self.log_action(f"Начата проверка хранения: {folder.name}", "СИСТЕМА")
                    for item in folder.iterdir():
                        if item.is_file():
                            try:
                                # Проверка даты модификации файла
                                if datetime.fromtimestamp(item.stat().st_mtime) < cutoff_date:
                                    item.unlink()
                                    self.log_action(item.name, folder.name, "УДАЛЕНО (Срок)")
                            except Exception as e:
                                self.log_action(item.name, folder.name, f"Ошибка удаления: {e}")

            # 2. Периодическая очистка пустых папок (Cleanup)
            if self.config['features'].get('deep_clean'):
                 # Запускаем Cleanup через executor, чтобы не блокировать поток
                 self.executor.submit(self._worker_cleanup) 


    # --- Worker Process ---
    def _worker_process(self, file_path_str):
        path = Path(file_path_str).resolve()
        
        # Обновляем конфиг на случай, если он был изменен в вебе/консоли
        self.config = cfg.load() 
        
        if not path.exists() or path.is_dir(): return
        
        # Проверка игнорируемых файлов
        if path.suffix.lower() in self.config['ignore_list'] or path.name in self.config['ignore_list']: 
            return
        
        cfg.increment_stats(filename=path.name)
        
        # Режим карантина (Черный список)
        if self.config['features'].get('quarantine_mode') and path.suffix.lower() in self.config['quarantine_blacklist']:
            self.move_to_quarantine(path, "Подозрительное расширение (ЧС)")
            return

        ext = path.suffix.lower()
        # Использование get() для безопасного доступа к категориям
        category_name = self.ext_map.get(ext, f"99_Прочее\\{ext.replace('.', '').upper()}")
        target_dir = self.dest / category_name
        
        # Сортировка по метаданным
        meta_subfolder = get_metadata_folder(path)
        if meta_subfolder: target_dir = target_dir / meta_subfolder
        
        # ИСПРАВЛЕНИЕ 3: Используем 'sort_by_date'
        if self.config['features'].get('sort_by_date'): 
            sort_date = get_metadata_date(path)
            if not sort_date:
                # Если метаданных нет, берем дату создания
                try:
                    stat = path.stat()
                    sort_date = datetime.fromtimestamp(stat.st_ctime).date()
                except:
                    # Fallback: дата сегодняшнего дня
                    sort_date = datetime.now().date()
            
            target_dir = target_dir / str(sort_date.year) / sort_date.strftime("%m_%B")

        target_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            # Обработка архивов
            if self.config['features'].get('auto_unpack') and ext in [".zip", ".rar", ".7z"]:
                self.handle_archive(path, target_dir, category_name)
            else:
                dest_path = self.move_safe(path, target_dir, category_name)
                if dest_path:
                    self.attempt_telegram_upload(dest_path)
                    
        except Exception as e:
            self.move_to_quarantine(path, f"Ошибка обработки: {e}")
        
        # Запуск очистки пустых папок после перемещения
        if self.config['features'].get('deep_clean'): self.executor.submit(self._worker_cleanup)

    # --- move_safe ---
    def move_safe(self, src, folder, category_name):
        
        # 1. Детекция дубликатов
        if self.config['features'].get('deduplication'):
            src_hash = calculate_hash(src)
            if src_hash:
                # Итерация по существующим файлам в целевой папке
                for existing_file in folder.iterdir():
                    if existing_file.is_file() and calculate_hash(existing_file) == src_hash:
                        self._log_and_move_duplicate(src, existing_file.name)
                        return None 
        
        # 2. Обработка конфликтов имен
        dest_file = folder / src.name
        if dest_file.exists():
            ts = datetime.now().strftime("_%Y%m%d_%H%M%S")
            dest_file = folder / f"{src.stem}{ts}{src.suffix}"
            
        # 3. Перемещение файла
        try:
            # Используем shutil.move для лучшей кросс-платформенной совместимости
            # и возможности перемещения между различными дисками
            shutil.move(str(src.resolve()), str(dest_file.resolve())) 
            self.log_success(dest_file.name, category_name, local_move=True)
            return dest_file 
        except Exception as e:
            self.move_to_quarantine(src, f"Критическая ошибка перемещения: {e}")
            return None

    # --- log_success ---
    def log_success(self, filename, category_name, local_move=False):
        cfg.increment_stats(category_name=category_name) 
        self.log_action(filename, category_name)
        if local_move: 
            if self.config['features'].get('sound_enabled'): 
                try: winsound.PlaySound("SystemExclamation", winsound.SND_ASYNC)
                except: pass
            first_seen_date = cfg.get_file_first_seen(filename)
            self._notify_event(f"Файл: `{filename}` отсортирован в категорию: *{category_name}*.\n_Обнаружен:_ {first_seen_date}", level="SUCCESS")


    # --- move_to_quarantine ---
    def move_to_quarantine(self, src, reason):
        quarantine_file = self.quarantine_dir / src.name
        counter = 1
        while quarantine_file.exists():
            quarantine_file = self.quarantine_dir / f"{src.stem}_({counter}){src.suffix}"
            counter += 1
        
        try:
            # Используем shutil.move для безопасности
            shutil.move(str(src.resolve()), str(quarantine_file.resolve()))
            first_seen_date = cfg.get_file_first_seen(src.name)
            send_telegram_message(f"Файл: `{src.name}` перемещен в карантин.\n*Причина:* {reason}\n_Обнаружен:_ {first_seen_date}", level="QUARANTINE")
            self.log_action(src.name, QUARANTINE_FOLDER, reason)
        except Exception as e:
            self.log_action(src.name, "ОШИБКА", f"Не удалось переместить в карантин: {e}")

    # --- _log_and_move_duplicate ---
    def _log_and_move_duplicate(self, src_path, original_name):
        dup_file = self.duplicate_dir / src_path.name
        counter = 1
        while dup_file.exists():
            dup_file = self.duplicate_dir / f"{src_path.stem}_({counter}){src_path.suffix}"
            counter += 1
        
        try:
            # Используем shutil.move для безопасности
            shutil.move(str(src_path.resolve()), str(dup_file.resolve()))
            first_seen_date = cfg.get_file_first_seen(src_path.name)
            send_telegram_message(f"Файл: `{src_path.name}` является дубликатом. Оригинал: `{original_name}`.\n_Обнаружен:_ {first_seen_date}", level="DUPLICATE")
            self.log_action(src_path.name, DUPLICATE_FOLDER, f"Оригинал: {original_name}")
        except Exception as e:
            self.log_action(src_path.name, "ОШИБКА", f"Не удалось переместить дубликат: {e}")


    def pause(self): 
        with self._lock: 
            self._is_paused = True
    
    def resume(self): 
        with self._lock: 
            self._is_paused = False

    def on_created(self, event):
        if not event.is_directory:
            # Даем системе время завершить запись файла
            time.sleep(1.0) 
            self.submit_task(event.src_path)

    def submit_task(self, path):
        with self._lock:
            if not self._is_paused: self.executor.submit(self._worker_process, path)

    def force_scan(self):
        self.executor.submit(self._worker_force_scan)

    def _worker_force_scan(self):
        self.config = cfg.load() 
        self._notify_event("Начато принудительное сканирование.")
        for item in self.src.iterdir():
            if item.is_file(): self._worker_process(str(item.resolve()))
        self._notify_event("Принудительное сканирование завершено.")

    def attempt_telegram_upload(self, file_path):
        if cfg.data.get('telegram', {}).get('upload_enabled'):
            success, message = send_file_to_telegram(file_path)
            
            if success:
                self.log_action(Path(file_path).name, "TELEGRAM", "Успешно загружено")
            else:
                self.log_action(Path(file_path).name, "TELEGRAM ОШИБКА", message)
                
    def _notify_event(self, message, level="INFO"):
        send_telegram_message(message, level=level) 
        
        if level == "ERROR":
            notification.notify(title="КРИТИЧЕСКАЯ ОШИБКА", message=message, app_name=APP_NAME, timeout=5)
        # Отправляем системное уведомление только при успехе и если включено в настройках
        elif level == "SUCCESS" and cfg.data['features'].get('notifications'):
            # Ограничиваем сообщение для Pop-up
            try:
                short_message = message.split('\n')[0].replace("`", "")
                notification.notify(title="Файл отсортирован", message=short_message, app_name=APP_NAME, timeout=2)
            except:
                 pass


    def log_action(self, filename, where, details=""):
        ts = datetime.now().strftime("%H:%M:%S")
        log_path = Path(__file__).resolve().parent / LOG_FILE
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] {filename} -> {where}. {details}\n")
            if self.ui_callback: 
                 # Безопасный вызов колбэка
                 try: self.ui_callback()
                 except: pass 
        except Exception as e:
            print(f"[{ts}] ОШИБКА ЛОГА: {filename}. {e}")

    def handle_archive(self, src, folder, category_name):
        unpack_path = folder / src.stem
        unpack_path.mkdir(parents=True, exist_ok=True)
        try:
            # Использование shutil.unpack_archive для zip, tar.gz, tar.bz2.
            # Для 7z и rar требуется внешняя утилита, но для стандартного функционала достаточно.
            # Если файл не является стандартным, shutil.unpack_archive выкинет ошибку.
            shutil.unpack_archive(str(src.resolve()), str(unpack_path.resolve()))
            # Перемещаем сам архив в папку с содержимым
            shutil.move(str(src.resolve()), str(unpack_path / src.name).resolve())
            self._notify_event(f"📦 Архив: `{src.name}` успешно распакован в папку: `{unpack_path.name}`", level="SUCCESS")
            self.log_success(f"📦 {src.name}", category_name, local_move=True)
        except (shutil.ReadError, zipfile.BadZipFile, EOFError) as e:
            # Если архив нечитаем, перемещаем в карантин
            self.move_to_quarantine(src, f"Не удалось распаковать архив: {e}")
        except Exception as e:
            self.move_to_quarantine(src, f"Ошибка распаковки: {e}")


    # --- _worker_cleanup ---
    def _worker_cleanup(self):
        self.config = cfg.load()
        if self._is_paused or not self.config['features'].get('deep_clean'): return
        
        # Включаем для очистки только папку назначения, избегая мусора в папке источника
        all_root_dirs = set([self.dest.resolve()])
        
        # Обходим все директории от корня назначения до листьев
        for root in all_root_dirs:
            if not root.is_dir(): continue
            
            # Проход по всем подпапкам в обратном порядке (от самых глубоких)
            # Path.rglob('*') возвращает и файлы, и папки. Сортировка по длине parts гарантирует, что мы удаляем сначала листья.
            all_paths = list(root.rglob('*'))
            for current_dir in sorted(all_paths, key=lambda p: len(p.parts), reverse=True):
                if current_dir.is_dir() and current_dir != root:
                    # Исключаем системные папки
                    if current_dir.name in [DUPLICATE_FOLDER, QUARANTINE_FOLDER]: continue
                    
                    try:
                        # Проверяем, пуста ли папка
                        if not any(current_dir.iterdir()):
                            current_dir.rmdir()
                            self.log_action(f"Папка {current_dir.name}", "ОЧИСТКА", "Удалена пустая директория")
                    except OSError as e:
                        # OSError 39 (Directory not empty) - стандартная ошибка, игнорируем
                        if "Directory not empty" not in str(e):
                            self.log_action(current_dir.name, "ОЧИСТКА ОШИБКА", f"Не удалось удалить: {e}")
                    except Exception as e:
                        self.log_action(current_dir.name, "ОЧИСТКА ОШИБКА", f"Критическая ошибка: {e}")


# --- СИСТЕМНЫЙ ТРЕЙ И ВЕБ-ДАШБОРД (Глобальные инстансы) ---
core_sorter_instance = None
observer_instance = None

def setup_background_tasks():
    global core_sorter_instance, observer_instance
    
    # Инициализация CoreSorter
    if not core_sorter_instance:
         # Передаем заглушку-колбэк
        core_sorter_instance = CoreSorter(ui_callback=lambda: None) 

    # Инициализация Watchdog Observer
    if not observer_instance:
        observer_instance = Observer()
        observer_instance.schedule(core_sorter_instance, str(core_sorter_instance.src.resolve()), recursive=False)
        
    # Запуск Observer, если он не запущен
    if not observer_instance.is_alive():
        observer_instance.start()
        send_telegram_message("Система X4 Sorter запущена в фоновом режиме.")

def start_tray(icon):
    setup_background_tasks()
    icon.visible = True

def on_pause_resume(icon, item):
    global core_sorter_instance
    if core_sorter_instance:
        if core_sorter_instance._is_paused:
            core_sorter_instance.resume()
            send_telegram_message("Сортировка Возобновлена.", level="INFO")
        else:
            core_sorter_instance.pause()
            send_telegram_message("Сортировка Приостановлена.", level="INFO")
        
        # Обновляем меню трея, чтобы изменить текст кнопки
        icon.menu = create_tray_menu()

def on_open_dashboard(icon, item):
    webbrowser.open(f"http://127.0.0.1:{WEB_PORT}/")

def on_exit(icon, item):
    global observer_instance, core_sorter_instance
    if observer_instance and observer_instance.is_alive(): observer_instance.stop()
    if core_sorter_instance and core_sorter_instance.executor: core_sorter_instance.executor.shutdown()
    try: send_telegram_message("Система X4 Sorter остановлена.")
    except: pass
    icon.stop()
    # Критическое завершение для потока pystray
    os._exit(0) 

def create_tray_menu():
    global core_sorter_instance
    # Проверка на существование инстанса перед доступом к _is_paused
    is_paused = core_sorter_instance._is_paused if core_sorter_instance else False
    status_text = '▶️ Возобновить' if is_paused else '⏸️ Пауза'
    
    # Используем lambda для защиты от ошибок, если core_sorter_instance еще не инициализирован
    force_scan_action = lambda icon, item: core_sorter_instance.force_scan() if core_sorter_instance else None

    return TrayMenu(
        TrayMenuItem(status_text, on_pause_resume),
        TrayMenuItem('🖥️ Веб-Дашборд', on_open_dashboard),
        TrayMenuItem('🚀 Принудительное сканирование', force_scan_action),
        TrayMenu.SEPARATOR,
        TrayMenuItem('❌ Выход', on_exit)
    )

def run_tray():
    # Создаем простую серую иконку
    image = Image.new('RGB', (64, 64), color = '#202020')
    # Добавляем в инстанс icon ссылку на функцию создания меню (для динамического обновления)
    icon = TrayIcon('X4 Sorter', image, 'X4 Sorter', create_tray_menu())
    # Запускаем трей в цикле
    icon.run(setup=start_tray)

# --- FLASK WEB DASHBOARD ---
app = Flask(__name__)
# ВАЖНО: Устанавливаем секретный ключ для flash сообщений
app.config['SECRET_KEY'] = 'super_secret_key_for_X4_sorter' 

# HTML_TEMPLATE - Полностью переписан для динамического дизайна
def generate_dynamic_css(theme_name):
    t = THEMES.get(theme_name, THEMES["Cyberpunk"])
    return f"""
        :root {{
            --color-primary: {t['primary']};
            --color-secondary: {t['secondary']};
            --color-dark: {t['dark']};
            --color-medium: {t['medium']};
            --color-light: {t['text']};
            --color-error: #ff3366;
            --color-accent: {t['accent']};
            --color-pause: #cc3333;
        }}
        body {{ 
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
            background: var(--color-dark); 
            color: var(--color-light); 
            margin: 0; 
            padding: 40px 20px; 
            transition: background-color 0.5s;
        }}
        .container {{ 
            max-width: 1200px; 
            margin: auto; 
            background: var(--color-medium); 
            padding: 40px; 
            border-radius: 15px; 
            box-shadow: 0 15px 40px rgba(0,0,0,0.7); 
            border: 1px solid var(--color-secondary);
        }}
        h1 {{ 
            color: var(--color-primary); 
            border-bottom: 4px solid var(--color-accent); 
            padding-bottom: 15px; 
            margin-bottom: 35px;
            text-shadow: 0 0 10px var(--color-primary);
            font-size: 2.5em;
        }}
        h2 {{ 
            color: var(--color-secondary); 
            margin-top: 35px; 
            margin-bottom: 20px;
            font-size: 1.8em;
        }}
        .status {{ 
            background: linear-gradient(90deg, var(--color-secondary), var(--color-primary)); 
            padding: 20px; 
            border-radius: 10px; 
            margin-bottom: 30px; 
            text-align: center; 
            font-size: 1.3em;
            color: var(--color-dark);
            box-shadow: 0 5px 20px rgba(0,0,0,0.5);
            font-weight: bold;
        }}
        .status.paused {{
            background: linear-gradient(90deg, var(--color-pause), #990000);
            color: var(--color-light);
        }}
        .logs {{ 
            background: #111; 
            padding: 25px; 
            border-radius: 10px; 
            max-height: 400px; 
            overflow-y: scroll; 
            white-space: pre-wrap; 
            margin-bottom: 30px; 
            font-family: 'Consolas', monospace; 
            border: 1px solid var(--color-secondary);
            font-size: 0.9em;
        }}
        table {{ 
            width: 100%; 
            border-collapse: separate; 
            margin-top: 20px; 
            border-radius: 10px; 
            overflow: hidden;
            box-shadow: 0 0 15px rgba(0,0,0,0.3);
        }}
        th, td {{ 
            padding: 15px; 
            text-align: left; 
            border-bottom: 1px solid #333; 
        }}
        th {{ 
            background-color: var(--color-dark); 
            color: var(--color-primary); 
            font-weight: bold;
            text-transform: uppercase;
        }}
        tr:nth-child(even) {{ background-color: #262626; }}
        tr:hover {{ background-color: #383838; cursor: default; }}

        .action-button {{ 
            background: var(--color-primary); 
            color: var(--color-dark); 
            border: none; 
            padding: 14px 25px; 
            border-radius: 8px; 
            cursor: pointer; 
            text-decoration: none; 
            font-weight: bold; 
            margin-right: 20px; 
            transition: all 0.3s;
            text-transform: uppercase;
        }}
        .action-button.secondary {{
            background: var(--color-accent);
            color: var(--color-dark);
        }}
        .action-button.delete {{
            background: var(--color-error);
            color: var(--color-light);
        }}
        .action-button:hover {{
            opacity: 0.9;
            box-shadow: 0 0 15px var(--color-primary);
            transform: translateY(-2px);
        }}
        .action-button.delete:hover {{
            box-shadow: 0 0 15px var(--color-error);
        }}
        .flash {{
            padding: 15px;
            margin-bottom: 25px;
            border-radius: 8px;
            background-color: var(--color-primary);
            color: var(--color-dark);
            font-weight: bold;
            box-shadow: 0 0 10px var(--color-primary);
        }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 20px;
        }}
        .stats-card {{
            background: #333;
            padding: 20px;
            border-radius: 10px;
            border-left: 5px solid var(--color-secondary);
        }}
        .stats-card p {{
            margin: 0;
            font-size: 0.9em;
            color: #ccc;
        }}
        .stats-card strong {{
            display: block;
            font-size: 1.5em;
            color: var(--color-primary);
            margin-top: 5px;
        }}
        /* Styles for Settings Page */
        .form-group {{
            margin-bottom: 25px;
            padding: 20px;
            border: 1px solid var(--color-accent);
            border-radius: 8px;
            background: #222;
        }}
        label {{
            display: block;
            font-weight: bold;
            margin-bottom: 8px;
            color: var(--color-secondary);
        }}
        input[type="text"], input[type="number"], select {{
            width: calc(100% - 20px);
            padding: 12px;
            border: 1px solid #555;
            border-radius: 6px;
            background-color: #333;
            color: var(--color-light);
            box-sizing: border-box;
            transition: border-color 0.3s;
        }}
        input[type="text"]:focus, input[type="number"]:focus, select:focus {{
            border-color: var(--color-primary);
            outline: none;
        }}
        input[type="checkbox"] {{
            width: auto;
            margin-right: 10px;
            transform: scale(1.3);
            vertical-align: middle;
            accent-color: var(--color-primary);
        }}
        .checkbox-group label {{
            margin-bottom: 10px;
            display: flex;
            align-items: center;
            font-weight: normal;
        }}
        .checkbox-group {{ margin-top: 15px; }}
        hr {{ border-color: #444; margin: 20px 0; }}

    """

HTML_TEMPLATE = """
<!doctype html>
<title>X4 Sorter Dashboard</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
    {{ dynamic_css }}
</style>
<div class="container">
    <h1>X4 Sorter Dashboard <span style="font-size: 0.5em; opacity: 0.6;">{{ version }}</span></h1>
    {% with messages = get_flashed_messages() %}
        {% if messages %}
            <div class="flash">{{ messages[0] }}</div>
        {% endif %}
    {% endwith %}

    {% if is_running %}
        {% if is_paused %}
            <div class="status paused">Статус: ПАУЗА ⏸️ (Web-Port: {{ WEB_PORT }})</div>
        {% else %}
            <div class="status">Статус: РАБОТАЕТ ✅ (Web-Port: {{ WEB_PORT }})</div>
        {% endif %}
    {% else %}
        <div class="status paused" style="background: #555;">Статус: НЕ АКТИВЕН 💤</div>
    {% endif %}

    <h2>Управление</h2>
    <a href="{{ url_for('force_scan') }}" class="action-button">🚀 Сканировать</a>
    {% if is_paused %}
        <a href="{{ url_for('resume') }}" class="action-button secondary">▶️ Возобновить</a>
    {% else %}
        <a href="{{ url_for('pause') }}" class="action-button secondary">⏸️ Пауза</a>
    {% endif %}
    <a href="{{ url_for('settings') }}" class="action-button secondary">⚙️ Настройки</a>
    <a href="{{ url_for('clear_log') }}" class="action-button delete" onclick="return confirm('Вы уверены? Журнал будет очищен.');">🗑️ Очистить журнал</a>

    <h2>Телеметрия Системы</h2>
    <div class="stats-grid">
        <div class="stats-card">
            <p>Дата первой регистрации</p>
            <strong>{{ first_run_date }}</strong>
        </div>
        <div class="stats-card">
            <p>Всего обработано файлов</p>
            <strong>{{ stats['total_files'] }}</strong>
        </div>
        <div class="stats-card">
            <p>Последний запуск</p>
            <strong>{{ stats['last_run'] if stats['last_run'] else 'N/A' }}</strong>
        </div>
        <div class="stats-card">
            <p>Хранение Карантин/Дубликаты</p>
            <strong>{{ retention_days }} дней</strong>
        </div>
        <div class="stats-card">
            <p>Папка Источника</p>
            <code style="color: var(--color-accent);">{{ source_folder }}</code>
        </div>
        <div class="stats-card">
            <p>Папка Назначения</p>
            <code style="color: var(--color-accent);">{{ dest_folder }}</code>
        </div>
    </div>

    <h2>Телеметрия по типам файлов</h2>
    {% if sorted_counts %}
        <table>
            <thead>
                <tr><th>Тип файла</th><th>Количество</th></tr>
            </thead>
            <tbody>
            {% for type, count in sorted_counts %}
                <tr><td>{{ type }}</td><td>{{ count }}</td></tr>
            {% endfor %}
            </tbody>
        </table>
    {% else %}
        <p>Нет статистики по типам файлов.</p>
    {% endif %}

    <h2>Журнал событий</h2>
    <div class="logs">{{ logs }}</div>
</div>
"""

HTML_SETTINGS_TEMPLATE = """
<!doctype html>
<title>X4 Sorter Settings</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
    {{ dynamic_css }}
</style>
<div class="container">
    <h1>X4 Sorter Настройки</h1>
    <a href="{{ url_for('index') }}" class="action-button secondary">◀️ Назад к Дашборду</a>
    
    {% with messages = get_flashed_messages() %}
        {% if messages %}
            <div class="flash">{{ messages[0] }}</div>
        {% endif %}
    {% endwith %}

    <form method="POST">
        <h2>Основные пути и тема</h2>
        <div class="form-group">
            <label for="source_folder">Папка Источника</label>
            <input type="text" id="source_folder" name="source_folder" value="{{ config['source_folder'] }}" required>
        </div>
        <div class="form-group">
            <label for="base_destination">Папка Назначения</label>
            <input type="text" id="base_destination" name="base_destination" value="{{ config['base_destination'] }}" required>
        </div>
        <div class="form-group">
            <label for="theme">Тема Дашборда</label>
            <select id="theme" name="theme">
                {% for theme_name in themes %}
                    <option value="{{ theme_name }}" {% if config['theme'] == theme_name %}selected{% endif %}>{{ theme_name }}</option>
                {% endfor %}
            </select>
        </div>
        
        <h2>Функционал</h2>
        <div class="form-group checkbox-group">
            {% for key, label in features_map.items() %}
                <label>
                    <input type="checkbox" name="{{ key }}" {% if config['features'].get(key) %}checked{% endif %}>
                    {{ label }}
                </label>
            {% endfor %}
        </div>
        <div class="form-group">
            <label for="retention_days">Дни хранения (Карантин/Дубликаты, 0 = не удалять)</label>
            <input type="number" id="retention_days" name="retention_days" value="{{ config['features'].get('retention_days', 30) }}" min="0" required>
        </div>

        <h2>Настройки Telegram</h2>
        <div class="form-group">
            <div class="checkbox-group">
                <label>
                    <input type="checkbox" name="telegram_enabled" {% if config['telegram'].get('enabled') %}checked{% endif %}>
                    Включить Telegram Уведомления (Текст)
                </label>
            </div>
            
            <label for="telegram_token">Telegram Token (Только для уведомлений)</label>
            <input type="text" id="telegram_token" name="telegram_token" value="{{ config['telegram'].get('token', '') }}">
            <label for="telegram_chat_id">Telegram Chat ID</label>
            <input type="text" id="telegram_chat_id" name="telegram_chat_id" value="{{ config['telegram'].get('chat_id', '') }}">
            
            <hr>
            
            <div class="checkbox-group">
                <label>
                    <input type="checkbox" name="upload_enabled" {% if config['telegram'].get('upload_enabled') %}checked{% endif %}>
                    Включить Загрузку файлов в Telegram (Облако)
                </label>
            </div>
            <label for="upload_max_size_mb">Максимальный размер файла для загрузки (MB)</label>
            <input type="number" id="upload_max_size_mb" name="upload_max_size_mb" value="{{ config['telegram'].get('upload_max_size_mb', 45) }}" min="1" max="50">
            
            <hr>
            <label style="color:var(--color-primary); margin-bottom:10px; display:block;">Управление Уведомлениями (Текст)</label>
            <div class="checkbox-group">
                <label>
                    <input type="checkbox" name="notify_success" {% if config['telegram'].get('notify_success') %}checked{% endif %}>
                    Уведомлять об успешной сортировке
                </label>
                <label>
                    <input type="checkbox" name="notify_duplicate" {% if config['telegram'].get('notify_duplicate') %}checked{% endif %}>
                    Уведомлять об обнаружении дубликатов
                </label>
                <label>
                    <input type="checkbox" name="notify_quarantine" {% if config['telegram'].get('notify_quarantine') %}checked{% endif %}>
                    Уведомлять о перемещении в Карантин
                </label>
            </div>
        </div>

        <button type="submit" class="action-button">💾 Сохранить и Перезагрузить</button>
    </form>
</div>
"""


@app.route('/')
def index():
    global core_sorter_instance, observer_instance
    
    # Пытаемся инициализировать, если не было инициализировано (для стабильности)
    if not core_sorter_instance:
        try:
             core_sorter_instance = CoreSorter(ui_callback=lambda: None)
        except Exception:
             # Если инициализация CoreSorter критически не удалась
             return "<div style='color:red;'>Система сортировки не инициализирована. Проверьте консоль.</div>"

    # Гарантируем, что Watchdog Observer запущен, если его нет
    if not observer_instance or not observer_instance.is_alive():
        setup_background_tasks() # Повторно запускаем Watchdog
    
    log_path = Path(__file__).resolve().parent / LOG_FILE
    logs = []
    if log_path.exists():
        with open(log_path, "r", encoding="utf-8") as f:
            logs = f.readlines()
            logs.reverse() 
            logs = logs[:40] 
    
    # Обновляем конфиг перед отображением
    cfg.load()
    
    file_counts = cfg.data['stats']['file_type_counts']
    sorted_counts = sorted(file_counts.items(), key=lambda item: item[1], reverse=True)
    
    return render_template_string(HTML_TEMPLATE,
        dynamic_css=generate_dynamic_css(cfg.data.get('theme', 'Cyberpunk')),
        version=VERSION,
        # Проверка состояния
        is_running=observer_instance.is_alive() if observer_instance else False,
        is_paused=core_sorter_instance._is_paused if core_sorter_instance else True,
        WEB_PORT=WEB_PORT,
        first_run_date=cfg.data.get('first_run_date', 'N/A'),
        stats=cfg.data['stats'],
        source_folder=cfg.data['source_folder'],
        dest_folder=cfg.data['base_destination'],
        retention_days=cfg.data.get('features', {}).get('retention_days', 30),
        sorted_counts=sorted_counts,
        logs="".join(logs)
    )

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if not core_sorter_instance:
        return "<div style='color:red;'>Система сортировки не запущена.</div>"
    
    # Обновляем конфиг перед отображением
    cfg.load() 
    
    features_map = {
        "sort_by_date": "Сортировка по дате (EXIF/Создание)",
        "sort_by_metadata": "Сортировка по метаданным (ID3/MP3)",
        "auto_unpack": "Авто-распаковка ZIP/7z/RAR",
        "deduplication": "Детекция дубликатов (SHA256)",
        "quarantine_mode": "Режим Карантина (Проверка на ЧС)",
        "deep_clean": "Удалять пустые папки (Cleanup)",
        "sound_enabled": "Звуковые уведомления (Windows)",
        "notifications": "Системные уведомления (Windows Pop-up)"
    }
    
    if request.method == 'POST':
        try:
            # 1. Общие настройки
            cfg.update_val(None, 'source_folder', request.form['source_folder'])
            cfg.update_val(None, 'base_destination', request.form['base_destination'])
            cfg.update_val(None, 'theme', request.form['theme'])

            # 2. Настройки функций (Чекбоксы)
            for key in features_map.keys():
                is_checked = key in request.form
                cfg.update_val('features', key, is_checked)
                
            # 3. Дни хранения
            retention = int(request.form['retention_days'])
            cfg.update_val('features', 'retention_days', retention)

            # 4. Настройки Telegram (Безопасный доступ)
            cfg.update_val('telegram', 'enabled', 'telegram_enabled' in request.form)
            cfg.update_val('telegram', 'token', request.form.get('telegram_token', ''))
            cfg.update_val('telegram', 'chat_id', request.form.get('telegram_chat_id', ''))
            cfg.update_val('telegram', 'upload_enabled', 'upload_enabled' in request.form)
            cfg.update_val('telegram', 'upload_max_size_mb', int(request.form.get('upload_max_size_mb', 45)))
            cfg.update_val('telegram', 'notify_success', 'notify_success' in request.form)
            cfg.update_val('telegram', 'notify_duplicate', 'notify_duplicate' in request.form)
            cfg.update_val('telegram', 'notify_quarantine', 'notify_quarantine' in request.form)

            # Перезагружаем настройки в активный инстанс
            core_sorter_instance.reload_settings()
            
            flash('✅ Настройки успешно сохранены и применены!')
            return redirect(url_for('settings'))
        
        except Exception as e:
            flash(f'❌ Ошибка при сохранении настроек: {e}')
            return redirect(url_for('settings'))


    return render_template_string(HTML_SETTINGS_TEMPLATE,
        dynamic_css=generate_dynamic_css(cfg.data.get('theme', 'Cyberpunk')),
        config=cfg.data,
        themes=THEMES.keys(),
        features_map=features_map
    )

@app.route('/clear_log')
def clear_log():
    log_path = Path(__file__).resolve().parent / LOG_FILE
    if log_path.exists():
        try:
            with open(log_path, 'w', encoding="utf-8") as f:
                f.write(f"[{datetime.now().strftime('%H:%M:%S')}] ЖУРНАЛ ОЧИЩЕН ЧЕРЕЗ ВЕБ-ДАШБОРД\n")
            flash('🗑️ Журнал событий успешно очищен.')
        except Exception as e:
            flash(f'❌ Ошибка при очистке журнала: {e}')
    else:
        flash('⚠️ Файл журнала не найден. Создан новый файл.')
    
    if core_sorter_instance and core_sorter_instance.ui_callback:
        # Вызов колбэка для обновления TUI
        try: core_sorter_instance.ui_callback()
        except: pass

    return redirect(url_for('index'))


@app.route('/pause')
def pause():
    if core_sorter_instance: core_sorter_instance.pause()
    return redirect(url_for('index'))

@app.route('/resume')
def resume():
    if core_sorter_instance: core_sorter_instance.resume()
    return redirect(url_for('index'))

@app.route('/force_scan')
def force_scan():
    if core_sorter_instance: core_sorter_instance.force_scan()
    return redirect(url_for('index'))

# --- ИСПРАВЛЕНАЯ ФУНКЦИЯ ДЛЯ ГЛОБАЛЬНОГО ИНСТАНСА (СИНТАКСИС) ---
def run_web_dashboard():
    global core_sorter_instance # ИСПРАВЛЕНИЕ 5: Добавлено объявление global в начало
    
    # Отключаем баннер Flask
    cli = sys.modules.get('flask.cli')
    if cli: cli.show_server_banner = lambda *x: None
    
    try:
        # Убедитесь, что core_sorter_instance инициализирован для получения темы
        if not core_sorter_instance:
             core_sorter_instance = CoreSorter(ui_callback=lambda: None)
             
        # run_simple (альтернатива для Flask) или app.run
        app.run(port=WEB_PORT, debug=False, use_reloader=False)
    except OSError:
        send_telegram_message(f"🚨 **ОШИБКА**: Порт {WEB_PORT} для веб-дашборда занят. Дашборд не запущен.", level="ERROR")
    except Exception as e:
        send_telegram_message(f"🚨 **Критическая ошибка Web-сервера**: {e}", level="ERROR")
        

# --- TUI И ТОЧКА ВХОДА ---
class Interface:
    
    def __init__(self):
        self.console = Console()
        self.clear()
        
    def clear(self): os.system('cls' if os.name == 'nt' else 'clear')
    
    def get_banner(self):
        cfg.update_theme() # Обновляем тему перед отрисовкой
        t = cfg.current_theme
        
        # ИСПРАВЛЕНИЕ 4: Panel не принимает 'justify', используем Align.center
        text = Align.center(Text(f" 🛡️ {APP_NAME} {VERSION} ", style=f"{t['text']}"))
        return Panel(
            text,
            style=f"{t['border']}", 
            border_style=t['border']
        )

    def main_menu(self):
        while True:
            self.clear()
            self.console.print(self.get_banner())
            t = cfg.current_theme
            
            # Обновляем конфиг для актуальной статистики
            cfg.load()
            stats = cfg.data['stats']
            
            self.console.print(f"\n[cyan]📊 СТАТИСТИКА:[/]")
            self.console.print(f"   Дата первой регистрации: [bold]{cfg.data.get('first_run_date', 'N/A')}[/]")
            self.console.print(f"   Всего обработано файлов: [bold]{stats['total_files']}[/]")
            self.console.print(f"   Веб-Дашборд: [bold]{t['primary']}http://127.0.0.1:{WEB_PORT}[/bold]")
            
            self.console.print(f"[cyan]МЕНЮ УПРАВЛЕНИЯ:[/]")
            self.console.print(f"[1] 🚀 [bold]ЗАПУСТИТЬ СОРТИРОВКУ (Live Режим)[/]")
            self.console.print(f"[2] ⚙️  Настройки функций")
            self.console.print(f"[3] 🔑 Настройка Telegram/Web")
            self.console.print(f"[4] 💾 Добавить в Автозагрузку (Режим Трея) [dim](Windows)[/dim]")
            self.console.print(f"[5] ❌ Выход")
            
            try:
                choice = Prompt.ask(f"\n[bold magenta]Ваш выбор[/]", choices=["1", "2", "3", "4", "5"], default="1")
            except KeyboardInterrupt:
                choice = "5" # Выход по Ctrl+C

            if choice == "1": self.run_dashboard()
            elif choice == "2": self.settings_page()
            elif choice == "3": self.advanced_settings_page()
            elif choice == "4": self.install_autorun()
            elif choice == "5": 
                if core_sorter_instance and observer_instance and observer_instance.is_alive():
                    # Безопасный выход из TUI
                    self.console.print("[yellow]Сортировка работает. Закрыть? (y/n)[/]")
                    if Prompt.ask("", choices=['y', 'n'], default='n') == 'y':
                        # Останавливаем все потоки перед выходом
                        if observer_instance: observer_instance.stop()
                        if core_sorter_instance and core_sorter_instance.executor: core_sorter_instance.executor.shutdown()
                        sys.exit()
                else:
                    sys.exit()

    def advanced_settings_page(self):
        while True:
            self.clear()
            self.console.print(self.get_banner())
            t = cfg.current_theme
            # Обновляем конфиг
            cfg.load()
            tg = cfg.data.get('telegram', {})
            
            def status(val): return f"[green]ВКЛ[/green]" if val else f"[red]ВЫКЛ[/red]"
            
            table = Table(box=box.SIMPLE, border_style=t['border'])
            table.add_column("№", style="dim")
            table.add_column("Параметр")
            table.add_column("Значение")

            table.add_row("1", "Telegram Уведомления (Текст)", status(tg.get('enabled')))
            table.add_row("2", "Telegram Token", f"[dim]{tg.get('token', '')[:10]}...[/dim]" if tg.get('token') else "[red]НЕ ЗАДАН[/red]")
            table.add_row("3", "Telegram Chat ID", f"[dim]{tg.get('chat_id', '')}[/dim]" if tg.get('chat_id') else "[red]НЕ ЗАДАН[/red]")
            table.add_row("4", "Загружать файлы в Telegram (Облако)", status(tg.get('upload_enabled')))
            table.add_row("5", "Уведомлять об успешной сортировке", status(tg.get('notify_success')))
            table.add_row("6", "Уведомлять об обнаружении дубликатов", status(tg.get('notify_duplicate')))
            table.add_row("7", "Уведомлять о перемещении в Карантин", status(tg.get('notify_quarantine')))
            table.add_row("8", "Дни хранения (Карантин/Дубликаты)", f"[bold]{cfg.data['features'].get('retention_days', 30)} дн.[/bold]")
            
            self.console.print(table)
            self.console.print("\n[dim]Введите номер для изменения или 'b' для возврата[/dim]")
            
            try:
                ans = Prompt.ask(f"[bold magenta]Настройка[/]")
            except KeyboardInterrupt:
                ans = 'b'
            
            if ans == 'b': break
            elif ans == '1': 
                cfg.update_val('telegram', 'enabled', not tg.get('enabled'))
                if core_sorter_instance: core_sorter_instance.reload_settings()
            elif ans == '2': 
                token = Prompt.ask("Введите Token"); cfg.update_val('telegram', 'token', token)
                if core_sorter_instance: core_sorter_instance.reload_settings()
            elif ans == '3': 
                chat_id = Prompt.ask("Введите Chat ID"); cfg.update_val('telegram', 'chat_id', chat_id)
                if core_sorter_instance: core_sorter_instance.reload_settings()
            elif ans == '4': 
                cfg.update_val('telegram', 'upload_enabled', not tg.get('upload_enabled'))
                if core_sorter_instance: core_sorter_instance.reload_settings()
            elif ans == '5': 
                cfg.update_val('telegram', 'notify_success', not tg.get('notify_success'))
                if core_sorter_instance: core_sorter_instance.reload_settings()
            elif ans == '6': 
                cfg.update_val('telegram', 'notify_duplicate', not tg.get('notify_duplicate'))
                if core_sorter_instance: core_sorter_instance.reload_settings()
            elif ans == '7': 
                cfg.update_val('telegram', 'notify_quarantine', not tg.get('notify_quarantine'))
                if core_sorter_instance: core_sorter_instance.reload_settings()
            elif ans == '8':
                days = Prompt.ask("Дни хранения", default=str(cfg.data['features'].get('retention_days', 30)))
                if days.isdigit(): 
                    cfg.update_val('features', 'retention_days', int(days))
                    if core_sorter_instance: core_sorter_instance.reload_settings()

    def settings_page(self):
        while True:
            self.clear()
            self.console.print(self.get_banner())
            t = cfg.current_theme
            # Обновляем конфиг
            cfg.load()
            f = cfg.data.get('features', {})
            
            def status(key): return f"[green]ВКЛ[/green]" if f.get(key) else f"[red]ВЫКЛ[/red]"
            
            table = Table(box=box.SIMPLE, border_style=t['border'])
            table.add_column("№", style="dim")
            table.add_column("Функция")
            table.add_column("Состояние")

            table.add_row("1", "Сортировка по дате (EXIF/Создание)", status('sort_by_date'))
            table.add_row("2", "Сортировка по метаданным (ID3/MP3)", status('sort_by_metadata'))
            table.add_row("3", "Авто-распаковка ZIP/7z/RAR", status('auto_unpack'))
            table.add_row("4", "Детекция дубликатов (SHA256)", status('deduplication'))
            table.add_row("5", "Режим Карантина (Проверка на ЧС)", status('quarantine_mode'))
            table.add_row("6", "Удалять пустые папки (Cleanup)", status('deep_clean'))
            table.add_row("7", "Сменить тему", cfg.data['theme'])
            table.add_row("8", "Папка Источника", cfg.data['source_folder'])
            table.add_row("9", "Папка Назначения", cfg.data['base_destination'])
            
            self.console.print(table)
            self.console.print("\n[dim]Введите номер для переключения или 'b' для возврата[/dim]")
            
            try:
                ans = Prompt.ask(f"[bold magenta]Настройка[/]")
            except KeyboardInterrupt:
                ans = 'b'
            
            if ans == 'b': break
            elif ans == '1': 
                cfg.update_val('features', 'sort_by_date', not f.get('sort_by_date'))
                if core_sorter_instance: core_sorter_instance.reload_settings()
            elif ans == '2': 
                cfg.update_val('features', 'sort_by_metadata', not f.get('sort_by_metadata'))
                if core_sorter_instance: core_sorter_instance.reload_settings()
            elif ans == '3': 
                cfg.update_val('features', 'auto_unpack', not f.get('auto_unpack'))
                if core_sorter_instance: core_sorter_instance.reload_settings()
            elif ans == '4': 
                cfg.update_val('features', 'deduplication', not f.get('deduplication'))
                if core_sorter_instance: core_sorter_instance.reload_settings()
            elif ans == '5': 
                cfg.update_val('features', 'quarantine_mode', not f.get('quarantine_mode'))
                if core_sorter_instance: core_sorter_instance.reload_settings()
            elif ans == '6': 
                cfg.update_val('features', 'deep_clean', not f.get('deep_clean'))
                if core_sorter_instance: core_sorter_instance.reload_settings()
            elif ans == '7':
                new_t = Prompt.ask("Выберите тему", choices=list(THEMES.keys()), default="Cyberpunk")
                cfg.update_val(None, 'theme', new_t)
                if core_sorter_instance: core_sorter_instance.reload_settings()
            elif ans == '8':
                new_src = Prompt.ask("Новая папка Источника", default=cfg.data['source_folder'])
                try:
                    path_obj = Path(new_src).resolve()
                    if path_obj.exists(): 
                        cfg.update_val(None, 'source_folder', str(path_obj))
                        if core_sorter_instance: core_sorter_instance.reload_settings()
                    else: self.console.print("[red]❌ Папка не найдена. Попробуйте снова.[/red]")
                except Exception as e:
                     self.console.print(f"[red]❌ Ошибка пути: {e}[/red]")
            elif ans == '9':
                new_dest = Prompt.ask("Новая папка Назначения", default=cfg.data['base_destination'])
                try:
                    path_obj = Path(new_dest).resolve()
                    path_obj.mkdir(parents=True, exist_ok=True)
                    cfg.update_val(None, 'base_destination', str(path_obj))
                    if core_sorter_instance: core_sorter_instance.reload_settings()
                except Exception as e:
                     self.console.print(f"[red]❌ Ошибка пути: {e}[/red]")

    def run_dashboard(self):
        global core_sorter_instance, observer_instance # ИСПРАВЛЕНИЕ 5: Добавлено объявление global в начало
        self.clear()
        
        cfg.load()
        
        # Инициализация CoreSorter и Observer, если они еще не запущены
        if not core_sorter_instance or not observer_instance or not observer_instance.is_alive():
            live_updater = lambda: live.refresh() if 'live' in locals() else None
            core_sorter_instance = CoreSorter(ui_callback=live_updater)
            observer_instance = Observer()
            observer_instance.schedule(core_sorter_instance, str(core_sorter_instance.src.resolve()), recursive=False)
            observer_instance.start()
        else:
             # Если уже запущены, обновляем колбэк для Live объекта
             live_updater = lambda: live.refresh() if 'live' in locals() else None
             core_sorter_instance.ui_callback = live_updater
        
        t = cfg.current_theme
        layout = Layout()
        layout.split_column(Layout(name="top", size=3), Layout(name="main"))
        layout["top"].update(self.get_banner())
        
        try:
            with Live(layout, refresh_per_second=2, screen=True) as live:
                while True:
                    # Обновление конфига для получения актуальной статистики
                    cfg.load()
                    
                    log_path = Path(__file__).resolve().parent / LOG_FILE
                    log_lines = []
                    if log_path.exists():
                        with open(log_path, "r", encoding="utf-8") as f:
                            log_lines = f.readlines()[-10:]
                    
                    log_text = Text()
                    for line in log_lines:
                        clean_line = line.strip().replace("->", "➜")
                        # Логика подсветки логов (без изменений)
                        if "КАРАНТИН" in clean_line or "ОШИБКА" in clean_line:
                            clean_line = Text(clean_line, style="bold red on black")
                        elif "ДУБЛИКАТ" in clean_line:
                            clean_line = Text(clean_line, style="bold yellow on black")
                        elif "УДАЛЕНО" in clean_line:
                            clean_line = Text(clean_line, style="dim white on black")
                        elif "ОЧИСТКА" in clean_line:
                            clean_line = Text(clean_line, style="bold magenta on black")
                        elif "TELEGRAM" in clean_line:
                            clean_line = Text(clean_line, style="bold cyan on black")
                        log_text.append(clean_line + "\n")

                    telemetry_table = Table(box=None, show_header=False)
                    telemetry_data = cfg.data['stats']['file_type_counts']
                    for name, count in sorted(telemetry_data.items(), key=lambda item: item[1], reverse=True)[:5]:
                         # Безопасное отображение имени категории
                         clean_name = name.split('_', 1)[1] if '_' in name else name 
                         telemetry_table.add_row(f"[dim]{clean_name}:[/dim]", f"[bold]{count}[/bold]")
                    
                    status_info = f"""
[bold]Статус:[/bold] {'[green]АКТИВЕН[/green]' if not core_sorter_instance._is_paused else '[red]ПАУЗА[/red]'}
[bold]Web:[/bold] [cyan]http://127.0.0.1:{WEB_PORT}[/cyan]
[bold]Retain:[/bold] {cfg.data.get('features', {}).get('retention_days', 30)} дней
[bold]Cleanup:[/bold] {'[green]ВКЛ[/green]' if cfg.data.get('features', {}).get('deep_clean') else '[red]ВЫКЛ[/red]'}

{telemetry_table}
[dim]Нажмите Ctrl+C для выхода[/dim] | [cyan]F[/cyan] - Принудительное сканирование
                    """
                    
                    main_split = Layout()
                    main_split.split_row(
                        Layout(Panel(status_info, title="Статус & Телеметрия", border_style=t['border']), ratio=1),
                        Layout(Panel(log_text, title="Живой журнал событий", border_style=t['text']), ratio=2)
                    )
                    layout["main"].update(main_split)
                    time.sleep(0.5)
                    
        except KeyboardInterrupt:
            # Обработка выхода из Live
            try:
                # Временно отключаем Live для ввода
                live.stop() 
                command = console.input("\nНажмите 'F' для сканирования или Enter для выхода в меню: ").upper()
                if command == 'F':
                    core_sorter_instance.force_scan()
                    # Возвращаемся в дашборд после сканирования
                    self.run_dashboard() 
            except: pass
            
        # Восстанавливаем колбэк на заглушку после выхода из Live
        core_sorter_instance.ui_callback = lambda: None


    def install_autorun(self):
        if os.name != 'nt':
            self.console.print("[red]❌ Эта функция предназначена только для Windows.[/red]")
            Prompt.ask("\nНажмите Enter для возврата...")
            return
            
        startup = Path(os.getenv('APPDATA')) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        bat_path = startup / "X4_Sorter_Tray.bat"
        
        # Используем pythonw.exe для скрытого запуска
        py_exe = sys.executable.replace("python.exe", "pythonw.exe")
        if not os.path.exists(py_exe): 
            self.console.print("[yellow]⚠️ Не найден 'pythonw.exe'. Используется 'python.exe', может появиться окно консоли.[/yellow]")
            py_exe = sys.executable
        
        # Получаем полный путь к main.py
        script_path = Path(__file__).resolve()
        
        # ИСПРАВЛЕНИЕ 6: Обязательно используем двойные кавычки вокруг путей
        content = f'@echo off\nCHCP 65001\nstart "" "{py_exe}" "{script_path}"'
        
        try:
            with open(bat_path, "w", encoding="utf-8") as f: f.write(content)
            self.console.print(f"\n[green]✅ Успешно! Скрипт установлен в режиме Системного Трея. (Запустится после перезагрузки)[/green]")
            self.console.print(f"[dim]Файл создан: {bat_path}[/dim]")
        except Exception as e:
            self.console.print(f"[red]Ошибка при создании BAT файла: {e}[/red]")
        
        Prompt.ask("\nНажмите Enter для возврата...")


# --- ТОЧКА ВХОДА ---
if __name__ == "__main__":
    
    # 1. Инициализация CoreSorter для доступа к настройкам темы до запуска Flask
    if not core_sorter_instance:
         # Инициализация с базовым UI callback
         core_sorter_instance = CoreSorter(ui_callback=lambda: None)
         
    # 2. Запуск веб-дашборда в отдельном потоке
    # Используем демон-поток, чтобы он автоматически завершился при закрытии основного
    threading.Thread(target=run_web_dashboard, daemon=True).start()
    
    # 3. Запуск основного интерфейса (консоль или трей)
    # Определяем, был ли запуск через pythonw.exe (скрытый запуск)
    if sys.executable.endswith("pythonw.exe"):
        # Режим трея (когда запускается через BAT)
        run_tray()
    else:
        # Режим консоли
        try:
            app = Interface()
            app.main_menu()
        except KeyboardInterrupt:
            # Остановка всех потоков при выходе из консоли
            if observer_instance: observer_instance.stop()
            if core_sorter_instance and core_sorter_instance.executor: core_sorter_instance.executor.shutdown()
            sys.exit()