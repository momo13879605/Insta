import os
import asyncio
import aiohttp
import logging
import math
import time
import shutil
import psutil
import hashlib
import json
from typing import Optional, Tuple, Dict, List
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor

from pyrogram import Client, filters, idle
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import FloodWait, RPCError, BadRequest
from pyrogram.enums import ParseMode, MessageMediaType
from pyrogram.raw.types import InputFile, InputFileBig

# ==================== تنظیمات اصلی ====================
class Config:
    # تنظیمات تلگرام (این مقادیر را با اطلاعات ربات خود جایگزین کنید)
    API_ID = 21822238  # از https://my.telegram.org/apps دریافت کنید
    API_HASH = "ebcf1d2bded42ee86d4a2e6a55d28b39"  # از https://my.telegram.org/apps دریافت کنید
    BOT_TOKEN = "8353195434:AAF5_F3DdFb7yfOY8HoQmH6pQ1eIdnn63c0"  # از @BotFather دریافت کنید
    
    # تنظیمات مدیران ربات
    ADMIN_IDS = [5914346958]  # شناسه کاربران مدیر
    
    # تنظیمات مسیرها
    BASE_DIR = Path(__file__).parent.absolute()
    DOWNLOAD_PATH = BASE_DIR / "downloads"
    TEMP_PATH = BASE_DIR / "temp"
    UPLOAD_PATH = BASE_DIR / "uploads"
    DATABASE_FILE = BASE_DIR / "bot_data.json"
    
    # محدودیت‌ها
    MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2GB - حداکثر حجم برای ربات‌های تلگرام
    MAX_UPLOAD_SIZE = 2 * 1024 * 1024 * 1024  # 2GB - حداکثر آپلود
    MAX_DOWNLOAD_SIZE = 2 * 1024 * 1024 * 1024  # 2GB - حداکثر دانلود
    
    # تنظیمات دانلود/آپلود
    DOWNLOAD_CHUNK_SIZE = 1024 * 1024  # 1MB
    UPLOAD_CHUNK_SIZE = 512 * 1024  # 512KB
    MAX_CONCURRENT_DOWNLOADS = 5  # حداکثر دانلود همزمان
    MAX_CONCURRENT_UPLOADS = 3  # حداکثر آپلود همزمان
    
    # تنظیمات زمان
    DOWNLOAD_TIMEOUT = 3600  # 1 ساعت
    UPLOAD_TIMEOUT = 3600  # 1 ساعت
    CONNECTION_TIMEOUT = 30  # 30 ثانیه
    
    # تنظیمات سیستم
    CLEANUP_AFTER_HOURS = 6  # پاکسازی فایل‌های قدیمی‌تر از 6 ساعت
    MAX_TEMP_FILES = 100  # حداکثر تعداد فایل‌های موقت
    LOG_LEVEL = logging.INFO

