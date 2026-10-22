"""
Telegram Alert Bot for alerts.in.ua - Background Worker for Render.com
Polls alerts API every 10 seconds and sends notifications to subscribed users.
"""

import asyncio
import csv
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from aiohttp import web

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, BotCommand
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
)
from telegram.error import Forbidden

from pyuca import Collator

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Environment variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALERTS_API_TOKEN = os.getenv("ALERTS_API_TOKEN")
BACKUP_CHAT_ID = os.getenv("BACKUP_CHAT_ID")
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID"))
ALERTS_API_URL = "https://api.alerts.in.ua/v1/alerts/active.json"

# File paths
USERS_CSV = Path("users.csv")
LAST_API_RESPONSE_FILE = Path("last_api_response.json")
LOCATIONS_CSV = Path("locations.csv")

# Conversation states
SELECT_ACTION, SELECT_LOCATION_TYPE, SELECT_LOCATION = range(3)

# Ukrainian translations
MESSAGES = {
    "start": "👋 Вітаємо! Це бот для сповіщень про тривоги\n\nЩо ви хочете зробити?",
    "menu": "Виберіть дію:",
    "add_location": "➕ Додати локацію",
    "remove_location": "➖ Видалити локацію",
    "view_subscriptions": "📋 Мої підписки",
    "select_region": "🗺️ Виберіть область або місто:",
    "select_subregion": "📍 Виберіть район або територіальну громаду:",
    "added": "✅ Локація додана: {location}",
    "already_subscribed": "⚠️ Ви вже підписані на цю локацію",
    "removed": "❌ Локація видалена: {location}",
    "not_subscribed": "⚠️ Ви не підписані на цю локацію",
    "subscriptions": "📋 Ваші підписки:\n{locations}",
    "no_subscriptions": "Ви поки не підписані на жодну локацію",
    "select_to_remove": "🗑️ Виберіть локацію для видалення:",
    "no_locations": "Немає доступних локацій",
    "back": "⬅️ Назад",
    "cancelled": "Скасовано",
}

# Alert type and level icons/translations
ALERT_TYPE_MAP = {
    "air_raid": "✈️ Тривога",
    "artillery_shelling": "💥 Артилерійський обстріл",
    "urban_fights": "🔫 Стрілецькі бої",
    "unspecified_missiles": "❓ Невизначена тривога"
}

LEVEL_ICON = {
    "red": "🔴",
    "yellow": "🟡",
    "green": "🟢",
}


class LocationManager:
    """Manages location data from in-memory locations_data."""

    def __init__(self):
        self.locations: Dict[str, Dict] = {}
        self.sorted_regions: Dict[str, str] = {}  # Cached sorted regions
        self.sorted_subregions: Dict[str, Dict[str, str]] = {}  # Cached sorted subregions by parent UID
        self.collator = Collator()  # Unicode Collator for proper sorting
        self.load_locations()

    def load_locations(self):
        """Load locations from embedded data and sort them alphabetically."""
        locations_data = [
            ("4", "Вінницька область", "Область", ""),
            ("8", "Волинська область", "Область", ""),
            ("9", "Дніпропетровська область", "Область", ""),
            ("28", "Донецька область", "Область", ""),
            ("10", "Житомирська область", "Область", ""),
            ("11", "Закарпатська область", "Область", ""),
            ("12", "Запорізька область", "Область", ""),
            ("13", "Івано-Франківська область", "Область", ""),
            ("14", "Київська область", "Область", ""),
            ("31", "м. Київ", "Місто з спеціальним статусом", ""),
            ("15", "Кіровоградська область", "Область", ""),
            ("16", "Луганська область", "Область", ""),
            ("27", "Львівська область", "Область", ""),
            ("17", "Миколаївська область", "Область", ""),
            ("18", "Одеська область", "Область", ""),
            ("19", "Полтавська область", "Область", ""),
            ("5", "Рівненська область", "Область", ""),
            ("20", "Сумська область", "Область", ""),
            ("21", "Тернопільська область", "Область", ""),
            ("22", "Харківська область", "Область", ""),
            ("23", "Херсонська область", "Область", ""),
            ("3", "Хмельницька область", "Область", ""),
            ("24", "Черкаська область", "Область", ""),
            ("26", "Чернівецька область", "Область", ""),
            ("25", "Чернігівська область", "Область", ""),
            ("29", "Автономна Республіка Крим", "Область", ""),
            ("30", "м. Севастополь", "Місто з спеціальним статусом", ""),
            ("135", "Кам'янець-Подільський район", "Район", "3"),
            ("134", "Хмельницький район", "Район", "3"),
            ("136", "Шепетівський район", "Район", "3"),
            ("36", "Вінницький район", "Район", "4"),
            ("37", "Гайсинський район", "Район", "4"),
            ("35", "Жмеринський район", "Район", "4"),
            ("33", "Могилів-Подільський район", "Район", "4"),
            ("32", "Тульчинський район", "Район", "4"),
            ("34", "Хмільницький район", "Район", "4"),
            ("110", "Вараський район", "Район", "5"),
            ("111", "Дубенський район", "Район", "5"),
            ("112", "Рівненський район", "Район", "5"),
            ("113", "Сарненський район", "Район", "5"),
            ("38", "Володимирський район", "Район", "8"),
            ("41", "Камінь-Каширський район", "Район", "8"),
            ("40", "Ковельський район", "Район", "8"),
            ("39", "Луцький район", "Район", "8"),
            ("42", "Кам'янський район", "Район", "9"),
            ("44", "Дніпровський район", "Район", "9"),
            ("46", "Криворізький район", "Район", "9"),
            ("47", "Нікопольський район", "Район", "9"),
            ("45", "Павлоградський район", "Район", "9"),
            ("43", "Самарівський район", "Район", "9"),
            ("48", "Синельниківський район", "Район", "9"),
            ("57", "Бердичівський район", "Район", "10"),
            ("59", "Житомирський район", "Район", "10"),
            ("60", "Звягельський район", "Район", "10"),
            ("58", "Коростенський район", "Район", "10"),
            ("61", "Берегівський район", "Район", "11"),
            ("65", "Мукачівський район", "Район", "11"),
            ("63", "Рахівський район", "Район", "11"),
            ("64", "Тячівський район", "Район", "11"),
            ("66", "Ужгородський район", "Район", "11"),
            ("62", "Хустський район", "Район", "11"),
            ("147", "Бердянський район", "Район", "12"),
            ("146", "Василівський район", "Район", "12"),
            ("149", "Запорізький район", "Район", "12"),
            ("148", "Мелітопольський район", "Район", "12"),
            ("145", "Пологівський район", "Район", "12"),
            ("67", "Верховинський район", "Район", "13"),
            ("71", "Калуський район", "Район", "13"),
            ("70", "Коломийський район", "Район", "13"),
            ("69", "Косівський район", "Район", "13"),
            ("72", "Надвірнянський район", "Район", "13"),
            ("68", "Івано-Франківський район", "Район", "13"),
            ("73", "Білоцерківський район", "Район", "14"),
            ("78", "Бориспільський район", "Район", "14"),
            ("79", "Броварський район", "Район", "14"),
            ("75", "Бучанський район", "Район", "14"),
            ("74", "Вишгородський район", "Район", "14"),
            ("76", "Обухівський район", "Район", "14"),
            ("77", "Фастівський район", "Район", "14"),
            ("82", "Голованівський район", "Район", "15"),
            ("81", "Кропивницький район", "Район", "15"),
            ("83", "Новоукраїнський район", "Район", "15"),
            ("80", "Олександрійський район", "Район", "15"),
            ("1803", "Алчевський район", "Район", "16"),
            ("1804", "Довжанський район", "Район", "16"),
            ("1801", "Луганський район", "Район", "16"),
            ("1802", "Ровеньківський район", "Район", "16"),
            ("84", "Сіверськодонецький район", "Район", "16"),
            ("85", "Сватівський район", "Район", "16"),
            ("86", "Старобільський район", "Район", "16"),
            ("87", "Щастинський район", "Район", "16"),
            ("96", "Баштанський район", "Район", "17"),
            ("95", "Вознесенський район", "Район", "17"),
            ("98", "Миколаївський район", "Район", "17"),
            ("97", "Первомайський район", "Район", "17"),
            ("102", "Білгород-Дністровський район", "Район", "18"),
            ("100", "Березівський район", "Район", "18"),
            ("105", "Болградський район", "Район", "18"),
            ("104", "Одеський район", "Район", "18"),
            ("99", "Подільський район", "Район", "18"),
            ("103", "Роздільнянський район", "Район", "18"),
            ("101", "Ізмаїльський район", "Район", "18"),
            ("107", "Кременчуцький район", "Район", "19"),
            ("106", "Лубенський район", "Район", "19"),
            ("108", "Миргородський район", "Район", "19"),
            ("109", "Полтавський район", "Район", "19"),
            ("117", "Конотопський район", "Район", "20"),
            ("118", "Охтирський район", "Район", "20"),
            ("116", "Роменський район", "Район", "20"),
            ("114", "Сумський район", "Область", "20"),
            ("115", "Шосткинський район", "Район", "20"),
            ("120", "Кременецький район", "Район", "21"),
            ("119", "Тернопільський район", "Район", "21"),
            ("121", "Чортківський район", "Район", "21"),
            ("127", "Берестинський район", "Район", "22"),
            ("126", "Богодухівський район", "Район", "22"),
            ("123", "Куп'янський район", "Район", "22"),
            ("128", "Лозівський район", "Район", "22"),
            ("1293", "м. Харків", "Місто", "22"),
            ("124", "Харківський район", "Район", "22"),
            ("122", "Чугуївський район", "Район", "22"),
            ("125", "Ізюмський район", "Район", "22"),
            ("129", "Бериславський район", "Район", "23"),
            ("133", "Генічеський район", "Район", "23"),
            ("131", "Каховський район", "Район", "23"),
            ("130", "Скадовський район", "Район", "23"),
            ("132", "Херсонський район", "Район", "23"),
            ("150", "Звенигородський район", "Район", "24"),
            ("153", "Золотоніський район", "Район", "24"),
            ("151", "Уманський район", "Район", "24"),
            ("152", "Черкаський район", "Район", "24"),
            ("144", "Корюківський район", "Район", "25"),
            ("142", "Ніжинський район", "Район", "25"),
            ("141", "Новгород-Сіверський район", "Район", "25"),
            ("143", "Прилуцький район", "Район", "25"),
            ("140", "Чернігівський район", "Район", "25"),
            ("138", "Вижницький район", "Район", "26"),
            ("139", "Дністровський район", "Район", "26"),
            ("137", "Чернівецький район", "Район", "26"),
            ("88", "Самбірський район", "Район", "27"),
            ("89", "Стрийський район", "Район", "27"),
            ("90", "Львівський район", "Район", "27"),
            ("91", "Дрогобицький район", "Район", "27"),
            ("92", "Шептицький район", "Район", "27"),
            ("93", "Яворівський район", "Район", "27"),
            ("94", "Золочівський район", "Район", "27"),
            ("49", "Кальміуський район", "Район", "28"),
            ("50", "Краматорський район", "Район", "28"),
            ("51", "Горлівський район", "Район", "28"),
            ("52", "Маріупольський район", "Район", "28"),
            ("53", "Донецький район", "Район", "28"),
            ("54", "Бахмутський район", "Район", "28"),
            ("55", "Волноваський район", "Район", "28"),
            ("56", "Покровський район", "Район", "28"),
        ]

        # Load locations into memory
        self.locations = {
            uid: {
                "name": name,
                "type": loc_type,
                "parent": parent_uid,
            }
            for uid, name, loc_type, parent_uid in locations_data
        }

        # Sort and cache regions alphabetically by name
        self.sorted_regions = {
            uid: loc["name"]
            for uid, loc in sorted(
                self.locations.items(),
                key=lambda item: self.collator.sort_key(
                    item[1]["name"][3:].lower() if item[1]["name"].startswith("м. ") else item[1]["name"].lower()  # Locale-aware sorting
                )
            )
            if loc["type"] in ("Область", "Місто з спеціальним статусом")
        }

        # Move the first region (Автономна Республіка Крим) to the end of the sorted list
        self.sorted_regions = {**dict(list(self.sorted_regions.items())[1:]), **dict(list(self.sorted_regions.items())[:1])}

        # Sort and cache subregions by parent UID, alphabetically ignoring case
        self.sorted_subregions = {}
        for uid, loc in self.locations.items():
            parent_uid = loc.get("parent")
            if parent_uid:
                if parent_uid not in self.sorted_subregions:
                    self.sorted_subregions[parent_uid] = {}
                self.sorted_subregions[parent_uid][uid] = loc["name"]

        # Sort subregions for each parent UID
        for parent_uid, subregions in self.sorted_subregions.items():
            self.sorted_subregions[parent_uid] = dict(
                sorted(subregions.items(), key=lambda item: self.collator.sort_key(item[1].lower()))  # Sort ignoring case
            )

    def get_regions(self) -> Dict[str, str]:
        """
        Get all regions (Область, Місто з спеціальним статусом).
        Returns a dictionary with UID as the key and region name as the value.
        """
        return self.sorted_regions

    def get_subregions(self, parent_uid: str) -> Dict[str, str]:
        """
        Get subregions (Район, Hromada) for a parent region.
        Returns a dictionary with UID as the key and subregion name as the value.
        """
        return self.sorted_subregions.get(parent_uid, {})

    def get_location_name(self, uid: str) -> Optional[str]:
        """Get location name by UID."""
        return self.locations.get(uid, {}).get("name")