# ==================== تنظیمات لاگ ====================
logging.basicConfig(
    level=Config.LOG_LEVEL,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(Config.BASE_DIR / 'bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ==================== ایجاد دایرکتوری‌ها ====================
Config.DOWNLOAD_PATH.mkdir(exist_ok=True, parents=True)
Config.TEMP_PATH.mkdir(exist_ok=True, parents=True)
Config.UPLOAD_PATH.mkdir(exist_ok=True, parents=True)

# ==================== دیتابیس ساده ====================
class SimpleDatabase:
    def __init__(self, db_file):
        self.db_file = db_file
        self.data = self.load_data()
    
    def load_data(self):
        """بارگذاری داده‌ها از فایل"""
        if self.db_file.exists():
            try:
                with open(self.db_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {"users": {}, "stats": {}, "settings": {}}
        return {"users": {}, "stats": {}, "settings": {}}
    
    def save_data(self):
        """ذخیره داده‌ها در فایل"""
        try:
            with open(self.db_file, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error(f"Error saving database: {e}")
            return False
    
    def update_user_stats(self, user_id: int, downloaded_bytes: int = 0, uploaded_bytes: int = 0):
        """بروزرسانی آمار کاربر"""
        user_id = str(user_id)
        if user_id not in self.data["users"]:
            self.data["users"][user_id] = {
                "total_downloaded": 0,
                "total_uploaded": 0,
                "files_count": 0,
                "last_active": datetime.now().isoformat()
            }
        
        user = self.data["users"][user_id]
        user["total_downloaded"] += downloaded_bytes
        user["total_uploaded"] += uploaded_bytes
        if downloaded_bytes > 0:
            user["files_count"] += 1
        user["last_active"] = datetime.now().isoformat()
        
        # بروزرسانی آمار کلی
        if "total_stats" not in self.data["stats"]:
            self.data["stats"]["total_stats"] = {
                "total_downloaded": 0,
                "total_uploaded": 0,
                "total_files": 0
            }
        
        stats = self.data["stats"]["total_stats"]
        stats["total_downloaded"] += downloaded_bytes
        stats["total_uploaded"] += uploaded_bytes
        if downloaded_bytes > 0:
            stats["total_files"] += 1
        
        self.save_data()
    
    def get_user_stats(self, user_id: int):
        """دریافت آمار کاربر"""
        user_id = str(user_id)
        return self.data["users"].get(user_id, {})
    
    def get_total_stats(self):
        """دریافت آمار کلی"""
        return self.data["stats"].get("total_stats", {})

# ==================== مدیر دانلود پیشرفته ====================
class AdvancedDownloadManager:
    def __init__(self):
        self.active_downloads: Dict[str, Dict] = {}
        self.active_uploads: Dict[str, Dict] = {}
        self.session: Optional[aiohttp.ClientSession] = None
        self.db = SimpleDatabase(Config.DATABASE_FILE)
        self.executor = ThreadPoolExecutor(max_workers=10)
        self.download_semaphore = asyncio.Semaphore(Config.MAX_CONCURRENT_DOWNLOADS)
        self.upload_semaphore = asyncio.Semaphore(Config.MAX_CONCURRENT_UPLOADS)
        self.cleanup_task = None
        
    async def get_session(self) -> aiohttp.ClientSession:
        """ایجاد یا برگشت session"""
        if self.session is None or self.session.closed:
            connector = aiohttp.TCPConnector(limit=50, ttl_dns_cache=300, force_close=True)
            timeout = aiohttp.ClientTimeout(
                total=Config.DOWNLOAD_TIMEOUT,
                connect=Config.CONNECTION_TIMEOUT,
                sock_read=Config.CONNECTION_TIMEOUT
            )
            self.session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': '*/*',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'Connection': 'keep-alive'
                }
            )
        return self.session
        
    async def close_session(self):
        """بستن session"""
        if self.session and not self.session.closed:
            await self.session.close()
    
    def generate_file_id(self, url: str) -> str:
        """تولید شناسه یکتا برای فایل"""
        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
        timestamp = int(time.time())
        return f"{timestamp}_{url_hash}"
    
    async def validate_url(self, url: str) -> Tuple[bool, str, Dict]:
        """اعتبارسنجی کامل URL"""
        try:
            parsed = urlparse(url)
            
            # بررسی scheme
            if parsed.scheme not in ['http', 'https']:
                return False, "❌ پروتکل باید HTTP یا HTTPS باشد", {}
            
            # بررسی host
            if not parsed.netloc:
                return False, "❌ آدرس سرور نامعتبر است", {}
            
            # بررسی اتصال
            session = await self.get_session()
            try:
                async with session.head(
                    url, 
                    allow_redirects=True, 
                    timeout=Config.CONNECTION_TIMEOUT
                ) as resp:
                    
                    if resp.status != 200:
                        return False, f"❌ سرور با کد {resp.status} پاسخ داد", {}
                    
                    # جمع‌آوری اطلاعات هدر
                    headers_info = {
                        'content-type': resp.headers.get('Content-Type', ''),
                        'content-length': resp.headers.get('Content-Length', '0'),
                        'accept-ranges': resp.headers.get('Accept-Ranges', 'none'),
                        'last-modified': resp.headers.get('Last-Modified', ''),
                        'etag': resp.headers.get('ETag', '')
                    }
                    
                    return True, "✅ لینک معتبر است", headers_info
                    
            except asyncio.TimeoutError:
                return False, "⏳ اتصال به سرور timeout خورد", {}
            except aiohttp.ClientError as e:
                return False, f"🌐 خطای شبکه: {str(e)}", {}
                
        except Exception as e:
            return False, f"⚠️ خطای ناشناخته: {str(e)}", {}
    
    def parse_filename(self, url: str, content_type: str = "") -> str:
        """استخراج نام فایل از URL"""
        import re
        
        # از URL استخراج کن
        parsed = urlparse(url)
        path = parsed.path
        
        if path:
            filename = os.path.basename(path).strip()
            if filename and '.' in filename:
                # حذف پارامترهای اضافی
                filename = re.sub(r'[?&].*$', '', filename)
                filename = re.sub(r'[<>:"/\\|?*]', '_', filename)  # حذف کاراکترهای نامعتبر
                
                if len(filename) > 200:
                    name, ext = os.path.splitext(filename)
                    filename = name[:150] + ext
                
                if filename:
                    return filename
        
        # اگر از URL نامعتبر بود، از content-type استفاده کن
        from mimetypes import guess_extension
        
        ext = ""
        if content_type:
            guessed_ext = guess_extension(content_type.split(';')[0].strip())
            if guessed_ext:
                ext = guessed_ext
        
        # نام بر اساس تاریخ و زمان
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"file_{timestamp}{ext if ext else '.bin'}"
    
    async def get_detailed_file_info(self, url: str) -> Tuple[bool, Dict]:
        """دریافت اطلاعات کامل فایل"""
        try:
            session = await self.get_session()
            
            async with session.head(
                url, 
                allow_redirects=True, 
                timeout=Config.CONNECTION_TIMEOUT
            ) as resp:
                
                if resp.status != 200:
                    return False, {"error": f"HTTP {resp.status}", "status": "error"}
                
                # خواندن حجم فایل
                content_length = resp.headers.get('Content-Length')
                file_size = int(content_length) if content_length and content_length.isdigit() else 0
                
                # بررسی محدودیت حجم
                if file_size > Config.MAX_DOWNLOAD_SIZE:
                    return False, {
                        "error": f"حجم فایل ({self.format_size(file_size)}) بیش از حد مجاز ({self.format_size(Config.MAX_DOWNLOAD_SIZE)}) است",
                        "status": "too_large"
                    }
                
                # جمع‌آوری اطلاعات
                info = {
                    "size": file_size,
                    "content_type": resp.headers.get('Content-Type', 'application/octet-stream'),
                    "accept_ranges": resp.headers.get('Accept-Ranges') == 'bytes',
                    "last_modified": resp.headers.get('Last-Modified', ''),
                    "etag": resp.headers.get('ETag', ''),
                    "filename": self.parse_filename(url, resp.headers.get('Content-Type', '')),
                    "server": resp.headers.get('Server', 'Unknown'),
                    "url": url,
                    "status": "available"
                }
                
                return True, info
                
        except Exception as e:
            return False, {"error": str(e), "status": "error"}
    
    async def download_with_progress(self, url: str, filepath: str, 
                                     message: Message, file_size: int) -> Tuple[bool, int]:
        """دانلود با نمایش پیشرفت"""
        downloaded = 0
        start_time = time.time()
        last_update_time = start_time
        
        # بررسی فایل نیمه تمام
        if os.path.exists(filepath):
            downloaded = os.path.getsize(filepath)
            logger.info(f"Resuming download from {self.format_size(downloaded)}")
        
        headers = {}
        if downloaded > 0:
            headers['Range'] = f'bytes={downloaded}-'
        
        try:
            session = await self.get_session()
            
            async with session.get(
                url, 
                headers=headers,
                timeout=Config.DOWNLOAD_TIMEOUT
            ) as response:
                
                if response.status not in [200, 206]:
                    return False, downloaded
                
                mode = 'ab' if downloaded > 0 else 'wb'
                with open(filepath, mode) as f:
                    async for chunk in response.content.iter_chunked(Config.DOWNLOAD_CHUNK_SIZE):
                        if not chunk:
                            break
                        
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        # آپدیت وضعیت هر 3 ثانیه یا هر 5%
                        current_time = time.time()
                        progress_percent = (downloaded / file_size) * 100 if file_size > 0 else 0
                        
                        if current_time - last_update_time >= 3 or progress_percent >= 100:
                            elapsed = current_time - start_time
                            speed = downloaded / elapsed if elapsed > 0 else 0
                            remaining = (file_size - downloaded) / speed if speed > 0 and file_size > downloaded else 0
                            
                            try:
                                await message.edit_text(
                                    self.create_progress_text(
                                        downloaded, file_size, progress_percent,
                                        speed, remaining, "دانلود"
                                    ),
                                    parse_mode=ParseMode.MARKDOWN
                                )
                            except FloodWait as e:
                                await asyncio.sleep(e.value)
                            except Exception:
                                pass
                            
                            last_update_time = current_time
                
                # بررسی صحت دانلود
                actual_size = os.path.getsize(filepath)
                if file_size > 0 and actual_size < file_size:
                    logger.warning(f"Incomplete download: {actual_size}/{file_size}")
                    return False, actual_size
                
                return True, downloaded
                
        except Exception as e:
            logger.error(f"Download error: {e}")
            return False, downloaded
    
    async def upload_with_progress(self, client: Client, chat_id: int, 
                                   filepath: str, message: Message, 
                                   caption: str = "") -> bool:
        """آپلود با نمایش پیشرفت"""
        try:
            file_size = os.path.getsize(filepath)
            filename = os.path.basename(filepath)
            
            # آماده‌سازی اطلاعات آپلود
            upload_start_time = time.time()
            
            # تابع کالبک برای پیشرفت
            async def progress_callback(current, total):
                try:
                    progress_percent = (current / total) * 100
                    elapsed = time.time() - upload_start_time
                    speed = current / elapsed if elapsed > 0 else 0
                    remaining = (total - current) / speed if speed > 0 and current < total else 0
                    
                    # فقط هر 5% یا در انتها آپدیت کن
                    if int(progress_percent) % 5 == 0 or current >= total:
                        await message.edit_text(
                            self.create_progress_text(
                                current, total, progress_percent,
                                speed, remaining, "آپلود"
                            ),
                            parse_mode=ParseMode.MARKDOWN
                        )
                except Exception:
                    pass
            
            # ارسال فایل بر اساس نوع
            ext = os.path.splitext(filename)[1].lower()
            
            if ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']:
                await client.send_photo(
                    chat_id=chat_id,
                    photo=filepath,
                    caption=caption[:1024],
                    progress=progress_callback
                )
            elif ext in ['.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv']:
                await client.send_video(
                    chat_id=chat_id,
                    video=filepath,
                    caption=caption[:1024],
                    progress=progress_callback,
                    supports_streaming=True
                )
            elif ext in ['.mp3', '.wav', '.ogg', '.m4a', '.flac']:
                await client.send_audio(
                    chat_id=chat_id,
                    audio=filepath,
                    caption=caption[:1024],
                    progress=progress_callback
                )
            else:
                await client.send_document(
                    chat_id=chat_id,
                    document=filepath,
                    caption=caption[:1024],
                    file_name=filename,
                    force_document=True,
                    progress=progress_callback
                )
            
            return True
            
        except FloodWait as e:
            await asyncio.sleep(e.value)
            return await self.upload_with_progress(client, chat_id, filepath, message, caption)
        except Exception as e:
            logger.error(f"Upload error: {e}")
            return False
    
    def create_progress_text(self, current: int, total: int, percent: float, 
                             speed: float, remaining: float, operation: str) -> str:
        """ایجاد متن نمایش پیشرفت"""
        progress_bar = self.create_progress_bar(percent, 20)
        
        text = (
            f"**{operation} در حال انجام...**\n\n"
            f"📊 **پیشرفت:** {percent:.1f}%\n"
            f"{progress_bar}\n"
            f"💾 **حجم:** {self.format_size(current)} / {self.format_size(total)}\n"
            f"🚀 **سرعت:** {self.format_size(speed)}/ثانیه\n"
        )
        
        if remaining > 0:
            if remaining < 60:
                text += f"⏳ **زمان باقی‌مانده:** {int(remaining)} ثانیه\n"
            elif remaining < 3600:
                text += f"⏳ **زمان باقی‌مانده:** {int(remaining/60)} دقیقه\n"
            else:
                hours = int(remaining/3600)
                minutes = int((remaining % 3600) / 60)
                text += f"⏳ **زمان باقی‌مانده:** {hours} ساعت و {minutes} دقیقه\n"
        
        return text
    
    def create_progress_bar(self, percent: float, length: int = 20) -> str:
        """ایجاد نوار پیشرفت"""
        filled = int(length * percent / 100)
        bar = "█" * filled + "░" * (length - filled)
        return f"`[{bar}]`"
    
    def format_size(self, size: int) -> str:
        """فرمت‌بندی حجم"""
        if size <= 0:
            return "0 B"
        
        units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
        unit_index = 0
        
        while size >= 1024 and unit_index < len(units) - 1:
            size /= 1024.0
            unit_index += 1
        
        return f"{size:.2f} {units[unit_index]}"
    
    def estimate_time(self, bytes_remaining: float, speed: float) -> str:
        """تخمین زمان باقی‌مانده"""
        if speed <= 0:
            return "نامعلوم"
        
        seconds = bytes_remaining / speed
        
        if seconds < 60:
            return f"{int(seconds)} ثانیه"
        elif seconds < 3600:
            minutes = int(seconds / 60)
            secs = int(seconds % 60)
            return f"{minutes} دقیقه و {secs} ثانیه"
        else:
            hours = int(seconds / 3600)
            minutes = int((seconds % 3600) / 60)
            return f"{hours} ساعت و {minutes} دقیقه"
    
    async def cleanup_old_files(self):
        """پاکسازی فایل‌های قدیمی"""
        current_time = time.time()
        max_age = Config.CLEANUP_AFTER_HOURS * 3600
        
        for temp_dir in [Config.TEMP_PATH, Config.DOWNLOAD_PATH, Config.UPLOAD_PATH]:
            if not temp_dir.exists():
                continue
            
            for item in temp_dir.iterdir():
                try:
                    item_age = current_time - item.stat().st_mtime
                    if item_age > max_age:
                        if item.is_file():
                            item.unlink()
                        elif item.is_dir():
                            shutil.rmtree(item)
                        logger.info(f"Cleaned up: {item}")
                except Exception as e:
                    logger.error(f"Error cleaning {item}: {e}")
    
    def get_system_stats(self) -> Dict:
        """دریافت آمار سیستم"""
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage(str(Config.BASE_DIR))
        
        return {
            "cpu": cpu_percent,
            "memory": {
                "percent": memory.percent,
                "used": memory.used,
                "total": memory.total
            },
            "disk": {
                "percent": disk.percent,
                "used": disk.used,
                "total": disk.total
            },
            "active_downloads": len(self.active_downloads),
            "active_uploads": len(self.active_uploads)
        }

# ==================== ایجاد شیء ربات ====================
app = Client(
    name="advanced_downloader_bot",
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    bot_token=Config.BOT_TOKEN,
    workers=200,
    max_concurrent_transmissions=5,
    sleep_threshold=60,
    in_memory=True
)

# ==================== ایجاد مدیر دانلود ====================
dm = AdvancedDownloadManager()

# ==================== منوهای اینلاین ====================
def get_main_keyboard() -> InlineKeyboardMarkup:
    """منوی اصلی"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 راهنما", callback_data="help"),
         InlineKeyboardButton("📊 آمار", callback_data="stats")],
        [InlineKeyboardButton("⚙️ تنظیمات", callback_data="settings"),
         InlineKeyboardButton("🔄 وضعیت", callback_data="status")],
        [InlineKeyboardButton("🧹 پاکسازی", callback_data="cleanup"),
         InlineKeyboardButton("👨‍💻 توسعه‌دهنده", url="https://t.me/example")]
    ])

def get_settings_keyboard() -> InlineKeyboardMarkup:
    """منوی تنظیمات"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔔 نوتیفیکیشن", callback_data="toggle_notify")],
        [InlineKeyboardButton("📤 حالت آپلود", callback_data="upload_mode")],
        [InlineKeyboardButton("📥 حالت دانلود", callback_data="download_mode")],
        [InlineKeyboardButton("↩️ بازگشت", callback_data="back_main")]
    ])

def get_cancel_keyboard(task_id: str = "") -> InlineKeyboardMarkup:
    """دکمه لغو"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ لغو عملیات", callback_data=f"cancel_{task_id}")]
    ])

# ==================== هندلرهای ربات ====================
@app.on_message(filters.command("start"))
async def start_handler(client: Client, message: Message):
    """هندلر دستور start"""
    welcome_text = (
        "🤖 **ربات دانلودر پیشرفته**\n\n"
        "🔹 **ویژگی‌های اصلی:**\n"
        "✅ دانلود فایل‌های تا **۲ گیگابایت**\n"
        "✅ پشتیبانی از همه فرمت‌ها\n"
        "✅ نمایش سرعت و زمان تخمینی\n"
        "✅ قابلیت توقف و ادامه دانلود\n"
        "✅ آپلود خودکار به تلگرام\n\n"
        "📎 **لطفاً لینک فایل را ارسال کنید**\n"
        "🔧 **برای تنظیمات از دکمه‌های زیر استفاده کنید**"
    )
    
    await message.reply_text(
        welcome_text,
        reply_markup=get_main_keyboard(),
        parse_mode=ParseMode.MARKDOWN,
        reply_to_message_id=message.id
    )

@app.on_message(filters.command("help"))
async def help_handler(client: Client, message: Message):
    """هندلر دستور help"""
    help_text = (
        "📚 **راهنمای کامل ربات:**\n\n"
        
        "🎯 **دستورات اصلی:**\n"
        "▫️ `/start` - شروع ربات و نمایش منو\n"
        "▫️ `/help` - نمایش این راهنما\n"
        "▫️ `/download <لینک>` - دانلود مستقیم\n"
        "▫️ `/status` - وضعیت سیستم و ربات\n"
        "▫️ `/stats` - آمار دانلودها\n"
        "▫️ `/cleanup` - پاکسازی فایل‌های موقت\n"
        "▫️ `/cancel` - لغو عملیات جاری\n\n"
        
        "📦 **فرمت‌های پشتیبانی شده:**\n"
        "• ویدیو: MP4, MKV, AVI, MOV, WMV, FLV\n"
        "• صدا: MP3, WAV, FLAC, M4A, AAC, OGG\n"
        "• عکس: JPG, PNG, GIF, WEBP, BMP, TIFF\n"
        "• اسناد: PDF, DOC, XLS, PPT, TXT, EPUB\n"
        "• فشرده: ZIP, RAR, 7Z, TAR, GZ, BZ2\n"
        "• سایر: APK, EXE, ISO, DMG, DEB, RPM\n\n"
        
        "⚙️ **تنظیمات پیشرفته:**\n"
        "✅ **ادامه دانلود:** اگر دانلود قطع شود، از همانجا ادامه می‌دهد\n"
        "✅ **مدیریت حافظه:** استفاده بهینه از RAM و CPU\n"
        "✅ **خطایابی:** ذخیره لاگ کامل تمام عملیات\n"
        "✅ **مقیاس‌پذیری:** قابلیت اجرا روی سرور قوی\n\n"
        
        "⚠️ **محدودیت‌ها و نکات:**\n"
        "• حداکثر حجم فایل: ۲ گیگابایت\n"
        "• زمان دانلود: ۱ ساعت\n"
        "• فایل‌های موقت بعد از ۶ ساعت پاک می‌شوند\n"
        "• لینک باید مستقیم باشد (نه صفحات دانلود)\n"
        "• سرعت بستگی به سرعت سرور مبدا دارد\n\n"
        
        "🔗 **نحوه استفاده:**\n"
        "۱. لینک مستقیم فایل را کپی کنید\n"
        "۲. لینک را برای ربات ارسال کنید\n"
        "۳. اطلاعات فایل را بررسی و تایید کنید\n"
        "۴. منتظر پایان دانلود و آپلود بمانید\n"
        "۵. فایل در تلگرام دریافت می‌کنید\n\n"
        
        "📞 **پشتیبانی:**\n"
        "در صورت مشکل با توسعه‌دهنده تماس بگیرید"
    )
    
    await message.reply_text(
        help_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_to_message_id=message.id,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")]
        ])
    )

@app.on_message(filters.command("status"))
async def status_handler(client: Client, message: Message):
    """هندلر وضعیت سیستم"""
    sys_stats = dm.get_system_stats()
    total_stats = dm.db.get_total_stats()
    
    status_text = (
        f"🖥 **وضعیت سیستم:**\n"
        f"• CPU: {sys_stats['cpu']:.1f}%\n"
        f"• RAM: {sys_stats['memory']['percent']:.1f}% "
        f"({dm.format_size(sys_stats['memory']['used'])} / "
        f"{dm.format_size(sys_stats['memory']['total'])})\n"
        f"• Disk: {sys_stats['disk']['percent']:.1f}% "
        f"({dm.format_size(sys_stats['disk']['used'])} / "
        f"{dm.format_size(sys_stats['disk']['total'])})\n\n"
        
        f"🤖 **وضعیت ربات:**\n"
        f"• دانلود‌های فعال: {sys_stats['active_downloads']}\n"
        f"• آپلود‌های فعال: {sys_stats['active_uploads']}\n"
        f"• حداکثر دانلود همزمان: {Config.MAX_CONCURRENT_DOWNLOADS}\n"
        f"• حداکثر آپلود همزمان: {Config.MAX_CONCURRENT_UPLOADS}\n\n"
        
        f"📊 **آمار کلی:**\n"
        f"• کل دانلود شده: {dm.format_size(total_stats.get('total_downloaded', 0))}\n"
        f"• کل آپلود شده: {dm.format_size(total_stats.get('total_uploaded', 0))}\n"
        f"• تعداد فایل‌ها: {total_stats.get('total_files', 0)}\n\n"
        
        f"🕐 **آخرین بروزرسانی:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    
    await message.reply_text(
        status_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_to_message_id=message.id
    )

@app.on_message(filters.command("stats"))
async def stats_handler(client: Client, message: Message):
    """هندلر آمار کاربر"""
    user_stats = dm.db.get_user_stats(message.from_user.id)
    
    if not user_stats:
        stats_text = "📊 شما هنوز فایلی دانلود نکرده‌اید!"
    else:
        stats_text = (
            f"📊 **آمار کاربر:** {message.from_user.first_name}\n\n"
            f"• کل حجم دانلود شده: {dm.format_size(user_stats.get('total_downloaded', 0))}\n"
            f"• کل حجم آپلود شده: {dm.format_size(user_stats.get('total_uploaded', 0))}\n"
            f"• تعداد فایل‌ها: {user_stats.get('files_count', 0)}\n"
            f"• آخرین فعالیت: {user_stats.get('last_active', 'نامشخص')}\n\n"
            f"👤 **شناسه کاربری:** `{message.from_user.id}`"
        )
    
    await message.reply_text(
        stats_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_to_message_id=message.id
    )

@app.on_message(filters.command("cleanup"))
async def cleanup_handler(client: Client, message: Message):
    """هندلر پاکسازی"""
    if message.from_user.id not in Config.ADMIN_IDS:
        await message.reply_text("❌ این دستور فقط برای مدیران است!")
        return
    
    await dm.cleanup_old_files()
    
    # شمارش فایل‌های باقی‌مانده
    temp_count = len(list(Config.TEMP_PATH.iterdir()))
    dl_count = len(list(Config.DOWNLOAD_PATH.iterdir()))
    up_count = len(list(Config.UPLOAD_PATH.iterdir()))
    
    await message.reply_text(
        f"✅ پاکسازی انجام شد!\n\n"
        f"• فایل‌های temp: {temp_count}\n"
        f"• فایل‌های downloads: {dl_count}\n"
        f"• فایل‌های uploads: {up_count}"
    )

@app.on_message(filters.command("download"))
async def direct_download_handler(client: Client, message: Message):
    """هندلر دانلود مستقیم"""
    if len(message.command) < 2:
        await message.reply_text(
            "❌ لطفاً لینک را بعد از دستور وارد کنید:\n"
            "مثال: `/download https://example.com/file.zip`",
            parse_mode=ParseMode.MARKDOWN,
            reply_to_message_id=message.id
        )
        return
    
    url = ' '.join(message.command[1:])
    await process_url(client, message, url)

@app.on_message(filters.text & ~filters.command)
async def url_handler(client: Client, message: Message):
    """هندلر دریافت لینک"""
    url = message.text.strip()
    
    # بررسی اینکه آیا لینک است
    if not (url.startswith('http://') or url.startswith('https://')):
        return
    
    await process_url(client, message, url)

async def process_url(client: Client, message: Message, url: str):
    """پردازش URL و شروع دانلود"""
    # اعتبارسنجی URL
    validating_msg = await message.reply_text(
        "🔍 در حال بررسی لینک...",
        reply_to_message_id=message.id
    )
    
    is_valid, valid_msg, headers = await dm.validate_url(url)
    
    if not is_valid:
        await validating_msg.edit_text(
            f"❌ **خطا در اعتبارسنجی:**\n{valid_msg}\n\n"
            f"🔗 **لینک:** `{url[:100]}{'...' if len(url) > 100 else ''}`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # دریافت اطلاعات فایل
    await validating_msg.edit_text(
        "📡 در حال دریافت اطلاعات فایل...",
        reply_to_message_id=message.id
    )
    
    success, file_info = await dm.get_detailed_file_info(url)
    
    if not success:
        await validating_msg.edit_text(
            f"❌ **خطا در دریافت اطلاعات:**\n{file_info.get('error', 'خطای نامشخص')}\n\n"
            f"🔗 **لینک:** `{url[:100]}{'...' if len(url) > 100 else ''}`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # نمایش اطلاعات و تایید
    confirm_text = (
        f"📄 **اطلاعات فایل:**\n\n"
        f"📁 **نام:** `{file_info['filename']}`\n"
        f"💾 **حجم:** {dm.format_size(file_info['size'])}\n"
        f"📦 **نوع:** {file_info['content_type']}\n"
        f"🌐 **سرور:** {file_info['server']}\n"
        f"🔗 **ادامه‌دار:** {'✅ بله' if file_info['accept_ranges'] else '❌ خیر'}\n\n"
        
        f"⏳ **زمان تخمینی دانلود:**\n"
        f"• با سرعت 1MB/s: {dm.estimate_time(file_info['size'], 1024*1024)}\n"
        f"• با سرعت 5MB/s: {dm.estimate_time(file_info['size'], 5*1024*1024)}\n\n"
        
        f"آیا مایل به دانلود این فایل هستید؟"
    )
    
    # تولید شناسه یکتا برای این عملیات
    task_id = dm.generate_file_id(url)
    
    confirm_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ بله، دانلود کن", callback_data=f"confirm_dl_{task_id}"),
         InlineKeyboardButton("❌ خیر، لغو", callback_data=f"cancel_dl_{task_id}")],
        [InlineKeyboardButton("⚡ دانلود سریع", callback_data=f"fast_dl_{task_id}")]
    ])
    
    await validating_msg.edit_text(
        confirm_text,
        reply_markup=confirm_keyboard,
        parse_mode=ParseMode.MARKDOWN
    )
    
    # ذخیره اطلاعات برای callback
    dm.active_downloads[task_id] = {
        "url": url,
        "file_info": file_info,
        "message": message,
        "status_msg": validating_msg,
        "user_id": message.from_user.id,
        "status": "pending",
        "created_at": time.time()
    }

@app.on_callback_query()
async def callback_handler(client: Client, callback_query: CallbackQuery):
    """هندلر callback"""
    data = callback_query.data
    
    if data == "help":
        await help_handler(client, callback_query.message)
        await callback_query.answer()
    
    elif data == "stats":
        await stats_handler(client, callback_query.message)
        await callback_query.answer()
    
    elif data == "status":
        await status_handler(client, callback_query.message)
        await callback_query.answer()
    
    elif data == "cleanup":
        await cleanup_handler(client, callback_query.message)
        await callback_query.answer("✅ پاکسازی انجام شد")
    
    elif data == "settings":
        await callback_query.message.edit_text(
            "⚙️ **تنظیمات ربات:**\n\n"
            "در حال حاضر این بخش در دست توسعه است...",
            reply_markup=get_settings_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        await callback_query.answer()
    
    elif data == "back_main":
        await start_handler(client, callback_query.message)
        await callback_query.answer()
    
    elif data.startswith("confirm_dl_"):
        task_id = data[11:]
        await start_download_process(client, callback_query, task_id)
    
    elif data.startswith("cancel_dl_"):
        task_id = data[10:]
        if task_id in dm.active_downloads:
            del dm.active_downloads[task_id]
        await callback_query.message.edit_text("❌ دانلود لغو شد.")
        await callback_query.answer("لغو شد")
    
    elif data.startswith("cancel_"):
        task_id = data[7:]
        await cancel_task(callback_query, task_id)

async def start_download_process(client: Client, callback_query: CallbackQuery, task_id: str):
    """شروع فرآیند دانلود"""
    if task_id not in dm.active_downloads:
        await callback_query.answer("❌ درخواست منقضی شده است", show_alert=True)
        return
    
    task_info = dm.active_downloads[task_id]
    url = task_info["url"]
    file_info = task_info["file_info"]
    user_id = task_info["user_id"]
    original_message = task_info["message"]
    status_msg = task_info["status_msg"]
    
    # آپدیت وضعیت
    task_info["status"] = "downloading"
    
    # ایجاد نام فایل
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_filename = ''.join(c for c in file_info['filename'] if c.isalnum() or c in '._- ')
    filename = f"{timestamp}_{safe_filename}"[:200]  # محدودیت طول نام فایل
    filepath = Config.DOWNLOAD_PATH / filename
    
    # شروع دانلود
    await status_msg.edit_text(
        f"🚀 **شروع دانلود...**\n\n"
        f"📁 **فایل:** `{file_info['filename']}`\n"
        f"💾 **حجم:** {dm.format_size(file_info['size'])}\n"
        f"👤 **کاربر:** {original_message.from_user.first_name}\n\n"
        f"⏳ **لطفاً منتظر بمانید...**",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_cancel_keyboard(task_id)
    )
    
    try:
        # دانلود فایل
        download_success, downloaded_bytes = await dm.download_with_progress(
            url, str(filepath), status_msg, file_info['size']
        )
        
        if not download_success:
            await status_msg.edit_text(
                f"❌ **خطا در دانلود!**\n\n"
                f"📁 فایل: `{file_info['filename']}`\n"
                f"💾 دانلود شده: {dm.format_size(downloaded_bytes)} / {dm.format_size(file_info['size'])}\n\n"
                f"⚠️ ممکن است سرور مبدا مشکل داشته باشد یا اتصال قطع شده باشد."
            )
            return
        
        # آپلود به تلگرام
        await status_msg.edit_text(
            f"✅ **دانلود تکمیل شد!**\n\n"
            f"📁 فایل: `{file_info['filename']}`\n"
            f"💾 حجم: {dm.format_size(downloaded_bytes)}\n\n"
            f"📤 **در حال آپلود به تلگرام...**"
        )
        
        # آماده کردن کپشن
        caption = (
            f"📁 **{file_info['filename']}**\n"
            f"💾 **حجم:** {dm.format_size(downloaded_bytes)}\n"
            f"👤 **کاربر:** {original_message.from_user.first_name}\n"
            f"🕐 **زمان:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            f"🤖 **ارسال شده توسط:** @{client.me.username}"
        )
        
        # آپلود فایل
        upload_success = await dm.upload_with_progress(
            client, original_message.chat.id, str(filepath), status_msg, caption
        )
        
        if upload_success:
            # بروزرسانی آمار
            dm.db.update_user_stats(user_id, downloaded_bytes, downloaded_bytes)
            
            await status_msg.edit_text(
                f"✅ **عملیات با موفقیت انجام شد!**\n\n"
                f"📁 فایل: `{file_info['filename']}`\n"
                f"💾 حجم: {dm.format_size(downloaded_bytes)}\n"
                f"👤 کاربر: {original_message.from_user.first_name}\n"
                f"🕐 زمان کل: {int(time.time() - task_info['created_at'])} ثانیه\n\n"
                f"🎉 **فایل با موفقیت ارسال شد!**"
            )
        else:
            await status_msg.edit_text(
                f"❌ **خطا در آپلود!**\n\n"
                f"فایل دانلود شده اما ارسال نشد.\n"
                f"لطفاً دوباره تلاش کنید یا با پشتیبانی تماس بگیرید."
            )
        
    except Exception as e:
        logger.error(f"Download process error: {e}", exc_info=True)
        await status_msg.edit_text(
            f"❌ **خطای غیرمنتظره!**\n\n"
            f"خطا: `{str(e)[:200]}`\n\n"
            f"لطفاً دوباره تلاش کنید یا با پشتیبانی تماس بگیرید."
        )
    
    finally:
        # پاکسازی فایل موقت
        try:
            if filepath.exists():
                filepath.unlink()
        except Exception as e:
            logger.error(f"Error deleting temp file: {e}")
        
        # حذف از لیست فعال
        if task_id in dm.active_downloads:
            del dm.active_downloads[task_id]

async def cancel_task(callback_query: CallbackQuery, task_id: str):
    """لغو یک task"""
    if task_id in dm.active_downloads:
        del dm.active_downloads[task_id]
        await callback_query.message.edit_text("✅ عملیات لغو شد.")
    else:
        await callback_query.answer("عملیاتی برای لغو یافت نشد")
    await callback_query.answer()

# ==================== تابع اصلی ====================
async def main():
    """تابع اصلی اجرای ربات"""
    logger.info("=" * 50)
    logger.info("🤖 شروع ربات دانلودر پیشرفته")
    logger.info("=" * 50)
    
    try:
        # پاکسازی اولیه
        await dm.cleanup_old_files()
        
        # راه‌اندازی ربات
        await app.start()
        
        # اطلاعات ربات
        me = await app.get_me()
        logger.info(f"✅ ربات با موفقیت راه‌اندازی شد!")
        logger.info(f"👤 نام: {me.first_name}")
        logger.info(f"🆔 ID: {me.id}")
        logger.info(f"🔗 یوزرنیم: @{me.username}")
        logger.info(f"💾 حداکثر حجم فایل: {dm.format_size(Config.MAX_FILE_SIZE)}")
        logger.info(f"📁 مسیر دانلود: {Config.DOWNLOAD_PATH}")
        
        # ارسال پیام شروع به ادمین‌ها
        start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for admin_id in Config.ADMIN_IDS:
            try:
                await app.send_message(
                    admin_id,
                    f"🤖 **ربات راه‌اندازی شد!**\n\n"
                    f"🕐 زمان: {start_time}\n"
                    f"👤 نام: {me.first_name}\n"
                    f"🔗 @{me.username}\n\n"
                    f"✅ آماده دریافت درخواست‌ها..."
                )
            except Exception as e:
                logger.error(f"Error sending startup message to admin {admin_id}: {e}")
        
        # اجرای وظیفه پاکسازی دوره‌ای
        async def periodic_tasks():
            while True:
                try:
                    await asyncio.sleep(3600)  # هر 1 ساعت
                    await dm.cleanup_old_files()
                    
                    # لاگ وضعیت سیستم هر 6 ساعت
                    if int(time.time()) % (6 * 3600) < 60:
                        sys_stats = dm.get_system_stats()
                        logger.info(
                            f"📊 گزارش سیستم - "
                            f"CPU: {sys_stats['cpu']:.1f}%, "
                            f"RAM: {sys_stats['memory']['percent']:.1f}%, "
                            f"Active DL: {sys_stats['active_downloads']}"
                        )
                        
                except Exception as e:
                    logger.error(f"Error in periodic tasks: {e}")
        
        # شروع وظایف دوره‌ای
        asyncio.create_task(periodic_tasks())
        
        # نگه داشتن ربات فعال
        logger.info("🔄 ربات در حال اجراست...")
        await idle()
        
    except KeyboardInterrupt:
        logger.info("⚠️ دریافت سیگنال توقف...")
    except Exception as e:
        logger.error(f"❌ خطای اصلی: {e}", exc_info=True)
    finally:
        logger.info("🛑 در حال خاموش کردن ربات...")
        
        # پاکسازی نهایی
        try:
            await dm.close_session()
            dm.executor.shutdown(wait=False)
            
            if app.is_connected:
                await app.stop()
            
            # ارسال پیام خاموشی به ادمین‌ها
            end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for admin_id in Config.ADMIN_IDS:
                try:
                    await app.send_message(
                        admin_id,
                        f"🛑 **ربات خاموش شد!**\n\n"
                        f"🕐 زمان: {end_time}\n"
                        f"👤 نام: {me.first_name if 'me' in locals() else 'Unknown'}\n"
                        f"🔗 @{me.username if 'me' in locals() else 'Unknown'}\n\n"
                        f"⚠️ دلیل: توقف دستی"
                    )
                except:
                    pass
                    
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
        
        logger.info("👋 ربات با موفقیت خاموش شد!")
        logger.info("=" * 50)

# ==================== اجرای ربات ====================
if __name__ == "__main__":
    # چک کردن تنظیمات
    if Config.API_ID == 21822238 or Config.API_HASH == "ebcf1d2bded42ee86d4a2e6a55d28b39" or Config.BOT_TOKEN == "8353195434:AAF5_F3DdFb7yfOY8HoQmH6pQ1eIdnn63c0":
        logger.error("❌ لطفاً تنظیمات API را در فایل کانفیگ وارد کنید!")
        print("\n" + "="*50)
        print("⚠️  توجه: لطفاً مقادیر زیر را در فایل کانفیگ تنظیم کنید:")
        print("="*50)
        print(f"API_ID = {Config.API_ID}  # از my.telegram.org دریافت کنید")
        print(f"API_HASH = '{Config.API_HASH}'  # از my.telegram.org دریافت کنید")
        print(f"BOT_TOKEN = '{Config.BOT_TOKEN}'  # از @BotFather دریافت کنید")
        print("="*50)
        exit(1)
    
    # اجرای ربات
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 خداحافظ!")