class UserManager:
    """Manages user subscriptions in CSV."""

    def __init__(self):
        self.ensure_csv_exists()

    def ensure_csv_exists(self):
        """Create CSV if it doesn't exist."""
        if not USERS_CSV.exists():
            with open(USERS_CSV, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["userId", "locations"])

    def get_user_locations(self, user_id: int) -> Set[str]:
        """Get all subscribed location UIDs for a user."""
        self.ensure_csv_exists()
        try:
            with open(USERS_CSV, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row["userId"] == str(user_id):
                        locations_str = row.get("locations", "")
                        return set(locations_str.split(",")) if locations_str else set()
        except Exception as e:
            logger.error(f"Error reading user locations: {e}")
        return set()

    def add_location(self, user_id: int, location_uid: str) -> bool:
        """Add a location to user's subscriptions."""
        self.ensure_csv_exists()
        locations = self.get_user_locations(user_id)
        if location_uid in locations:
            return False  # Already subscribed
        
        locations.add(location_uid)
        self._save_user_locations(user_id, locations)
        return True

    def remove_location(self, user_id: int, location_uid: str) -> bool:
        """Remove a location from user's subscriptions."""
        self.ensure_csv_exists()
        locations = self.get_user_locations(user_id)
        if location_uid not in locations:
            return False  # Not subscribed
        
        locations.remove(location_uid)
        self._save_user_locations(user_id, locations)
        return True

    def remove_user(self, user_id: int):
        """Completely remove a user and all their subscriptions from users.csv."""
        self.ensure_csv_exists()
        try:
            rows = []
            user_id_str = str(user_id)
            user_removed = False
            
            with open(USERS_CSV, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row["userId"] != user_id_str:
                        rows.append(row)
                    else:
                        user_removed = True
                        
            if user_removed:
                with open(USERS_CSV, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=["userId", "locations"])
                    writer.writeheader()
                    writer.writerows(rows)
                logger.info(f"Removed user {user_id} completely from users.csv (blocked/deactivated)")
        except Exception as e:
            logger.error(f"Error removing user {user_id} from CSV: {e}")

    def _save_user_locations(self, user_id: int, locations: Set[str]):
        """Save user locations to CSV."""
        rows = []
        user_found = False
        user_id_str = str(user_id)
        locations_str = ",".join(sorted(locations)) if locations else ""

        try:
            if USERS_CSV.exists():
                with open(USERS_CSV, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if row["userId"] == user_id_str:
                            user_found = True
                            rows.append({"userId": user_id_str, "locations": locations_str})
                        else:
                            rows.append(row)

            if not user_found:
                rows.append({"userId": user_id_str, "locations": locations_str})

            with open(USERS_CSV, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["userId", "locations"])
                writer.writeheader()
                writer.writerows(rows)
        except Exception as e:
            logger.error(f"Error saving user locations: {e}")


class AlertsPollerManager:
    """Manages API polling and change detection."""

    def __init__(self):
        self.last_response: Dict = {}
        self.last_modified: Optional[str] = None
        self.http_client: Optional[httpx.AsyncClient] = None
        self.load_last_response()

    def load_last_response(self):
        """Load last API response from file."""
        try:
            if LAST_API_RESPONSE_FILE.exists():
                with open(LAST_API_RESPONSE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.last_response = data.get("alerts", {})
                    self.last_modified = data.get("last_modified")
                logger.info("Loaded last API response")
        except Exception as e:
            logger.error(f"Error loading last response: {e}")

    def save_response(self, alerts_data: List[Dict], last_modified: str):
        """Save API response to file."""
        try:
            # Convert alerts list to dict keyed by location_uid for easier comparison
            alerts_dict = {}
            for alert in alerts_data:
                uid = alert.get("location_uid")
                if uid:
                    alerts_dict[uid] = alert

            data = {
                "alerts": alerts_dict,
                "last_modified": last_modified,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            with open(LAST_API_RESPONSE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.last_response = alerts_dict
            self.last_modified = last_modified
        except Exception as e:
            logger.error(f"Error saving response: {e}")

    async def poll_alerts(self) -> Tuple[List[Dict], Optional[str]]:
        """Poll alerts API with conditional request."""
        if not self.http_client:
            self.http_client = httpx.AsyncClient()

        headers = {"Authorization": f"Bearer {ALERTS_API_TOKEN}"}
        if self.last_modified:
            headers["If-Modified-Since"] = self.last_modified

        try:
            response = await self.http_client.get(ALERTS_API_URL, headers=headers, timeout=10)

            if response.status_code == 304:
                logger.debug("API returned 304 Not Modified")
                return [], None

            response.raise_for_status()
            data = response.json()
            
            last_modified = response.headers.get("Last-Modified")
            alerts = data.get("alerts", [])
            
            return alerts, last_modified
        except httpx.HTTPError as e:
            logger.error(f"HTTP error polling alerts: {e}")
            return [], None
        except Exception as e:
            logger.error(f"Error polling alerts: {e}")
            return [], None

    def detect_changes(self, new_alerts: List[Dict]) -> Dict[str, Dict]:
        """
        Detect changes between old and new alerts.
        Returns dict of location_uid -> change_info
        """
        changes = {}
        new_alerts_by_uid = {a.get("location_uid"): a for a in new_alerts}
        
        # Check for new alerts and threat changes
        for location_uid, alert in new_alerts_by_uid.items():
            old_alert = self.last_response.get(location_uid)
            
            if not old_alert:
                # Case 1: New alert started
                changes[location_uid] = {
                    "type": "new_alert",
                    "alert": alert,
                    "specific_threat": None, # Will use main alert / first threat
                }
            else:
                # Check for new threats
                old_threats = set()
                new_threats_list = alert.get("threats", [])
                
                for threat in old_alert.get("threats", []):
                    threat_key = (threat.get("threat_type"), threat.get("level"))
                    old_threats.add(threat_key)
                
                added_threats = []
                for threat in new_threats_list:
                    threat_key = (threat.get("threat_type"), threat.get("level"))
                    if threat_key not in old_threats:
                        added_threats.append(threat)
                
                if added_threats:
                    # Case 2: New threat(s) added; focus on the newly added threat (threat2)
                    changes[location_uid] = {
                        "type": "new_threat",
                        "alert": alert,
                        "specific_threat": added_threats[0], # The newly added threat
                    }

        # Check for cancelled alerts
        for location_uid, old_alert in self.last_response.items():
            if location_uid not in new_alerts_by_uid:
                # Alert was cancelled
                changes[location_uid] = {
                    "type": "alert_cancelled",
                    "alert": old_alert,
                }

        return changes


# Global managers
location_manager = LocationManager()
user_manager = UserManager()
alerts_manager = AlertsPollerManager()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command."""
    keyboard = [
        [
            InlineKeyboardButton(MESSAGES["add_location"], callback_data="add"),
            InlineKeyboardButton(MESSAGES["remove_location"], callback_data="remove"),
        ],
        [InlineKeyboardButton(MESSAGES["view_subscriptions"], callback_data="view")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(MESSAGES["start"], reply_markup=reply_markup)


async def backup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Secret admin command to manually backup users.csv."""
    user_id = update.effective_user.id
    
    # Only allow admin user
    if user_id != ADMIN_USER_ID:
        await update.message.reply_text("❌ Unauthorized. This command is only available to administrators.")
        logger.warning(f"Unauthorized backup attempt from user {user_id}")
        return
    
    await update.message.reply_text("⏳ Performing manual backup...")
    
    success = await _perform_backup(context.application, backup_type="manual")
    
    if success:
        await update.message.reply_text("✅ Manual backup completed successfully!")
    else:
        await update.message.reply_text("❌ Backup failed. Check logs for details.")


def restore_users_from_telegram_sync():
    """Synchronously restore users.csv from Telegram on startup before bot boots up."""
    if not BACKUP_CHAT_ID or not TELEGRAM_BOT_TOKEN:
        logger.warning("BACKUP_CHAT_ID or TELEGRAM_BOT_TOKEN not set. Skipping Telegram restore.")
        return

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
        
        # 1. Get chat info to check for a pinned backup message
        chat_res = httpx.get(f"{url}/getChat", params={"chat_id": BACKUP_CHAT_ID}, timeout=10.0).json()
        if not chat_res.get("ok"):
            logger.error(f"Failed to get backup chat: {chat_res}")
            return
            
        pinned_msg = chat_res.get("result", {}).get("pinned_message")
        if not pinned_msg or not pinned_msg.get("document"):
            logger.info("No pinned backup document found in BACKUP_CHAT_ID. Starting with fresh users.csv.")
            return
            
        file_id = pinned_msg["document"]["file_id"]
        
        # 2. Get file path from Telegram servers
        file_res = httpx.get(f"{url}/getFile", params={"file_id": file_id}, timeout=10.0).json()
        if not file_res.get("ok"):
            logger.error(f"Failed to get file path: {file_res}")
            return
            
        file_path = file_res["result"]["file_path"]
        
        # 3. Download the actual CSV bytes
        download_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
        file_data = httpx.get(download_url, timeout=30.0).content
        
        # 4. Overwrite local users.csv with restored data
        with open(USERS_CSV, "wb") as f:
            f.write(file_data)
            
        logger.info("Successfully restored users.csv from Telegram backup!")
    except Exception as e:
        logger.error(f"Error restoring users from Telegram: {e}")


async def _perform_backup(application: Application, backup_type: str = "automatic"):
    """Helper function to perform backup of users.csv to Telegram.
    
    Args:
        application: Telegram bot application
        backup_type: Either "automatic" or "manual"
    """
    if not BACKUP_CHAT_ID:
        logger.warning("BACKUP_CHAT_ID not set. Cannot backup.")
        return False

    try:
        if USERS_CSV.exists() and USERS_CSV.stat().st_size > 0:
            # 1. Fetch current chat info to see if there is already a pinned message
            old_pinned_message_id = None
            try:
                chat_info = await application.bot.get_chat(chat_id=BACKUP_CHAT_ID)
                if chat_info.pinned_message:
                    old_pinned_message_id = chat_info.pinned_message.message_id
            except Exception as e:
                logger.debug(f"Could not retrieve existing pinned message: {e}")

            # 2. Send the new backup document
            with open(USERS_CSV, "rb") as f:
                caption = f"{'🛡️ Automatic' if backup_type == 'automatic' else '👨‍💻 Manual'} DB Backup: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
                sent_message = await application.bot.send_document(
                    chat_id=BACKUP_CHAT_ID,
                    document=f,
                    filename="users.csv",
                    caption=caption
                )
            
            # 3. Pin the new backup message
            await application.bot.pin_chat_message(
                chat_id=BACKUP_CHAT_ID, 
                message_id=sent_message.message_id,
                disable_notification=True  # Keeps notifications quiet
            )
            
            # 4. Unpin the old backup message to prevent clutter
            if old_pinned_message_id:
                try:
                    await application.bot.unpin_chat_message(
                        chat_id=BACKUP_CHAT_ID, 
                        message_id=old_pinned_message_id
                    )
                except Exception as e:
                    logger.debug(f"Could not unpin old message {old_pinned_message_id}: {e}")

            logger.info(f"Successfully sent, pinned, and cleaned up {backup_type} users.csv backup in Telegram.")
            return True
        else:
            logger.warning("users.csv is missing or empty. Skipping backup.")
            return False
    except Exception as e:
        logger.error(f"Error in backup: {e}")
        return False


async def backup_worker(application: Application):
    """Periodically backs up users.csv to a private Telegram chat/channel, only on user count changes."""
    if not BACKUP_CHAT_ID:
        logger.info("BACKUP_CHAT_ID not set. Periodic backups are disabled.")
        return

    logger.info("Starting backup worker")
    # Wait 1 minute after startup before the first backup
    await asyncio.sleep(60)

    last_user_count = 0

    while True:
        try:
            # Count current users in CSV
            current_user_count = 0
            if USERS_CSV.exists():
                with open(USERS_CSV, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    current_user_count = sum(1 for _ in reader)

            # Only backup if user count changed
            if current_user_count != last_user_count:
                logger.info(f"User count changed from {last_user_count} to {current_user_count}. Triggering backup.")
                await _perform_backup(application, backup_type="automatic")
                last_user_count = current_user_count
            else:
                logger.debug(f"User count unchanged ({current_user_count}). Skipping backup.")
        except Exception as e:
            logger.error(f"Error in backup worker: {e}")

        # Check every 1 hour for user count changes
        await asyncio.sleep(3600)


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button presses."""
    query = update.callback_query
    await query.answer()

    if query.data == "noop":
        return
    elif query.data == "add":
        await show_regions(query, context, "add")
    elif query.data == "remove":
        await show_remove_menu(query, context)
    elif query.data == "view":
        await show_subscriptions(query, context)
    elif query.data.startswith("region_"):
        parent_uid = query.data.split("_")[1]
        if context.user_data.get("action") == "add":
            await show_subregions(query, context, parent_uid)
        elif context.user_data.get("action") == "remove":
            await show_remove_subregions(query, context, parent_uid)
    elif query.data.startswith("suball_"):
        # NEW: Handle subscribing to all child locations
        parent_uid = query.data.split("_")[1]
        await subscribe_all_subregions(query, context, parent_uid)
    elif query.data.startswith("select_"):
        location_uid = query.data.split("_")[1]
        if context.user_data.get("action") == "add":
            await add_location(query, context, location_uid)
        elif context.user_data.get("action") == "remove":
            await remove_location(query, context, location_uid)
    elif query.data == "back":
        await show_regions(query, context, context.user_data.get("action", "add"))


async def show_regions(query, context, action: str):
    """Show available regions."""
    context.user_data["action"] = action
    regions = location_manager.get_regions()
    
    if not regions:
        await query.edit_message_text(MESSAGES["no_locations"])
        return

    keyboard = []
    for uid, name in sorted(regions.items(), key=lambda x: x[1]):
        keyboard.append(
            [InlineKeyboardButton(name, callback_data=f"region_{uid}")]
        )
    keyboard.append([InlineKeyboardButton(MESSAGES["back"], callback_data="back")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(MESSAGES["select_region"], reply_markup=reply_markup)


async def show_subregions(query, context, parent_uid: str):
    """Show subregions for selected region with 'Subscribe to all' as the first option (only if children exist)."""
    context.user_data["parent_uid"] = parent_uid
    subregions = location_manager.get_subregions(parent_uid)
    parent_name = location_manager.get_location_name(parent_uid)

    # If there are NO child locations (e.g., Kyiv, Sevastopol), skip "Subscribe to all" 
    # and show direct subscription/status option.
    if not subregions:
        user_id = query.from_user.id
        locations = user_manager.get_user_locations(user_id)
        
        if parent_uid in locations:
            keyboard = [[InlineKeyboardButton(MESSAGES["back"], callback_data="back")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                MESSAGES["already_subscribed"] + f"\n\n{parent_name}",
                reply_markup=reply_markup
            )
        else:
            keyboard = [
                [InlineKeyboardButton(f"✅ Підписатися на {parent_name}", 
                                    callback_data=f"select_{parent_uid}")],
                [InlineKeyboardButton(MESSAGES["back"], callback_data="back")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(parent_name, reply_markup=reply_markup)
        return

    # If subregions DO exist, show "Subscribe to all" as the FIRST option, followed by individual districts
    keyboard = [
        [InlineKeyboardButton(f"🌐 Підписатися на всі райони ({parent_name})", callback_data=f"suball_{parent_uid}")]
    ]
    
    for uid, name in sorted(subregions.items(), key=lambda x: x[1]):
        keyboard.append(
            [InlineKeyboardButton(name, callback_data=f"select_{uid}")]
        )
        
    keyboard.append([InlineKeyboardButton(MESSAGES["back"], callback_data="back")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(MESSAGES["select_subregion"], reply_markup=reply_markup)


async def subscribe_all_subregions(query, context, parent_uid: str):
    """Subscribe user to all subregions of a given parent region and send active alerts."""
    user_id = query.from_user.id
    subregions = location_manager.get_subregions(parent_uid)
    parent_name = location_manager.get_location_name(parent_uid)
    
    added_count = 0
    for uid in subregions.keys():
        if user_manager.add_location(user_id, uid):
            added_count += 1
            # NEW: Send active status for each newly added subregion if alerts are active
            await send_current_status_if_any(context.bot, user_id, uid)

    keyboard = [[InlineKeyboardButton(MESSAGES["back"], callback_data="back")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if added_count > 0:
        text = f"✅ Успішно підписано на всі локації ({added_count}) регіону:\n<b>{parent_name}</b>"
    else:
        text = f"⚠️ Ви вже підписані на всі локації регіону:\n<b>{parent_name}</b>"

    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")


async def send_current_status_if_any(bot, user_id: int, location_uid: str):
    """Check if there is an active alert for a location and send it to the user upon subscribing."""
    try:
        active_alert = alerts_manager.last_response.get(location_uid)
        
        # Define location_title safely beforehand
        location_title = (
            (active_alert.get("location_title") if active_alert else None) 
            or location_manager.get_location_name(location_uid) 
            or "Локація"
        )

        if not active_alert:
            message = f"✅ <b>Поточний статус:</b>\n{LEVEL_ICON.get('green', '🟢')} {location_title}: немає тривоги"
        else:
            alert_level = active_alert.get("alert_level", "red")
            threats = active_alert.get("threats", [])
            if threats:
                threat = threats[0]
                source_msg = threat.get("source_message") or threat.get("threat_type")
                threat_level = threat.get("level", alert_level)
                message = f"🚨 <b>Поточний статус:</b>\n{LEVEL_ICON.get(threat_level, '🟡')} {location_title}: {source_msg}"
            else:
                alert_name = ALERT_TYPE_MAP.get(active_alert.get("alert_type"), "Тривога")
                message = f"🚨 <b>Поточний статус:</b>\n{LEVEL_ICON.get(alert_level, '🟡')} {location_title}: {alert_name}"

        await bot.send_message(
            chat_id=user_id,
            text=message,
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error sending initial status for location {location_uid} to user {user_id}: {e}")


async def add_location(query, context, location_uid: str):
    """Add location to user subscriptions."""
    user_id = query.from_user.id
    location_name = location_manager.get_location_name(location_uid)

    if user_manager.add_location(user_id, location_uid):
        # NEW: Check and send current status if an alert is active right now
        await send_current_status_if_any(context.bot, user_id, location_uid)

        keyboard = [[InlineKeyboardButton(MESSAGES["back"], callback_data="back")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            MESSAGES["added"].format(location=location_name),
            reply_markup=reply_markup,
        )
    else:
        keyboard = [[InlineKeyboardButton(MESSAGES["back"], callback_data="back")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            MESSAGES["already_subscribed"] + f"\n\n{location_name}",
            reply_markup=reply_markup,
        )


async def show_remove_menu(query, context):
    """Show menu to remove locations."""
    context.user_data["action"] = "remove"
    regions = location_manager.get_regions()
    
    keyboard = []
    for uid, name in sorted(regions.items(), key=lambda x: x[1]):
        keyboard.append(
            [InlineKeyboardButton(name, callback_data=f"region_{uid}")]
        )
    keyboard.append([InlineKeyboardButton(MESSAGES["back"], callback_data="back")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(MESSAGES["select_to_remove"], reply_markup=reply_markup)


async def show_remove_subregions(query, context, parent_uid: str):
    """Show subregions for removal."""
    context.user_data["parent_uid"] = parent_uid
    subregions = location_manager.get_subregions(parent_uid)
    user_id = query.from_user.id
    user_locations = user_manager.get_user_locations(user_id)

    # If no subregions, allow removing the parent region itself
    if not subregions:
        parent_name = location_manager.get_location_name(parent_uid)
        
        if parent_uid not in user_locations:
            await query.edit_message_text(
                MESSAGES["not_subscribed"] + f"\n\n{parent_name}"
            )
        else:
            keyboard = [
                [InlineKeyboardButton(f"🗑️ Видалити {parent_name}", 
                                    callback_data=f"select_{parent_uid}")],
                [InlineKeyboardButton(MESSAGES["back"], callback_data="back")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(parent_name, reply_markup=reply_markup)
        return

    keyboard = []
    for uid, name in sorted(subregions.items(), key=lambda x: x[1]):
        # Only show locations user is subscribed to
        if uid in user_locations:
            keyboard.append(
                [InlineKeyboardButton(name, callback_data=f"select_{uid}")]
            )
    
    if not keyboard:
        keyboard.append([InlineKeyboardButton(MESSAGES["no_subscriptions"], callback_data="noop")])
    
    keyboard.append([InlineKeyboardButton(MESSAGES["back"], callback_data="back")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(MESSAGES["select_to_remove"], reply_markup=reply_markup)


async def remove_location(query, context, location_uid: str):
    """Remove location from user subscriptions."""
    user_id = query.from_user.id
    location_name = location_manager.get_location_name(location_uid)

    if user_manager.remove_location(user_id, location_uid):
        keyboard = [[InlineKeyboardButton(MESSAGES["back"], callback_data="back")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            MESSAGES["removed"].format(location=location_name),
            reply_markup=reply_markup,
        )
    else:
        keyboard = [[InlineKeyboardButton(MESSAGES["back"], callback_data="back")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            MESSAGES["not_subscribed"] + f"\n\n{location_name}",
            reply_markup=reply_markup,
        )


async def show_subscriptions(query, context):
    """Show user's current subscriptions."""
    user_id = query.from_user.id
    locations = user_manager.get_user_locations(user_id)

    if not locations:
        text = MESSAGES["no_subscriptions"]
    else:
        location_names = []
        for uid in sorted(locations):
            name = location_manager.get_location_name(uid)
            if name:
                location_names.append(f"• {name}")
        text = MESSAGES["subscriptions"].format(locations="\n".join(location_names))

    keyboard = [[InlineKeyboardButton(MESSAGES["back"], callback_data="back")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup)


async def alerts_poller(application: Application):
    """Background task to poll alerts and send notifications."""
    logger.info("Starting alerts poller")
    
    while True:
        try:
            # Poll API
            new_alerts, last_modified = await alerts_manager.poll_alerts()
            
            if new_alerts and last_modified:
                # Detect changes
                changes = alerts_manager.detect_changes(new_alerts)
                
                # Send notifications to affected users
                for location_uid, change_info in changes.items():
                    await send_notifications(
                        application, location_uid, change_info
                    )
                
                # Save response for next comparison
                alerts_manager.save_response(new_alerts, last_modified)
            
            # Wait 10 seconds before next poll
            await asyncio.sleep(10)
        except Exception as e:
            logger.error(f"Error in alerts poller: {e}")
            await asyncio.sleep(10)


async def send_notifications(
    application: Application, location_uid: str, change_info: Dict
):
    """Send notifications to users subscribed to this location."""
    try:
        alert = change_info["alert"]
        alert_type = change_info["type"]
        location_title = alert.get("location_title", "Unknown")
        alert_level = alert.get("alert_level", "red")
        specific_threat = change_info.get("specific_threat")
        
        # Prepare message based on change type
        if alert_type == "alert_cancelled":
            # 🟢 Explicitly force the icon to green for any cancellation notification
            message = f"🟢 {location_title}: відбій тривоги"
        elif alert_type == "new_threat" and specific_threat:
            # Send message specifically for the newly added threat
            source_msg = specific_threat.get("source_message") or ALERT_TYPE_MAP.get(specific_threat.get("threat_type"), specific_threat.get("threat_type"))
            threat_level = specific_threat.get("level", alert_level)
            message = f"{LEVEL_ICON.get(threat_level, '🟡')} {location_title}: {source_msg}"
        else:
            # New alert (or fallback) -> send message with threat1 (first threat or general alert type)
            threats = alert.get("threats", [])
            if threats:
                threat = threats[0]
                source_msg = threat.get("source_message") or ALERT_TYPE_MAP.get(threat.get("threat_type"), threat.get("threat_type"))
                threat_level = threat.get("level", alert_level)
                message = f"{LEVEL_ICON.get(threat_level, '🟡')} {location_title}: {source_msg}"
            else:
                alert_name = ALERT_TYPE_MAP.get(alert.get("alert_type"), "Тривога")
                message = f"{LEVEL_ICON.get(alert_level, '🟡')} {location_title}: {alert_name}"
        
        # Find all users subscribed to this location
        all_users = set()
        if USERS_CSV.exists():
            with open(USERS_CSV, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    locations_str = row.get("locations", "")
                    if location_uid in locations_str.split(","):
                        try:
                            user_id = int(row["userId"])
                            all_users.add(user_id)
                        except ValueError:
                            pass
        
        # Send message to each user
        for user_id in all_users:
            try:
                await application.bot.send_message(
                    chat_id=user_id,
                    text=message,
                    parse_mode="HTML"
                )
            except Forbidden:
                logger.warning(f"User {user_id} has blocked the bot or deactivated account. Removing via UserManager.")
                user_manager.remove_user(user_id)
            except Exception as e:
                logger.error(f"Error sending notification to {user_id}: {e}")
    except Exception as e:
        logger.error(f"Error preparing notifications: {e}")

async def set_bot_commands(application: Application):
    """Set up the Telegram menu button commands."""
    commands = [
        BotCommand("start", "🏠 Відкрити головне меню"),
    ]
    await application.bot.set_my_commands(commands)

async def handle_ping(request):
    """Simple health-check endpoint to keep Render awake."""
    return web.Response(text="I am alive!")

async def start_web_server():
    """Starts a lightweight web server for Render's port binding."""
    app = web.Application()
    app.router.add_get("/", handle_ping)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    # Render assigns a port via the PORT environment variable (defaults to 10000)
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Web server started on port {port}")

async def post_init(application: Application):
    """Post initialization hook to start background tasks."""
    await set_bot_commands(application)

    # Start the web server so Render sees incoming activity
    await start_web_server()
    
    # Start your bot's other background tasks (like alerts poller)
    asyncio.create_task(alerts_poller(application))
    asyncio.create_task(backup_worker(application))


def main():
    """Main function to run the bot."""
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set")
    if not ALERTS_API_TOKEN:
        raise ValueError("ALERTS_API_TOKEN environment variable not set")

    # 📌 1. Restore database from Telegram before bot boots up
    restore_users_from_telegram_sync()

    # Create application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("backup", backup_command))
    application.add_handler(CallbackQueryHandler(button_callback))

    # Set post_init to start background tasks
    application.post_init = post_init

    # Start polling
    logger.info("Starting bot")
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
