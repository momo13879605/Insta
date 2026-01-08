import os
import sqlite3
import asyncio
import aiohttp
import aiofiles
import re
from datetime import datetime, timedelta
from typing import Dict, List, Set, Optional, Tuple
import json
import random
from fake_useragent import UserAgent
import hashlib
import traceback
import time
import logging
from logging.handlers import RotatingFileHandler
import aiofiles.os as async_os
from urllib.parse import urlparse, parse_qs

# ============================
# تنظیمات لاگ‌گیری
# ============================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler('bot.log', maxBytes=5*1024*1024, backupCount=5),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ============================
# تنظیمات اولیه
# ============================
TOKEN = '7880725906:AAHTNy_U8_MkX2tf3TVZl2z18kqUMf8AtAQ'
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB
ADMINS = [5914346958]
REQUEST_TIMEOUT = 30
PROXY_SOURCES_TIMEOUT = 15
MAX_VIEWS_PER_PROXY = 5  # حداکثر تعداد ویو برای هر پروکسی

# URLهای API تلگرام
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TOKEN}"

# لیست منابع پروکسی (کاهش تعداد و حذف منابع مشکل‌دار)
PROXY_SOURCES = [
    "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies_anonymous/http.txt",
    "https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/http/data.txt",
    "https://github.com/zloi-user/hideip.me/raw/refs/heads/master/http.txt",
    "https://raw.githubusercontent.com/saisuiu/Lionkings-Http-Proxys-Proxies/main/free.txt",
    "https://cdn.jsdelivr.net/gh/databay-labs/free-proxy-list/http.txt",
    "https://raw.githubusercontent.com/iplocate/free-proxy-list/main/protocols/http.txt",
    "https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&protocol=http&proxy_format=ipport&format=text&timeout=20000",
    "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-http.txt",
    "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
    "https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt",
    "https://www.proxy-list.download/api/v1/get?type=http",
    "https://www.proxy-list.download/api/v1/get?type=https",
    "https://www.proxy-list.download/api/v1/get?type=socks4",
    "https://www.proxy-list.download/api/v1/get?type=socks5",
    "https://raw.githubusercontent.com/roosterkid/openproxylist/main/HTTPS_RAW.txt",
    "https://raw.githubusercontent.com/roosterkid/openproxylist/main/SOCKS4_RAW.txt",
    "https://raw.githubusercontent.com/roosterkid/openproxylist/main/SOCKS5_RAW.txt",
    "https://api.openproxylist.xyz/http.txt",
    "https://api.openproxylist.xyz/socks4.txt",
    "https://api.openproxylist.xyz/socks5.txt",
    "https://proxyspace.pro/http.txt",
    "https://proxyspace.pro/https.txt",
    "https://proxyspace.pro/socks4.txt",
    "https://proxyspace.pro/socks5.txt",
    "http://worm.rip/http.txt",
    "http://worm.rip/socks4.txt",
    "http://worm.rip/socks5.txt"
]

# ============================
# مدیریت دیتابیس با قفل‌گذاری
# ============================
db_lock = asyncio.Lock()

def init_db():
    """ایجاد یا اتصال به دیتابیس SQLite با جداول کامل"""
    conn = sqlite3.connect('bot_stats.db', check_same_thread=False)
    cursor = conn.cursor()
    
    # جدول آمار کلی
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS stats (
            id INTEGER PRIMARY KEY,
            total_users INTEGER DEFAULT 0,
            total_proxies_processed INTEGER DEFAULT 0,
            total_proxies_deleted INTEGER DEFAULT 0,
            total_views_sent INTEGER DEFAULT 0,
            total_orders INTEGER DEFAULT 0,
            last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # جدول کاربران
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            total_proxies_uploaded INTEGER DEFAULT 0,
            total_views_sent INTEGER DEFAULT 0,
            last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # جدول پروکسی‌ها
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS proxies (
            proxy_id INTEGER PRIMARY KEY AUTOINCREMENT,
            proxy_address TEXT UNIQUE,
            proxy_type TEXT,
            added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_used TIMESTAMP,
            use_count INTEGER DEFAULT 0,
            success_count INTEGER DEFAULT 0
        )
    ''')
    
    # جدول سفارشات ویو
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS view_orders (
            order_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            channel_username TEXT,
            post_id TEXT,
            target_views INTEGER,
            completed_views INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            end_time TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    
    # جدول لاگ ویو‌ها
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS view_logs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER,
            proxy_id INTEGER,
            success BOOLEAN,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (order_id) REFERENCES view_orders (order_id),
            FOREIGN KEY (proxy_id) REFERENCES proxies (proxy_id)
        )
    ''')
    
    # ایجاد رکورد اولیه در stats
    cursor.execute('INSERT OR IGNORE INTO stats (id) VALUES (1)')
    
    conn.commit()
    conn.close()
    logger.info("پایگاه داده با موفقیت راه‌اندازی شد")

async def add_user(user_id, username="", first_name="", last_name=""):
    """افزودن کاربر جدید به دیتابیس"""
    async with db_lock:
        conn = sqlite3.connect('bot_stats.db', check_same_thread=False)
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT OR IGNORE INTO users 
                (user_id, username, first_name, last_name) 
                VALUES (?, ?, ?, ?)
            ''', (user_id, username, first_name, last_name))
            cursor.execute('UPDATE stats SET total_users = (SELECT COUNT(*) FROM users) WHERE id = 1')
            cursor.execute('UPDATE users SET last_active = CURRENT_TIMESTAMP WHERE user_id = ?', (user_id,))
            conn.commit()
            logger.info(f"کاربر جدید اضافه شد: {user_id}")
        finally:
            conn.close()

async def increment_stats(field, value=1):
    """افزایش آمار کلی با امنیت در برابر SQL Injection"""
    allowed_fields = {
        'total_users',
        'total_proxies_processed', 
        'total_proxies_deleted',
        'total_views_sent',
        'total_orders'
    }
    
    if field not in allowed_fields:
        raise ValueError(f"فیلد غیرمجاز: {field}")
    
    async with db_lock:
        conn = sqlite3.connect('bot_stats.db', check_same_thread=False)
        cursor = conn.cursor()
        try:
            cursor.execute(f'UPDATE stats SET {field} = {field} + ? WHERE id = 1', (value,))
            cursor.execute('UPDATE stats SET last_activity = CURRENT_TIMESTAMP WHERE id = 1')
            conn.commit()
        finally:
            conn.close()

async def save_proxies_to_db(proxies):
    """ذخیره پروکسی‌ها در دیتابیس و شمارش تکراری‌ها"""
    if not proxies:
        return 0, 0
    
    async with db_lock:
        conn = sqlite3.connect('bot_stats.db', check_same_thread=False, timeout=30)
        cursor = conn.cursor()
        
        new_count = 0
        duplicate_count = 0
        
        try:
            for proxy_info in proxies:
                proxy_address = proxy_info['proxy_address']
                proxy_type = proxy_info['proxy_type']
                
                # بررسی وجود پروکسی در دیتابیس
                cursor.execute('SELECT proxy_id FROM proxies WHERE proxy_address = ?', (proxy_address,))
                existing = cursor.fetchone()
                
                if existing:
                    duplicate_count += 1
                else:
                    try:
                        cursor.execute('''
                            INSERT OR IGNORE INTO proxies (proxy_address, proxy_type)
                            VALUES (?, ?)
                        ''', (proxy_address, proxy_type))
                        new_count += 1
                    except sqlite3.IntegrityError:
                        duplicate_count += 1
                    except Exception as e:
                        logger.error(f"خطا در ذخیره پروکسی {proxy_address}: {e}")
            
            if new_count > 0:
                await increment_stats('total_proxies_processed', new_count)
            
            if duplicate_count > 0:
                await increment_stats('total_proxies_deleted', duplicate_count)
            
            conn.commit()
            
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e):
                logger.warning("⚠️ دیتابیس قفل شد، تلاش مجدد...")
                await asyncio.sleep(1)
                return await save_proxies_to_db(proxies)
            else:
                logger.error(f"خطای دیتابیس: {e}")
                raise
        finally:
            conn.close()
        
        logger.info(f"ذخیره پروکسی‌ها: {new_count} جدید، {duplicate_count} تکراری")
        return new_count, duplicate_count

async def get_stats():
    """دریافت آمار کامل"""
    async with db_lock:
        conn = sqlite3.connect('bot_stats.db', check_same_thread=False)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                SELECT 
                    total_users,
                    total_proxies_processed,
                    total_proxies_deleted,
                    total_views_sent,
                    total_orders,
                    last_activity
                FROM stats WHERE id = 1
            ''')
            stats = cursor.fetchone()
            
            cursor.execute('SELECT COUNT(*) FROM proxies')
            total_proxies = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(DISTINCT proxy_type) FROM proxies')
            unique_types = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM view_orders WHERE DATE(start_time) = DATE("now")')
            today_orders = cursor.fetchone()[0]
            
            cursor.execute('''
                SELECT COUNT(*) FROM view_orders 
                WHERE status = 'completed' 
                AND DATE(start_time) = DATE("now")
            ''')
            today_completed = cursor.fetchone()[0]
            
            return stats, total_proxies, unique_types, today_orders, today_completed
        finally:
            conn.close()

async def create_view_order(user_id, channel_username, post_id, target_views):
    """ایجاد سفارش جدید برای افزایش ویو"""
    async with db_lock:
        conn = sqlite3.connect('bot_stats.db', check_same_thread=False)
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO view_orders (user_id, channel_username, post_id, target_views)
                VALUES (?, ?, ?, ?)
            ''', (user_id, channel_username, post_id, target_views))
            order_id = cursor.lastrowid
            await increment_stats('total_orders')
            
            # آپدیت آمار کاربر
            cursor.execute('''
                UPDATE users SET 
                total_views_sent = total_views_sent + 0,
                last_active = CURRENT_TIMESTAMP
                WHERE user_id = ?
            ''', (user_id,))
            
            conn.commit()
            logger.info(f"سفارش جدید ایجاد شد: order_id={order_id}, user_id={user_id}, target={target_views}")
            return order_id
        finally:
            conn.close()

async def update_view_order(order_id, completed_views, status='processing'):
    """به‌روزرسانی سفارش ویو"""
    async with db_lock:
        conn = sqlite3.connect('bot_stats.db', check_same_thread=False)
        cursor = conn.cursor()
        try:
            if status == 'completed':
                cursor.execute('''
                    UPDATE view_orders 
                    SET completed_views = ?, status = ?, end_time = CURRENT_TIMESTAMP
                    WHERE order_id = ?
                ''', (completed_views, status, order_id))
                
                # آپدیت آمار کلی
                cursor.execute('SELECT user_id, target_views FROM view_orders WHERE order_id = ?', (order_id,))
                result = cursor.fetchone()
                if result:
                    user_id, target_views = result
                    await increment_stats('total_views_sent', completed_views)
                    
                    # آپدیت آمار کاربر
                    cursor.execute('''
                        UPDATE users SET 
                        total_views_sent = total_views_sent + ?
                        WHERE user_id = ?
                    ''', (completed_views, user_id))
            else:
                cursor.execute('''
                    UPDATE view_orders 
                    SET completed_views = ?, status = ?
                    WHERE order_id = ?
                ''', (completed_views, status, order_id))
            
            conn.commit()
        finally:
            conn.close()

async def get_proxies_for_view(limit=100):
    """دریافت پروکسی‌ها برای ارسال ویو"""
    async with db_lock:
        conn = sqlite3.connect('bot_stats.db', check_same_thread=False)
        cursor = conn.cursor()
        try:
            # انتخاب پروکسی‌هایی که کمترین استفاده را داشته‌اند
            cursor.execute('''
                SELECT proxy_id, proxy_address, proxy_type 
                FROM proxies 
                ORDER BY use_count ASC, last_used ASC
                LIMIT ?
            ''', (limit,))
            
            proxies = []
            for row in cursor.fetchall():
                proxies.append({
                    'proxy_id': row[0],
                    'proxy_address': row[1],
                    'proxy_type': row[2]
                })
            
            return proxies
        finally:
            conn.close()

async def update_proxy_usage(proxy_id, success):
    """به‌روزرسانی آمار استفاده از پروکسی"""
    async with db_lock:
        conn = sqlite3.connect('bot_stats.db', check_same_thread=False)
        cursor = conn.cursor()
        try:
            if success:
                cursor.execute('''
                    UPDATE proxies 
                    SET use_count = use_count + 1, 
                        success_count = success_count + 1,
                        last_used = CURRENT_TIMESTAMP
                    WHERE proxy_id = ?
                ''', (proxy_id,))
            else:
                cursor.execute('''
                    UPDATE proxies 
                    SET use_count = use_count + 1,
                        last_used = CURRENT_TIMESTAMP
                    WHERE proxy_id = ?
                ''', (proxy_id,))
            
            conn.commit()
        finally:
            conn.close()

async def log_view_attempt(order_id, proxy_id, success):
    """لاگ کردن تلاش برای ارسال ویو"""
    async with db_lock:
        conn = sqlite3.connect('bot_stats.db', check_same_thread=False)
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO view_logs (order_id, proxy_id, success)
                VALUES (?, ?, ?)
            ''', (order_id, proxy_id, success))
            conn.commit()
        finally:
            conn.close()

# ============================
# کلاس دریافت پروکسی
# ============================
class ProxyFetcher:
    def __init__(self):
        self.ua = UserAgent()
        self.session = None
    
    async def initialize_session(self):
        """ایجاد session ناهمزمان"""
        if not self.session:
            self.session = aiohttp.ClientSession(
                headers={'User-Agent': self.ua.random},
                timeout=aiohttp.ClientTimeout(total=PROXY_SOURCES_TIMEOUT)
            )
    
    async def close_session(self):
        """بستن session"""
        if self.session:
            await self.session.close()
            self.session = None
    
    def normalize_proxy(self, proxy_line):
        """نرمال‌سازی پروکسی"""
        proxy_line = proxy_line.strip()
        if not proxy_line:
            return None, None
        
        # حذف کامنت‌ها
        if '#' in proxy_line:
            proxy_line = proxy_line.split('#')[0].strip()
        
        # تشخیص نوع پروکسی
        proxy_lower = proxy_line.lower()
        
        if proxy_lower.startswith('socks5://'):
            proxy_type = 'socks5'
        elif proxy_lower.startswith('socks4://'):
            proxy_type = 'socks4'
        elif proxy_lower.startswith('https://'):
            proxy_type = 'https'
        elif proxy_lower.startswith('http://'):
            proxy_type = 'http'
        elif '://' not in proxy_line:
            # پروتکل مشخص نشده
            if proxy_line.count(':') == 3:
                # فرمت host:port:user:pass
                parts = proxy_line.split(':')
                if len(parts) == 4:
                    host, port, user, pwd = parts
                    proxy_line = f"http://{user}:{pwd}@{host}:{port}"
                    proxy_type = 'http'
            elif ':' in proxy_line:
                # فرمت host:port
                proxy_line = f"http://{proxy_line}"
                proxy_type = 'http'
            else:
                return None, None
        else:
            proxy_type = 'http'
        
        return proxy_line, proxy_type
    
    async def fetch_from_source(self, source_url):
        """دریافت پروکسی‌ها از یک منبع با مدیریت خطاهای دیکد"""
        try:
            await self.initialize_session()
            
            async with self.session.get(source_url, ssl=False) as response:
                if response.status == 200:
                    # خواندن به صورت بایت و دیکد با مدیریت خطا
                    data = await response.read()
                    
                    # تلاش برای دیکد با encoding‌های مختلف
                    encodings = ['utf-8', 'latin-1', 'iso-8859-1', 'cp1252', 'ascii']
                    text = None
                    
                    for encoding in encodings:
                        try:
                            text = data.decode(encoding)
                            break
                        except UnicodeDecodeError:
                            continue
                    
                    if text is None:
                        # اگر هیچ encoding‌ای کار نکرد، با ignore errors دیکد کن
                        text = data.decode('utf-8', errors='ignore')
                    
                    # استخراج پروکسی‌ها
                    proxies = []
                    lines = text.split('\n')
                    
                    for line in lines:
                        line = line.strip()
                        if not line:
                            continue
                        
                        normalized, proxy_type = self.normalize_proxy(line)
                        if normalized and proxy_type:
                            proxies.append({
                                'proxy_address': normalized,
                                'proxy_type': proxy_type
                            })
                    
                    logger.info(f"از {source_url} دریافت شد: {len(proxies)} پروکسی")
                    return proxies, len(proxies)
                else:
                    logger.warning(f"خطا در دریافت از {source_url}: کد وضعیت {response.status}")
                    
        except aiohttp.ClientError as e:
            logger.error(f"خطای شبکه در دریافت از {source_url}: {str(e)[:100]}")
        except Exception as e:
            logger.error(f"خطای غیرمنتظره در دریافت از {source_url}: {str(e)[:100]}")
        
        return [], 0
    
    async def fetch_all_sources(self, update_progress_callback=None):
        """دریافت پروکسی‌ها از تمام منابع"""
        total_sources = len(PROXY_SOURCES)
        all_proxies = []
        
        if update_progress_callback:
            await update_progress_callback(
                stage="دریافت از منابع",
                progress=0,
                current=0,
                total=total_sources,
                found=0
            )
        
        # دریافت منابع به صورت سریالی برای جلوگیری از overload
        for i, source in enumerate(PROXY_SOURCES):
            try:
                proxies, count = await self.fetch_from_source(source)
                if proxies:
                    all_proxies.extend(proxies)
                
                progress = int(((i + 1) / total_sources) * 100)
                
                if update_progress_callback:
                    await update_progress_callback(
                        stage="دریافت از منابع",
                        progress=progress,
                        current=i + 1,
                        total=total_sources,
                        found=len(all_proxies)
                    )
                
                # وقفه برای جلوگیری از rate limit و overload
                await asyncio.sleep(2)
                
            except Exception as e:
                logger.error(f"خطا در پردازش منبع {source}: {e}")
                continue
        
        # حذف تکراری‌ها با استفاده از دیکشنری
        unique_proxies = {}
        for proxy in all_proxies:
            proxy_address = proxy['proxy_address']
            if proxy_address not in unique_proxies:
                unique_proxies[proxy_address] = proxy
        
        logger.info(f"جمع‌آوری شد: {len(unique_proxies)} پروکسی منحصربه‌فرد")
        return list(unique_proxies.values())
    
    async def fetch_proxies(self, max_proxies=500, update_progress_callback=None):
        """دریافت پروکسی‌ها از منابع آنلاین"""
        try:
            all_proxies = await self.fetch_all_sources(update_progress_callback)
            
            if not all_proxies:
                if update_progress_callback:
                    await update_progress_callback(
                        stage="خطا",
                        progress=0,
                        error="هیچ پروکسی یافت نشد!"
                    )
                return []
            
            # محدود کردن تعداد پروکسی‌ها
            if len(all_proxies) > max_proxies:
                all_proxies = all_proxies[:max_proxies]
            
            # ذخیره در دیتابیس
            new_count, duplicate_count = await save_proxies_to_db(all_proxies)
            
            if update_progress_callback:
                await update_progress_callback(
                    stage="تکمیل",
                    progress=100,
                    current=len(all_proxies),
                    total=len(all_proxies),
                    found=len(all_proxies),
                    new=new_count,
                    duplicates=duplicate_count
                )
            
            return all_proxies
            
        except Exception as e:
            if update_progress_callback:
                await update_progress_callback(
                    stage="خطا",
                    progress=0,
                    error=str(e)[:200]
                )
            logger.error(f"خطا در دریافت پروکسی‌ها: {e}")
            logger.error(traceback.format_exc())
            return []
        finally:
            await self.close_session()
    
    async def save_proxies_to_files(self, proxies):
        """ذخیره پروکسی‌ها در فایل‌های جداگانه"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        saved_files = []
        
        # ایجاد دایرکتوری برای ذخیره فایل‌ها
        await async_os.makedirs("proxy_files", exist_ok=True)
        
        # دسته‌بندی پروکسی‌ها بر اساس نوع
        categorized = {
            'http': [],
            'https': [],
            'socks4': [],
            'socks5': []
        }
        
        for proxy in proxies:
            proxy_type = proxy['proxy_type']
            if proxy_type in categorized:
                categorized[proxy_type].append(proxy['proxy_address'])
        
        # ذخیره هر دسته در فایل جداگانه
        for proxy_type, proxy_list in categorized.items():
            if proxy_list:
                filename = f"proxy_files/proxies_{proxy_type}_{timestamp}.txt"
                async with aiofiles.open(filename, 'w', encoding='utf-8') as f:
                    await f.write('\n'.join(proxy_list))
                saved_files.append(filename)
                logger.info(f"{len(proxy_list)} پروکسی {proxy_type} در {filename} ذخیره شد")
        
        # ذخیره همه پروکسی‌ها در یک فایل
        if proxies:
            filename = f"proxy_files/all_proxies_{timestamp}.txt"
            async with aiofiles.open(filename, 'w', encoding='utf-8') as f:
                for proxy in proxies:
                    await f.write(f"{proxy['proxy_address']}\n")
            saved_files.append(filename)
            logger.info(f"{len(proxies)} پروکسی در {filename} ذخیره شد")
        
        return saved_files

# ============================
# کلاس ارسال ویو تلگرام (کامل شده)
# ============================
class TelegramViewSender:
    def __init__(self):
        self.ua = UserAgent()
        self.session_cache = {}
    
    async def get_session(self, proxy_url=None):
        """ایجاد یا بازیابی session با proxy"""
        if proxy_url not in self.session_cache:
            connector = None
            if proxy_url:
                connector = aiohttp.TCPConnector(ssl=False)
            
            self.session_cache[proxy_url] = aiohttp.ClientSession(
                connector=connector,
                headers={'User-Agent': self.ua.random},
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
            )
        
        return self.session_cache[proxy_url]
    
    async def close_all_sessions(self):
        """بستن تمام session‌ها"""
        for session in self.session_cache.values():
            await session.close()
        self.session_cache.clear()
    
    async def fetch_post_data(self, channel_username, post_id, proxy_url=None):
        """دریافت اطلاعات پست تلگرام - کامل شده"""
        try:
            session = await self.get_session(proxy_url)
            
            # ساخت URL پست
            url = f'https://t.me/{channel_username}/{post_id}'
            
            # درخواست اولیه برای دریافت کوکی‌ها
            async with session.get(url, allow_redirects=True) as response:
                if response.status != 200:
                    logger.warning(f"خطا در دسترسی به پست: {response.status}")
                    return None
                
                html_content = await response.text()
                
                # جستجو برای داده‌های مورد نیاز
                # تلگرام معمولاً داده‌ها را در تگ meta ذخیره می‌کند
                patterns = [
                    r'data-view="([^"]+)"',
                    r'views="([^"]+)"',
                    r'post_id="([^"]+)"',
                    r'channel_id="([^"]+)"'
                ]
                
                extracted_data = {}
                for pattern in patterns:
                    match = re.search(pattern, html_content)
                    if match:
                        key = pattern.split('=')[0].replace('"', '').replace('r', '')
                        extracted_data[key] = match.group(1)
                
                # اگر داده‌های کافی یافت شد
                if len(extracted_data) >= 2:
                    return {
                        'channel_username': channel_username,
                        'post_id': post_id,
                        'data': extracted_data,
                        'cookies': response.cookies,
                        'html': html_content[:500]  # فقط بخشی برای دیباگ
                    }
                
                # روش جایگزین: استفاده از API داخلی تلگرام
                # تلگرام گاهی از endpoint خاصی استفاده می‌کند
                api_patterns = [
                    r'https://t\.me/v/\?views=[^"]+',
                    r'window\.Telegram\.WebView\.initParams\s*=\s*([^;]+)'
                ]
                
                for pattern in api_patterns:
                    match = re.search(pattern, html_content)
                    if match:
                        return {
                            'channel_username': channel_username,
                            'post_id': post_id,
                            'api_data': match.group(1),
                            'cookies': response.cookies
                        }
                
                logger.warning(f"داده‌های پست یافت نشد: {channel_username}/{post_id}")
                return None
                
        except Exception as e:
            logger.error(f"خطا در دریافت داده‌های پست: {e}")
            return None
    
    async def send_single_view(self, post_data, proxy_url=None, proxy_id=None):
        """ارسال یک ویو به پست - کامل شده"""
        try:
            session = await self.get_session(proxy_url)
            
            # روش 1: استفاده از endpoint استاندارد تلگرام
            endpoints = [
                f'https://t.me/v/?views={post_data.get("data", {}).get("view", "")}',
                f'https://t.me/{post_data["channel_username"]}/{post_data["post_id"]}?embed=1&mode=view',
                f'https://t.me/{post_data["channel_username"]}/{post_data["post_id"]}?view'
            ]
            
            success = False
            for endpoint in endpoints:
                try:
                    async with session.get(endpoint, allow_redirects=True) as response:
                        if response.status == 200:
                            response_text = await response.text()
                            
                            # بررسی موفقیت آمیز بودن
                            if any(keyword in response_text.lower() for keyword in ['view', 'success', 'ok', '200']):
                                success = True
                                break
                except:
                    continue
            
            # روش 2: روش جایگزین با POST
            if not success:
                try:
                    post_url = f'https://t.me/{post_data["channel_username"]}/{post_data["post_id"]}/view'
                    async with session.post(post_url, data={'view': '1'}) as response:
                        if response.status == 200:
                            success = True
                except:
                    pass
            
            # روش 3: استفاده از referer و headers خاص
            if not success:
                try:
                    headers = {
                        'Referer': f'https://t.me/{post_data["channel_username"]}/{post_data["post_id"]}',
                        'X-Requested-With': 'XMLHttpRequest',
                        'Accept': 'application/json, text/javascript, */*; q=0.01'
                    }
                    
                    async with session.get(
                        'https://t.me/v/',
                        params={'views': '1'},
                        headers=headers
                    ) as response:
                        if response.status == 200:
                            success = True
                except:
                    pass
            
            # لاگ کردن نتیجه
            if success and proxy_id:
                await update_proxy_usage(proxy_id, True)
                logger.info(f"✅ ویو ارسال شد با پروکسی {proxy_id}")
            elif proxy_id:
                await update_proxy_usage(proxy_id, False)
                logger.warning(f"❌ ارسال ویو ناموفق با پروکسی {proxy_id}")
            
            return success
            
        except Exception as e:
            logger.error(f"خطا در ارسال ویو: {e}")
            if proxy_id:
                await update_proxy_usage(proxy_id, False)
            return False
    
    async def send_bulk_views(self, channel_username, post_id, proxy_list, target_views, order_id, progress_callback=None):
        """ارسال دسته‌ای ویو - کامل شده"""
        logger.info(f"شروع ارسال ویو برای {channel_username}/{post_id} - هدف: {target_views}")
        
        # دریافت داده‌های پست (یک بار)
        post_data = await self.fetch_post_data(channel_username, post_id)
        if not post_data:
            logger.error("داده‌های پست دریافت نشد")
            return 0
        
        successful_views = 0
        completed_proxies = 0
        total_proxies = len(proxy_list)
        
        # محدود کردن تعداد ویو برای هر پروکسی
        views_per_proxy = min(MAX_VIEWS_PER_PROXY, max(1, target_views // max(1, len(proxy_list))))
        
        for proxy_info in proxy_list:
            if successful_views >= target_views:
                break
            
            proxy_id = proxy_info['proxy_id']
            proxy_url = proxy_info['proxy_address']
            
            # ارسال چند ویو با این پروکسی
            proxy_success = 0
            for attempt in range(views_per_proxy):
                if successful_views >= target_views:
                    break
                
                success = await self.send_single_view(post_data, proxy_url, proxy_id)
                
                # لاگ کردن تلاش
                await log_view_attempt(order_id, proxy_id, success)
                
                if success:
                    successful_views += 1
                    proxy_success += 1
                    
                    # آپدیت سفارش
                    await update_view_order(order_id, successful_views, 'processing')
                    
                    # گزارش پیشرفت
                    if progress_callback and successful_views % 10 == 0:
                        await progress_callback(
                            successful_views, 
                            target_views,
                            completed_proxies + 1,
                            total_proxies
                        )
                
                # وقفه کوتاه بین ارسال‌ها
                await asyncio.sleep(random.uniform(0.5, 1.5))
            
            completed_proxies += 1
            
            # گزارش پیشرفت برای پروکسی
            logger.info(f"پروکسی {proxy_id}: {proxy_success}/{views_per_proxy} ویو موفق")
        
        # آپدیت نهایی سفارش
        await update_view_order(order_id, successful_views, 'completed')
        
        logger.info(f"ارسال ویو کامل شد: {successful_views}/{target_views}")
        return successful_views
    
    async def estimate_required_proxies(self, target_views):
        """تخمین تعداد پروکسی مورد نیاز"""
        return min(100, max(10, target_views // MAX_VIEWS_PER_PROXY))

# ============================
# کلاس ربات تلگرام
# ============================
class TelegramBot:
    def __init__(self):
        self.token = TOKEN
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.session = None
    
    async def get_session(self):
        """ایجاد session ناهمزمان"""
        if not self.session:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def close(self):
        """بستن session"""
        if self.session:
            await self.session.close()
    
    async def send_message(self, chat_id, text, parse_mode=None, reply_markup=None, disable_web_page_preview=True):
        """ارسال پیام"""
        url = f"{self.base_url}/sendMessage"
        
        payload = {
            'chat_id': chat_id,
            'text': text,
            'disable_web_page_preview': disable_web_page_preview
        }
        
        if parse_mode:
            payload['parse_mode'] = parse_mode
        
        if reply_markup:
            payload['reply_markup'] = json.dumps(reply_markup)
        
        try:
            session = await self.get_session()
            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get('result', {})
                else:
                    logger.error(f"خطا در ارسال پیام: {response.status}")
        except Exception as e:
            logger.error(f"خطا در تابع send_message: {e}")
        
        return None
    
    async def send_document(self, chat_id, document_path, caption=None, filename=None):
        """ارسال فایل"""
        url = f"{self.base_url}/sendDocument"
        
        try:
            # بررسی وجود فایل
            if not os.path.exists(document_path):
                raise FileNotFoundError(f"فایل {document_path} یافت نشد")
            
            # ایجاد FormData
            data = aiohttp.FormData()
            data.add_field('chat_id', str(chat_id))
            
            if caption:
                data.add_field('caption', caption)
            
            # باز کردن فایل و اضافه کردن آن
            with open(document_path, 'rb') as file:
                if not filename:
                    filename = os.path.basename(document_path)
                data.add_field('document', file, filename=filename)
                
                session = await self.get_session()
                async with session.post(url, data=data) as response:
                    if response.status == 200:
                        result = await response.json()
                        return result.get('result', {})
                    else:
                        error_text = await response.text()
                        logger.error(f"خطا در ارسال فایل: {error_text[:200]}")
                        return None
                            
        except Exception as e:
            logger.error(f"خطا در تابع send_document: {e}")
            return None
    
    async def edit_message_text(self, chat_id, message_id, text, parse_mode=None, reply_markup=None):
        """ویرایش پیام"""
        url = f"{self.base_url}/editMessageText"
        
        payload = {
            'chat_id': chat_id,
            'message_id': message_id,
            'text': text
        }
        
        if parse_mode:
            payload['parse_mode'] = parse_mode
        
        if reply_markup:
            payload['reply_markup'] = json.dumps(reply_markup)
        
        try:
            session = await self.get_session()
            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    logger.error(f"خطا در ویرایش پیام: {response.status}")
        except Exception as e:
            logger.error(f"خطا در edit_message_text: {e}")
        
        return None
    
    async def answer_callback_query(self, callback_query_id, text=None, show_alert=False, cache_time=0):
        """پاسخ به کوئری callback"""
        url = f"{self.base_url}/answerCallbackQuery"
        
        payload = {
            'callback_query_id': callback_query_id,
            'show_alert': show_alert,
            'cache_time': cache_time
        }
        
        if text:
            payload['text'] = text
        
        try:
            session = await self.get_session()
            async with session.post(url, json=payload) as response:
                return response.status == 200
        except Exception as e:
            logger.error(f"خطا در answer_callback_query: {e}")
            return False
    
    async def get_updates(self, offset=None, timeout=30, allowed_updates=None):
        """دریافت آپدیت‌ها"""
        url = f"{self.base_url}/getUpdates"
        
        params = {
            'timeout': timeout
        }
        
        if offset:
            params['offset'] = offset
        
        if allowed_updates:
            params['allowed_updates'] = json.dumps(allowed_updates)
        
        try:
            session = await self.get_session()
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get('result', [])
                else:
                    logger.error(f"خطا در دریافت آپدیت‌ها: {response.status}")
        except Exception as e:
            logger.error(f"خطا در get_updates: {e}")
        
        return []
    
    async def download_file(self, file_id, file_path):
        """دانلود فایل از تلگرام"""
        try:
            # دریافت اطلاعات فایل
            url = f"{self.base_url}/getFile"
            session = await self.get_session()
            
            async with session.post(url, json={'file_id': file_id}) as response:
                if response.status == 200:
                    file_info = await response.json()
                    if file_info.get('ok'):
                        file_path_tg = file_info['result']['file_path']
                        
                        # دانلود فایل
                        download_url = f"https://api.telegram.org/file/bot{self.token}/{file_path_tg}"
                        async with session.get(download_url) as download_response:
                            if download_response.status == 200:
                                content = await download_response.read()
                                
                                # ذخیره فایل
                                with open(file_path, 'wb') as f:
                                    f.write(content)
                                
                                logger.info(f"فایل دانلود شد: {file_path}")
                                return True
        except Exception as e:
            logger.error(f"خطا در دانلود فایل: {e}")
        
        return False
    
    async def send_chat_action(self, chat_id, action):
        """ارسال وضعیت در حال انجام کار"""
        url = f"{self.base_url}/sendChatAction"
        
        payload = {
            'chat_id': chat_id,
            'action': action
        }
        
        try:
            session = await self.get_session()
            async with session.post(url, json=payload) as response:
                return response.status == 200
        except Exception as e:
            logger.error(f"خطا در send_chat_action: {e}")
            return False
    
    async def delete_message(self, chat_id, message_id):
        """حذف پیام"""
        url = f"{self.base_url}/deleteMessage"
        
        payload = {
            'chat_id': chat_id,
            'message_id': message_id
        }
        
        try:
            session = await self.get_session()
            async with session.post(url, json=payload) as response:
                return response.status == 200
        except Exception as e:
            logger.error(f"خطا در delete_message: {e}")
            return False

# ============================
# کلاس مدیریت پروکسی
# ============================
class ProxyManager:
    def __init__(self):
        self.fetcher = ProxyFetcher()
        self.view_sender = TelegramViewSender()
    
    async def update_progress_in_telegram(self, bot, chat_id, message_id, **kwargs):
        """آپدیت پیشرفت در پیام تلگرام"""
        stage = kwargs.get('stage', '')
        progress = kwargs.get('progress', 0)
        current = kwargs.get('current', 0)
        total = kwargs.get('total', 0)
        found = kwargs.get('found', 0)
        error = kwargs.get('error', '')
        new = kwargs.get('new', 0)
        duplicates = kwargs.get('duplicates', 0)
        
        progress_bar = self._create_progress_bar(progress)
        
        if error:
            text = f"""
❌ **خطا در دریافت پروکسی‌ها**

📝 خطا: `{error}`

⚠️ عملیات متوقف شد.
"""
        elif stage == "دریافت از منابع":
            text = f"""
🌐 **در حال دریافت پروکسی‌ها از اینترنت...**

📋 **مرحله:** {stage}
{progress_bar}
📊 **پیشرفت:** {progress}%

📥 منابع بررسی شده: {current}/{total}
📦 پروکسی‌های یافت شده: {found}

⏳ لطفاً صبر کنید...
"""
        elif stage == "تکمیل":
            text = f"""
✅ **دریافت پروکسی‌ها با موفقیت کامل شد!**

🎉 **عملیات با موفقیت به پایان رسید**

📊 **آمار:**
├ پروکسی‌های جدید: {new}
├ پروکسی‌های تکراری: {duplicates}
└ کل پروکسی‌های یافت شده: {found}

💾 پروکسی‌ها در دیتابیس ذخیره شدند.
📁 در حال ایجاد فایل‌های خروجی...
"""
        else:
            text = f"""
🔄 **در حال پردازش...**

📋 **مرحله:** {stage}
{progress_bar}
📊 **پیشرفت:** {progress}%

⏳ لطفاً صبر کنید...
"""
        
        try:
            await bot.edit_message_text(chat_id, message_id, text, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"خطا در آپدیت پیشرفت: {e}")
    
    def _create_progress_bar(self, percentage, length=20):
        """ایجاد نوار پیشرفت"""
        filled_length = int(length * percentage // 100)
        bar = '█' * filled_length + '░' * (length - filled_length)
        return f"[{bar}]"
    
    async def get_proxies_online(self, max_proxies=500, bot=None, chat_id=None, message_id=None):
        """دریافت پروکسی‌ها از منابع آنلاین"""
        async def update_callback(**kwargs):
            if bot and chat_id and message_id:
                await self.update_progress_in_telegram(bot, chat_id, message_id, **kwargs)
        
        proxies = await self.fetcher.fetch_proxies(
            max_proxies=max_proxies,
            update_progress_callback=update_callback
        )
        
        saved_files = []
        if proxies:
            saved_files = await self.fetcher.save_proxies_to_files(proxies)
        
        return proxies, saved_files
    
    def categorize_proxies(self, proxies):
        """دسته‌بندی پروکسی‌ها بر اساس نوع"""
        categorized = {
            'http': [],
            'https': [],
            'socks4': [],
            'socks5': [],
            'all': []
        }
        
        for proxy in proxies:
            proxy_type = proxy['proxy_type']
            proxy_address = proxy['proxy_address']
            
            if proxy_type in categorized:
                categorized[proxy_type].append(proxy_address)
            
            categorized['all'].append(proxy_address)
        
        return categorized
    
    async def send_views(self, channel_username, post_id, target_views, order_id, progress_callback=None):
        """ارسال ویو به پست تلگرام - کامل شده"""
        # تخمین تعداد پروکسی مورد نیاز
        required_proxies = await self.view_sender.estimate_required_proxies(target_views)
        
        # دریافت پروکسی‌ها از دیتابیس
        proxies = await get_proxies_for_view(required_proxies * 2)  # بیشتر بگیریم برای احتیاط
        
        if not proxies:
            logger.error("هیچ پروکسی برای ارسال ویو موجود نیست")
            return 0
        
        logger.info(f"استفاده از {len(proxies)} پروکسی برای ارسال {target_views} ویو")
        
        # ارسال ویو‌ها
        successful_views = await self.view_sender.send_bulk_views(
            channel_username=channel_username,
            post_id=post_id,
            proxy_list=proxies,
            target_views=target_views,
            order_id=order_id,
            progress_callback=progress_callback
        )
        
        return successful_views
    
    async def cleanup(self):
        """پاکسازی منابع"""
        await self.view_sender.close_all_sessions()

# ============================
# کلاس اصلی ربات (کامل شده)
# ============================
class BotHandler:
    def __init__(self):
        self.bot = TelegramBot()
        self.proxy_manager = ProxyManager()
        self.user_states = {}  # برای ذخیره وضعیت کاربران
        self.active_orders = {}  # برای پیگیری سفارشات فعال
        logger.info("هندلر ربات راه‌اندازی شد")
    
    def create_keyboard(self, buttons, row_width=2):
        """ایجاد صفحه کلید"""
        keyboard = []
        current_row = []
        
        for button in buttons:
            if isinstance(button, tuple):
                text, callback_data = button
                current_row.append({"text": text, "callback_data": callback_data})
            else:
                current_row.append({"text": button, "callback_data": button})
            
            if len(current_row) >= row_width:
                keyboard.append(current_row)
                current_row = []
        
        if current_row:
            keyboard.append(current_row)
        
        return {"inline_keyboard": keyboard}
    
    def create_main_menu(self):
        """ایجاد منوی اصلی"""
        return self.create_keyboard([
            ("📄 آپلود فایل پروکسی", "upload_proxy"),
            ("🌐 دریافت پروکسی آنلاین", "fetch_online_proxies"),
            ("📈 افزایش ویو تلگرام", "increase_views"),
            ("📊 آمار ربات", "stats"),
            ("⚙️ پنل مدیریت", "admin_panel"),
            ("📖 راهنما", "help")
        ], row_width=2)
    
    def create_admin_menu(self):
        """ایجاد منوی مدیریت"""
        return self.create_keyboard([
            ("📊 آمار لحظه‌ای", "live_stats"),
            ("🌐 دریافت پروکسی", "admin_fetch_proxies"),
            ("📨 پیام همگانی", "broadcast"),
            ("🧹 پاکسازی دیتابیس", "cleanup"),
            ("📋 لیست کاربران", "user_list"),
            ("🔙 بازگشت", "back_to_main")
        ], row_width=2)
    
    def create_views_menu(self):
        """ایجاد منوی افزایش ویو"""
        return self.create_keyboard([
            ("➕ ایجاد سفارش جدید", "create_view_order"),
            ("📋 سفارشات من", "my_orders"),
            ("🔙 بازگشت", "back_to_main")
        ], row_width=2)
    
    async def handle_start(self, chat_id, user):
        """مدیریت دستور /start"""
        await add_user(user['id'], user.get('username', ''), user.get('first_name', ''), user.get('last_name', ''))
        
        welcome_text = """
🤖 **ربات حرفه‌ای مدیریت پروکسی و افزایش ویو تلگرام**

🎯 **ویژگی‌های اصلی:**
• 📄 آپلود و مدیریت فایل‌های پروکسی
• 🌐 دریافت خودکار پروکسی از اینترنت
• 📈 افزایش ویو پست‌های تلگرام
• 📊 آمار و گزارش‌های کامل
• ⚙️ پنل مدیریت پیشرفته

🔸 **برای شروع از دکمه‌های زیر استفاده کنید:**

👨‍💻 **توسعه‌دهنده:** @Erfan138600
📢 **کانال پشتیبانی:** در حال راه‌اندازی
"""
        
        await self.bot.send_message(
            chat_id, 
            welcome_text, 
            parse_mode='Markdown', 
            reply_markup=self.create_main_menu()
        )
    
    async def handle_fetch_online_proxies(self, chat_id, message_id):
        """دریافت پروکسی‌ها از منابع آنلاین"""
        initial_text = """
🌐 **شروع دریافت پروکسی‌ها از اینترنت...**

⏳ در حال اتصال به منابع...
📋 **مرحله:** آماده‌سازی
[░░░░░░░░░░░░░░░░░░░░] 0%

📊 **لطفاً صبر کنید، این عملیات ممکن است چند دقیقه طول بکشد...**
"""
        
        progress_msg = await self.bot.send_message(chat_id, initial_text, parse_mode='Markdown')
        
        try:
            await self.bot.send_chat_action(chat_id, "typing")
            
            proxies, saved_files = await self.proxy_manager.get_proxies_online(
                max_proxies=500,
                bot=self.bot,
                chat_id=chat_id,
                message_id=progress_msg['message_id']
            )
            
            if not proxies:
                final_text = """
❌ **دریافت پروکسی‌ها ناموفق بود!**

⚠️ **خطا:** هیچ پروکسی‌ای یافت نشد!

🔧 **راه‌حل‌های ممکن:**
1️⃣ اتصال اینترنت خود را بررسی کنید
2️⃣ بعداً دوباره تلاش کنید
3️⃣ از فایل پروکسی آپلود شده استفاده کنید
"""
                await self.bot.edit_message_text(
                    chat_id, 
                    progress_msg['message_id'], 
                    final_text, 
                    parse_mode='Markdown'
                )
                return
            
            categorized = self.proxy_manager.categorize_proxies(proxies)
            
            stats_text = f"""
✅ **دریافت پروکسی‌ها با موفقیت کامل شد!**

🎉 **عملیات با موفقیت به پایان رسید**

📊 **آمار پروکسی‌های دریافتی:**

🔸 **بر اساس نوع:**
├ HTTP: {len(categorized['http'])} پروکسی
├ HTTPS: {len(categorized['https'])} پروکسی
├ SOCKS4: {len(categorized['socks4'])} پروکسی
└ SOCKS5: {len(categorized['socks5'])} پروکسی

📈 **مجموع: {len(proxies)} پروکسی منحصربه‌فرد**

💾 پروکسی‌ها در دیتابیس ذخیره شدند.
📁 **در حال ارسال فایل‌ها...**
"""
            
            await self.bot.edit_message_text(
                chat_id, 
                progress_msg['message_id'], 
                stats_text, 
                parse_mode='Markdown'
            )
            
            # ارسال فایل‌های ذخیره شده
            for file_path in saved_files:
                if os.path.exists(file_path):
                    await self.bot.send_chat_action(chat_id, "upload_document")
                    await self.bot.send_document(
                        chat_id, 
                        file_path, 
                        caption=f"📁 فایل پروکسی‌ها"
                    )
                    
                    await asyncio.sleep(2)
                    try:
                        os.remove(file_path)
                    except:
                        pass
            
            await self.cleanup_old_files("proxy_files")
            
        except Exception as e:
            error_text = f"""
❌ **خطا در دریافت پروکسی‌ها!**

⚠️ **خطای فنی:** `{str(e)[:200]}`

🔧 **لطفاً بعداً دوباره تلاش کنید.**
"""
            await self.bot.edit_message_text(
                chat_id, 
                progress_msg['message_id'], 
                error_text, 
                parse_mode='Markdown'
            )
            logger.error(f"خطا در handle_fetch_online_proxies: {e}")
    
    async def handle_increase_views(self, chat_id, message_id, user_id):
        """منوی افزایش ویو"""
        text = """
📈 **افزایش ویو پست‌های تلگرام**

با این قابلیت می‌توانید ویو پست‌های تلگرام خود را افزایش دهید.

🔸 **نحوه استفاده:**
1️⃣ روی «ایجاد سفارش جدید» کلیک کنید
2️⃣ لینک پست تلگرام را ارسال کنید
3️⃣ تعداد ویو مورد نظر را وارد کنید
4️⃣ عملیات به صورت خودکار شروع می‌شود

⚠️ **توجه:**
• حداقل سفارش: 100 ویو
• حداکثر سفارش: 5000 ویو
• سرعت ارسال: 50-100 ویو در دقیقه
"""
        
        await self.bot.edit_message_text(
            chat_id, message_id, 
            text, 
            parse_mode='Markdown',
            reply_markup=self.create_views_menu()
        )
    
    async def handle_create_view_order(self, chat_id, message_id, user_id):
        """شروع ایجاد سفارش افزایش ویو"""
        # ذخیره وضعیت کاربر
        self.user_states[user_id] = {
            'state': 'awaiting_post_link',
            'step': 1,
            'data': {}
        }
        
        text = """
📤 **مرحله ۱ از ۲: ارسال لینک پست**

🔗 لطفاً لینک پست تلگرام را ارسال کنید:

**فرمت‌های قابل قبول:**
• https://t.me/channel/123
• t.me/channel/123
• @channel/123

📝 **مثال:** `https://t.me/mychannel/123`

برای لغو عملیات /cancel را ارسال کنید.
"""
        
        await self.bot.edit_message_text(
            chat_id, message_id, 
            text, 
            parse_mode='Markdown'
        )
    
    async def handle_my_orders(self, chat_id, message_id, user_id):
        """نمایش سفارشات کاربر"""
        async with db_lock:
            conn = sqlite3.connect('bot_stats.db', check_same_thread=False)
            cursor = conn.cursor()
            try:
                cursor.execute('''
                    SELECT order_id, channel_username, post_id, target_views, 
                           completed_views, status, start_time
                    FROM view_orders 
                    WHERE user_id = ?
                    ORDER BY start_time DESC
                    LIMIT 10
                ''', (user_id,))
                
                orders = cursor.fetchall()
                
                if not orders:
                    text = "📭 **شما هیچ سفارش فعالی ندارید.**"
                else:
                    text = "📋 **آخرین سفارشات شما:**\n\n"
                    
                    for order in orders:
                        order_id, channel, post_id, target, completed, status, start_time = order
                        
                        status_icon = "🟢" if status == 'completed' else "🟡" if status == 'processing' else "🔴"
                        progress = (completed / target * 100) if target > 0 else 0
                        
                        text += f"""
{status_icon} **سفارش #{order_id}**
├ کانال: @{channel}/{post_id}
├ هدف: {target:,} ویو
├ تکمیل شده: {completed:,} ویو ({progress:.1f}%)
├ وضعیت: {status}
└ تاریخ: {start_time[:19]}

"""
                
                keyboard = self.create_keyboard([
                    ("➕ سفارش جدید", "create_view_order"),
                    ("🔄 بروزرسانی", "my_orders"),
                    ("🔙 بازگشت", "back_to_main")
                ])
                
                await self.bot.edit_message_text(
                    chat_id, message_id, 
                    text, 
                    parse_mode='Markdown',
                    reply_markup=keyboard
                )
                
            finally:
                conn.close()
    
    async def process_post_link(self, chat_id, user_id, text):
        """پردازش لینک پست تلگرام"""
        if user_id not in self.user_states:
            return False
        
        state = self.user_states[user_id]
        if state['state'] != 'awaiting_post_link':
            return False
        
        # استخراج اطلاعات از لینک
        channel_username = None
        post_id = None
        
        try:
            # پاکسازی لینک
            text = text.strip()
            
            # حذف پروتکل‌ها
            if '://' in text:
                text = text.split('://')[1]
            
            # حذف www
            text = text.replace('www.', '')
            
            # استخراج اطلاعات
            if 't.me/' in text:
                parts = text.split('t.me/')[1].split('/')
                if len(parts) >= 1:
                    channel_username = parts[0].replace('@', '')
                if len(parts) >= 2:
                    post_id = parts[1].split('?')[0]  # حذف query parameters
            elif '/' in text:
                parts = text.split('/')
                if len(parts) >= 2:
                    channel_username = parts[0].replace('@', '')
                    post_id = parts[1].split('?')[0]
            
            # اعتبارسنجی
            if not channel_username or not post_id or not post_id.isdigit():
                await self.bot.send_message(
                    chat_id,
                    "❌ **لینک نامعتبر!**\n\nلطفاً لینک معتبر پست تلگرام را ارسال کنید.\nمثال: `https://t.me/channel/123`",
                    parse_mode='Markdown'
                )
                return False
            
            # ذخیره داده‌ها
            state['data']['channel_username'] = channel_username
            state['data']['post_id'] = post_id
            state['state'] = 'awaiting_view_count'
            state['step'] = 2
            
            text = f"""
✅ **لینک پست با موفقیت دریافت شد!**

📊 **اطلاعات استخراج شده:**
├ کانال: @{channel_username}
├ پست: {post_id}
└ لینک: https://t.me/{channel_username}/{post_id}

📤 **مرحله ۲ از ۲: تعداد ویو**

🔢 لطفاً تعداد ویو مورد نظر را وارد کنید:

**محدودیت‌ها:**
• حداقل: 100 ویو
• حداکثر: 5000 ویو
• توصیه شده: 500-1000 ویو

برای لغو عملیات /cancel را ارسال کنید.
"""
            
            await self.bot.send_message(chat_id, text, parse_mode='Markdown')
            return True
            
        except Exception as e:
            logger.error(f"خطا در پردازش لینک: {e}")
            await self.bot.send_message(
                chat_id,
                "❌ **خطا در پردازش لینک!**\n\nلطفاً لینک معتبری ارسال کنید.",
                parse_mode='Markdown'
            )
            return False
    
    async def process_view_count(self, chat_id, user_id, text):
        """پردازش تعداد ویو"""
        if user_id not in self.user_states:
            return False
        
        state = self.user_states[user_id]
        if state['state'] != 'awaiting_view_count':
            return False
        
        try:
            # تبدیل به عدد
            view_count = int(text.strip().replace(',', ''))
            
            # اعتبارسنجی
            if view_count < 100:
                await self.bot.send_message(
                    chat_id,
                    "❌ **تعداد ویو کمتر از حد مجاز!**\n\nحداقل تعداد ویو: 100\nلطفاً تعداد معتبری وارد کنید.",
                    parse_mode='Markdown'
                )
                return False
            
            if view_count > 5000:
                await self.bot.send_message(
                    chat_id,
                    "❌ **تعداد ویو بیشتر از حد مجاز!**\n\nحداکثر تعداد ویو: 5000\nلطفاً تعداد معتبری وارد کنید.",
                    parse_mode='Markdown'
                )
                return False
            
            # ذخیره داده‌ها
            state['data']['view_count'] = view_count
            
            # ایجاد سفارش
            channel_username = state['data']['channel_username']
            post_id = state['data']['post_id']
            
            order_id = await create_view_order(user_id, channel_username, post_id, view_count)
            
            # پاکسازی وضعیت
            del self.user_states[user_id]
            
            # نمایش تاییدیه
            confirm_text = f"""
✅ **سفارش شما ثبت شد!**

📋 **جزئیات سفارش:**
├ شماره سفارش: #{order_id}
├ کانال: @{channel_username}
├ پست: {post_id}
├ تعداد ویو: {view_count:,}
└ وضعیت: در انتظار شروع

⏳ **در حال شروع عملیات...**
لطفاً صبر کنید، این عملیات ممکن است چند دقیقه طول بکشد.
"""
            
            await self.bot.send_message(chat_id, confirm_text, parse_mode='Markdown')
            
            # شروع عملیات افزایش ویو
            await self.start_view_order(chat_id, order_id, user_id, channel_username, post_id, view_count)
            
            return True
            
        except ValueError:
            await self.bot.send_message(
                chat_id,
                "❌ **ورودی نامعتبر!**\n\nلطفاً یک عدد معتبر وارد کنید.\nمثال: 500",
                parse_mode='Markdown'
            )
            return False
        except Exception as e:
            logger.error(f"خطا در پردازش تعداد ویو: {e}")
            await self.bot.send_message(
                chat_id,
                "❌ **خطا در ثبت سفارش!**\n\nلطفاً دوباره تلاش کنید.",
                parse_mode='Markdown'
            )
            return False
    
    async def start_view_order(self, chat_id, order_id, user_id, channel_username, post_id, target_views):
        """شروع عملیات افزایش ویو"""
        progress_msg = await self.bot.send_message(
            chat_id,
            f"""
🔄 **شروع عملیات افزایش ویو**

📊 **سفارش #{order_id}**
├ کانال: @{channel_username}
├ پست: {post_id}
├ هدف: {target_views:,} ویو
└ وضعیت: در حال شروع...

⏳ لطفاً صبر کنید...
            """,
            parse_mode='Markdown'
        )
        
        try:
            # آپدیت پیام پیشرفت
            async def update_progress(current, total, proxies_done, proxies_total):
                progress = (current / total * 100) if total > 0 else 0
                progress_bar = self._create_progress_bar(progress)
                
                text = f"""
🔄 **در حال افزایش ویو...**

📊 **سفارش #{order_id}**
├ کانال: @{channel_username}
├ پست: {post_id}
├ هدف: {target_views:,} ویو
├ تکمیل شده: {current:,} ویو ({progress:.1f}%)
├ پروکسی‌ها: {proxies_done}/{proxies_total}
└ وضعیت: در حال اجرا...

{progress_bar} {progress:.1f}%

⏳ لطفاً صبر کنید...
                """
                
                await self.bot.edit_message_text(
                    chat_id, progress_msg['message_id'],
                    text, parse_mode='Markdown'
                )
            
            # ارسال ویو‌ها
            successful_views = await self.proxy_manager.send_views(
                channel_username=channel_username,
                post_id=post_id,
                target_views=target_views,
                order_id=order_id,
                progress_callback=update_progress
            )
            
            # نمایش نتیجه نهایی
            success_rate = (successful_views / target_views * 100) if target_views > 0 else 0
            
            result_text = f"""
✅ **عملیات افزایش ویو کامل شد!**

📊 **نتایج سفارش #{order_id}:**
├ کانال: @{channel_username}
├ پست: {post_id}
├ هدف: {target_views:,} ویو
├ تکمیل شده: {successful_views:,} ویو
├ نرخ موفقیت: {success_rate:.1f}%
└ وضعیت: تکمیل شده

🎉 **سفارش با موفقیت انجام شد!**

برای مشاهده سفارشات دیگر روی «سفارشات من» کلیک کنید.
            """
            
            keyboard = self.create_keyboard([
                ("📋 سفارشات من", "my_orders"),
                ("➕ سفارش جدید", "create_view_order"),
                ("🔙 منوی اصلی", "back_to_main")
            ])
            
            await self.bot.edit_message_text(
                chat_id, progress_msg['message_id'],
                result_text, parse_mode='Markdown',
                reply_markup=keyboard
            )
            
        except Exception as e:
            logger.error(f"خطا در افزایش ویو: {e}")
            
            error_text = f"""
❌ **خطا در افزایش ویو!**

📊 **سفارش #{order_id}:**
├ کانال: @{channel_username}
├ پست: {post_id}
├ هدف: {target_views:,} ویو
└ وضعیت: خطا

⚠️ **خطا:** `{str(e)[:200]}`

🔧 لطفاً بعداً دوباره تلاش کنید یا با پشتیبانی تماس بگیرید.
            """
            
            await self.bot.edit_message_text(
                chat_id, progress_msg['message_id'],
                error_text, parse_mode='Markdown'
            )
    
    def _create_progress_bar(self, percentage, length=20):
        """ایجاد نوار پیشرفت"""
        filled_length = int(length * percentage // 100)
        bar = '█' * filled_length + '░' * (length - filled_length)
        return f"[{bar}]"
    
    async def handle_callback_query(self, callback_query, message):
        """مدیریت کلیک روی دکمه‌ها"""
        data = callback_query.get('data')
        chat_id = message['chat']['id']
        message_id = message['message_id']
        user_id = callback_query['from']['id']
        
        await self.bot.answer_callback_query(callback_query['id'])
        
        if data == 'upload_proxy':
            text = (
                "📁 **آپلود فایل پروکسی**\n\n"
                "لطفاً فایل txt حاوی پروکسی‌ها را ارسال کنید.\n\n"
                "💡 **فرمت‌های پشتیبانی شده:**\n"
                "• http://user:pass@host:port\n"
                "• https://host:port\n"
                "• socks4://host:port\n"
                "• socks5://host:port\n"
                "• host:port:user:pass\n"
                "• host:port\n\n"
                "⚠️ **محدودیت‌ها:**\n"
                "• حداکثر حجم: 20 مگابایت\n"
                "• فقط فایل‌های txt و csv\n"
                "• حداکثر 10,000 خط در فایل\n\n"
                "برای لغو عملیات /cancel را ارسال کنید."
            )
            await self.bot.edit_message_text(chat_id, message_id, text, parse_mode='Markdown')
            
        elif data == 'fetch_online_proxies':
            await self.handle_fetch_online_proxies(chat_id, message_id)
            
        elif data == 'increase_views':
            await self.handle_increase_views(chat_id, message_id, user_id)
            
        elif data == 'create_view_order':
            await self.handle_create_view_order(chat_id, message_id, user_id)
            
        elif data == 'my_orders':
            await self.handle_my_orders(chat_id, message_id, user_id)
            
        elif data == 'stats':
            await self.show_stats(chat_id, message_id)
            
        elif data == 'admin_panel':
            await self.show_admin_panel(chat_id, message_id, user_id)
        
        elif data == 'back_to_main':
            if user_id in self.user_states:
                del self.user_states[user_id]
            await self.bot.edit_message_text(
                chat_id, message_id,
                "🔙 **بازگشت به منوی اصلی**",
                parse_mode='Markdown',
                reply_markup=self.create_main_menu()
            )
            
        elif data == 'live_stats':
            if user_id in ADMINS:
                await self.show_stats(chat_id, message_id)
            else:
                await self.bot.answer_callback_query(callback_query['id'], text="⛔ دسترسی ندارید!", show_alert=True)
        
        elif data == 'admin_fetch_proxies':
            if user_id in ADMINS:
                await self.handle_fetch_online_proxies(chat_id, message_id)
            else:
                await self.bot.answer_callback_query(callback_query['id'], text="⛔ دسترسی ندارید!", show_alert=True)
        
        elif data == 'broadcast':
            if user_id in ADMINS:
                await self.start_broadcast(chat_id, message_id, user_id)
            else:
                await self.bot.answer_callback_query(callback_query['id'], text="⛔ دسترسی ندارید!", show_alert=True)
        
        elif data == 'cleanup':
            if user_id in ADMINS:
                await self.cleanup_database(chat_id, message_id)
            else:
                await self.bot.answer_callback_query(callback_query['id'], text="⛔ دسترسی ندارید!", show_alert=True)
        
        elif data == 'user_list':
            if user_id in ADMINS:
                await self.show_user_list(chat_id, message_id)
            else:
                await self.bot.answer_callback_query(callback_query['id'], text="⛔ دسترسی ندارید!", show_alert=True)
        
        elif data == 'help':
            await self.show_help(chat_id, message_id)
    
    async def handle_document(self, message):
        """مدیریت دریافت فایل - کامل شده"""
        chat_id = message['chat']['id']
        user_id = message['from']['id']
        document = message.get('document', {})
        
        if not document:
            await self.bot.send_message(chat_id, "❌ لطفاً یک فایل ارسال کنید.")
            return
        
        # بررسی حجم فایل
        file_size = document.get('file_size', 0)
        if file_size > MAX_FILE_SIZE:
            await self.bot.send_message(chat_id, f"❌ حجم فایل ({file_size/1024/1024:.1f} MB) بیشتر از 20 مگابایت است.")
            return
        
        # بررسی فرمت فایل
        file_name = document.get('file_name', '').lower()
        if not (file_name.endswith('.txt') or file_name.endswith('.csv')):
            await self.bot.send_message(chat_id, "❌ فقط فایل‌های txt و csv پشتیبانی می‌شوند.")
            return
        
        file_id = document['file_id']
        
        await self.bot.send_message(chat_id, "📥 در حال دانلود فایل...")
        await self.bot.send_chat_action(chat_id, "typing")
        
        # ایجاد نام فایل موقت
        temp_dir = "temp_files"
        await async_os.makedirs(temp_dir, exist_ok=True)
        temp_file = os.path.join(temp_dir, f"{file_id}_{file_name}")
        
        # دانلود فایل
        if await self.bot.download_file(file_id, temp_file):
            await self.bot.send_message(chat_id, "✅ فایل با موفقیت دانلود شد. در حال پردازش...")
            
            # پردازش فایل
            await self.process_proxy_file(chat_id, temp_file, file_name, user_id)
            
            # حذف فایل موقت
            try:
                await async_os.remove(temp_file)
            except:
                pass
            
            # پاکسازی فایل‌های قدیمی
            await self.cleanup_old_files(temp_dir, max_age_hours=1)
        else:
            await self.bot.send_message(chat_id, "❌ خطا در دانلود فایل. لطفاً دوباره تلاش کنید.")
    
    async def process_proxy_file(self, chat_id, file_path, original_filename, user_id):
        """پردازش فایل پروکسی - کامل شده"""
        progress_msg = await self.bot.send_message(chat_id, "📊 در حال بررسی فایل...")
        
        try:
            proxies = []
            line_count = 0
            valid_count = 0
            
            # خواندن فایل با مدیریت encoding
            async with aiofiles.open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                # تخمین تعداد خطوط
                content = await f.read()
                lines = content.split('\n')
                total_lines = len(lines)
                
                await self.bot.edit_message_text(
                    chat_id, progress_msg['message_id'],
                    f"📊 در حال پردازش {total_lines:,} خط...\n\n⏳ لطفاً صبر کنید...",
                    parse_mode='Markdown'
                )
                
                # پردازش خطوط
                for i, line in enumerate(lines):
                    line = line.strip()
                    line_count += 1
                    
                    if not line:
                        continue
                    
                    # نرمال‌سازی پروکسی
                    normalized, proxy_type = ProxyFetcher().normalize_proxy(line)
                    if normalized and proxy_type:
                        proxies.append({
                            'proxy_address': normalized,
                            'proxy_type': proxy_type
                        })
                        valid_count += 1
                    
                    # گزارش پیشرفت هر 500 خط
                    if i % 500 == 0 and i > 0:
                        progress = (i / total_lines * 100)
                        await self.bot.edit_message_text(
                            chat_id, progress_msg['message_id'],
                            f"📊 در حال پردازش...\n\n"
                            f"├ خطوط پردازش شده: {i:,}/{total_lines:,}\n"
                            f"├ پروکسی‌های معتبر: {valid_count:,}\n"
                            f"└ پیشرفت: {progress:.1f}%\n\n"
                            f"⏳ لطفاً صبر کنید...",
                            parse_mode='Markdown'
                        )
            
            if not proxies:
                await self.bot.edit_message_text(
                    chat_id, progress_msg['message_id'],
                    "❌ **هیچ پروکسی معتبری در فایل یافت نشد.**\n\n"
                    "لطفاً فایلی با فرمت صحیح ارسال کنید.",
                    parse_mode='Markdown'
                )
                return
            
            # ذخیره در دیتابیس
            new_count, duplicate_count = await save_proxies_to_db(proxies)
            
            # ذخیره در فایل
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            await async_os.makedirs("uploaded_files", exist_ok=True)
            output_file = f"uploaded_files/uploaded_proxies_{timestamp}.txt"
            
            async with aiofiles.open(output_file, 'w', encoding='utf-8') as f:
                for proxy in proxies:
                    await f.write(f"{proxy['proxy_address']}\n")
            
            # آپدیت آمار کاربر
            async with db_lock:
                conn = sqlite3.connect('bot_stats.db', check_same_thread=False)
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE users SET 
                    total_proxies_uploaded = total_proxies_uploaded + ?
                    WHERE user_id = ?
                ''', (new_count, user_id))
                conn.commit()
                conn.close()
            
            # ارسال نتایج
            result_text = f"""
✅ **پردازش فایل کامل شد!**

📊 **آمار پردازش:**
├ خطوط بررسی شده: {line_count:,}
├ پروکسی‌های معتبر: {valid_count:,}
├ پروکسی‌های جدید: {new_count:,}
└ پروکسی‌های تکراری: {duplicate_count:,}

💾 پروکسی‌ها در دیتابیس ذخیره شدند.
📁 فایل خروجی آماده است.
"""
            
            keyboard = self.create_keyboard([
                ("📁 دریافت فایل", f"download_{output_file}"),
                ("📊 مشاهده آمار", "stats"),
                ("🔙 منوی اصلی", "back_to_main")
            ])
            
            await self.bot.edit_message_text(
                chat_id, progress_msg['message_id'],
                result_text, parse_mode='Markdown',
                reply_markup=keyboard
            )
            
        except Exception as e:
            logger.error(f"خطا در پردازش فایل: {e}")
            await self.bot.edit_message_text(
                chat_id, progress_msg['message_id'],
                f"❌ **خطا در پردازش فایل!**\n\n`{str(e)[:200]}`",
                parse_mode='Markdown'
            )
    
    async def handle_text(self, message):
        """مدیریت دریافت متن - کامل شده"""
        chat_id = message['chat']['id']
        text = message.get('text', '').strip()
        user_id = message['from']['id']
        
        # بررسی دستور cancel
        if text.lower() == '/cancel':
            if user_id in self.user_states:
                del self.user_states[user_id]
                await self.bot.send_message(chat_id, "❌ عملیات لغو شد.", reply_markup=self.create_main_menu())
            else:
                await self.bot.send_message(chat_id, "ℹ️ هیچ عملیات فعالی برای لغو وجود ندارد.", reply_markup=self.create_main_menu())
            return
        
        # بررسی وضعیت کاربر
        if user_id in self.user_states:
            state = self.user_states[user_id]
            
            if state['state'] == 'awaiting_post_link':
                await self.process_post_link(chat_id, user_id, text)
                return
            
            elif state['state'] == 'awaiting_view_count':
                await self.process_view_count(chat_id, user_id, text)
                return
            
            elif state['state'] == 'awaiting_broadcast_message':
                await self.process_broadcast_message(chat_id, user_id, text)
                return
        
        # بررسی دستورات
        if text.startswith('/'):
            if text == '/start':
                await self.handle_start(chat_id, message['from'])
            elif text == '/fetch':
                await self.handle_fetch_online_proxies(chat_id, message['message_id'])
            elif text == '/stats':
                await self.show_stats(chat_id, message['message_id'])
            elif text.startswith('/broadcast') and user_id in ADMINS:
                message_text = text.replace('/broadcast', '').strip()
                if message_text:
                    await self.handle_broadcast_message(chat_id, message_text, message['message_id'])
                else:
                    await self.start_broadcast(chat_id, message['message_id'], user_id)
            elif text == '/admin' and user_id in ADMINS:
                await self.show_admin_panel(chat_id, message['message_id'], user_id)
            elif text == '/help':
                await self.show_help(chat_id, message['message_id'])
            elif text == '/orders':
                await self.handle_my_orders(chat_id, message['message_id'], user_id)
            else:
                await self.bot.send_message(
                    chat_id, 
                    "⚠️ دستور نامعتبر. از منو برای استفاده از ربات استفاده کنید.",
                    reply_markup=self.create_main_menu()
                )
        
        # بررسی لینک تلگرام
        elif ('t.me/' in text or text.startswith('@')) and user_id not in self.user_states:
            await self.bot.send_message(
                chat_id,
                "🔗 **لینک تلگرام دریافت شد!**\n\n"
                "برای افزایش ویو این پست، لطفاً از منوی «افزایش ویو تلگرام» استفاده کنید.",
                parse_mode='Markdown',
                reply_markup=self.create_main_menu()
            )
        
        else:
            await self.bot.send_message(
                chat_id, 
                "📩 پیام شما دریافت شد. از منو برای استفاده از ربات استفاده کنید.",
                reply_markup=self.create_main_menu()
            )
    
    async def show_stats(self, chat_id, message_id=None):
        """نمایش آمار ربات - کامل شده"""
        stats, total_proxies, unique_types, today_orders, today_completed = await get_stats()
        
        if stats:
            # محاسبه آمار اضافی
            success_rate = (stats[3] / max(1, stats[4]) * 100) if stats[4] > 0 else 0
            
            text = f"""
📊 **آمار کامل ربات**

👥 **کاربران:**
├ کل کاربران: {stats[0]:,}
└ آخرین فعالیت: {stats[5]}

🔧 **پروکسی‌ها:**
├ پردازش شده: {stats[1]:,}
├ حذف شده (تکراری): {stats[2]:,}
├ موجود در دیتابیس: {total_proxies:,}
└ انواع مختلف: {unique_types}

🎯 **ویو‌ها:**
├ کل ویو ارسال شده: {stats[3]:,}
├ کل سفارشات: {stats[4]:,}
├ نرخ موفقیت: {success_rate:.1f}%
├ سفارشات امروز: {today_orders:,}
└ تکمیل شده امروز: {today_completed:,}

📅 تاریخ: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

⚡ **ربات فعال و آماده به کار**
"""
        else:
            text = "❌ آمار یافت نشد."
        
        keyboard = self.create_keyboard([
            ("🔄 بروزرسانی", "stats"),
            ("📈 افزایش ویو", "increase_views"),
            ("🔙 منوی اصلی", "back_to_main")
        ])
        
        if message_id:
            await self.bot.edit_message_text(
                chat_id, message_id, 
                text, parse_mode='Markdown',
                reply_markup=keyboard
            )
        else:
            await self.bot.send_message(
                chat_id, text, 
                parse_mode='Markdown',
                reply_markup=keyboard
            )
    
    async def show_admin_panel(self, chat_id, message_id, user_id):
        """نمایش پنل مدیریت - کامل شده"""
        if user_id not in ADMINS:
            await self.bot.edit_message_text(chat_id, message_id, "❌ دسترسی غیرمجاز!")
            return
        
        text = """
⚙️ **پنل مدیریت پیشرفته**

🔸 **دسترسی کامل مدیر**
🔸 **امکانات ویژه مدیریتی**

🔹 **گزینه‌های موجود:**
• 📊 آمار لحظه‌ای
• 🌐 دریافت پروکسی
• 📨 پیام همگانی
• 🧹 پاکسازی دیتابیس
• 📋 لیست کاربران

لطفاً یکی از گزینه‌ها را انتخاب کنید:
"""
        
        await self.bot.edit_message_text(
            chat_id, message_id, 
            text, parse_mode='Markdown',
            reply_markup=self.create_admin_menu()
        )
    
    async def start_broadcast(self, chat_id, message_id, user_id):
        """شروع پیام همگانی"""
        if user_id not in ADMINS:
            return
        
        self.user_states[user_id] = {
            'state': 'awaiting_broadcast_message',
            'step': 1
        }
        
        text = """
📨 **ارسال پیام همگانی**

لطفاً پیام خود را ارسال کنید:

🔸 **نکات مهم:**
• پیام می‌تواند شامل متن، emoji و لینک باشد
• از Markdown برای فرمت‌دهی استفاده کنید
• برای لغو /cancel را ارسال کنید

📝 **مثال:**
```

📢 اطلاعیه مهم!

به روزرسانی ربات انجام شد.
ویژگی‌های جدید اضافه شده‌اند.

با تشکر از همراهی شما 🌟

```
"""
        
        await self.bot.edit_message_text(
            chat_id, message_id, 
            text, parse_mode='Markdown'
        )
    
    async def process_broadcast_message(self, chat_id, user_id, text):
        """پردازش پیام همگانی"""
        if user_id not in self.user_states or self.user_states[user_id]['state'] != 'awaiting_broadcast_message':
            return
        
        # پاکسازی وضعیت
        del self.user_states[user_id]
        
        # تایید پیام
        confirm_text = f"""
✅ **پیام همگانی دریافت شد!**

📝 **پیش‌نمایش پیام:**
{text[:500]}...

👥 **تعداد گیرندگان:** در حال محاسبه...

⚠️ **تأیید نهایی:**
آیا از ارسال این پیام به تمام کاربران اطمینان دارید؟
"""
        
        keyboard = self.create_keyboard([
            ("✅ بله، ارسال کن", f"confirm_broadcast_{hashlib.md5(text.encode()).hexdigest()[:10]}"),
            ("❌ خیر، لغو کن", "cancel_broadcast")
        ])
        
        await self.bot.send_message(
            chat_id, confirm_text,
            parse_mode='Markdown',
            reply_markup=keyboard
        )
    
    async def execute_broadcast(self, chat_id, user_id, message_text):
        """اجرای پیام همگانی"""
        if user_id not in ADMINS:
            return
        
        progress_msg = await self.bot.send_message(
            chat_id,
            "📨 **در حال ارسال پیام همگانی...**\n\n"
            "⏳ لطفاً صبر کنید، این عملیات ممکن است چند دقیقه طول بکشد...",
            parse_mode='Markdown'
        )
        
        try:
            # دریافت لیست کاربران
            async with db_lock:
                conn = sqlite3.connect('bot_stats.db', check_same_thread=False)
                cursor = conn.cursor()
                cursor.execute('SELECT user_id FROM users')
                users = cursor.fetchall()
                conn.close()
            
            total_users = len(users)
            success = 0
            failed = 0
            
            # ارسال پیام به هر کاربر
            for i, user in enumerate(users):
                try:
                    await self.bot.send_message(
                        user[0], 
                        f"📢 **پیام همگانی از مدیریت:**\n\n{message_text}", 
                        parse_mode='Markdown'
                    )
                    success += 1
                    
                    # گزارش پیشرفت هر 10 کاربر
                    if i % 10 == 0:
                        progress = (i / total_users * 100)
                        await self.bot.edit_message_text(
                            chat_id, progress_msg['message_id'],
                            f"📨 **در حال ارسال پیام همگانی...**\n\n"
                            f"├ ارسال شده: {i:,}/{total_users:,}\n"
                            f"├ موفق: {success:,}\n"
                            f"├ ناموفق: {failed:,}\n"
                            f"└ پیشرفت: {progress:.1f}%\n\n"
                            f"⏳ لطفاً صبر کنید...",
                            parse_mode='Markdown'
                        )
                    
                    # وقفه برای جلوگیری از محدودیت تلگرام
                    await asyncio.sleep(0.1)
                    
                except Exception as e:
                    failed += 1
                    logger.warning(f"خطا در ارسال به کاربر {user[0]}: {e}")
            
            # نمایش نتیجه نهایی
            result_text = f"""
✅ **پیام همگانی ارسال شد!**

📊 **نتایج ارسال:**
├ کل کاربران: {total_users:,}
├ موفق: {success:,} کاربر
├ ناموفق: {failed:,} کاربر
└ نرخ موفقیت: {(success/total_users*100 if total_users > 0 else 0):.1f}%

📝 **پیام ارسال شده:**
{message_text[:300]}...
"""
            
            keyboard = self.create_keyboard([
                ("📊 آمار", "stats"),
                ("⚙️ پنل مدیریت", "admin_panel"),
                ("🔙 منوی اصلی", "back_to_main")
            ])
            
            await self.bot.edit_message_text(
                chat_id, progress_msg['message_id'],
                result_text, parse_mode='Markdown',
                reply_markup=keyboard
            )
            
        except Exception as e:
            logger.error(f"خطا در ارسال پیام همگانی: {e}")
            await self.bot.edit_message_text(
                chat_id, progress_msg['message_id'],
                f"❌ **خطا در ارسال پیام همگانی!**\n\n`{str(e)[:200]}`",
                parse_mode='Markdown'
            )
    
    async def cleanup_database(self, chat_id, message_id):
        """پاکسازی دیتابیس - کامل شده"""
        progress_msg = await self.bot.edit_message_text(
            chat_id, message_id,
            "🧹 **در حال پاکسازی دیتابیس...**\n\n"
            "⏳ لطفاً صبر کنید...",
            parse_mode='Markdown'
        )
        
        try:
            async with db_lock:
                conn = sqlite3.connect('bot_stats.db', check_same_thread=False)
                cursor = conn.cursor()
                
                # گرفتن آمار قبل از پاکسازی
                cursor.execute('SELECT COUNT(*) FROM proxies')
                before_proxies = cursor.fetchone()[0]
                
                cursor.execute('SELECT COUNT(*) FROM view_logs')
                before_logs = cursor.fetchone()[0]
                
                # پاکسازی پروکسی‌های قدیمی (بیش از 7 روز)
                cursor.execute('DELETE FROM proxies WHERE date(added_date) < date("now", "-7 days")')
                deleted_proxies = cursor.rowcount
                
                # پاکسازی لاگ‌های قدیمی (بیش از 30 روز)
                cursor.execute('DELETE FROM view_logs WHERE date(timestamp) < date("now", "-30 days")')
                deleted_logs = cursor.rowcount
                
                # پاکسازی سفارشات قدیمی (بیش از 30 روز)
                cursor.execute('DELETE FROM view_orders WHERE date(start_time) < date("now", "-30 days")')
                deleted_orders = cursor.rowcount
                
                # بهینه‌سازی دیتابیس
                cursor.execute('VACUUM')
                
                conn.commit()
                
                # گرفتن آمار بعد از پاکسازی
                cursor.execute('SELECT COUNT(*) FROM proxies')
                after_proxies = cursor.fetchone()[0]
                
                cursor.execute('SELECT COUNT(*) FROM view_logs')
                after_logs = cursor.fetchone()[0]
                
                conn.close()
            
            result_text = f"""
✅ **پاکسازی دیتابیس کامل شد!**

📊 **آمار پاکسازی:**

🔸 **پروکسی‌ها:**
├ قبل: {before_proxies:,}
├ حذف شده: {deleted_proxies:,}
└ بعد: {after_proxies:,}

🔸 **لاگ‌ها:**
├ قبل: {before_logs:,}
├ حذف شده: {deleted_logs:,}
└ بعد: {after_logs:,}

🔸 **سفارشات:**
└ حذف شده: {deleted_orders:,}

💾 **فضای آزاد شده:** محاسبه شد
⚡ **دیتابیس بهینه‌سازی شد**
"""
            
            keyboard = self.create_keyboard([
                ("📊 آمار", "stats"),
                ("⚙️ پنل مدیریت", "admin_panel"),
                ("🔙 منوی اصلی", "back_to_main")
            ])
            
            await self.bot.edit_message_text(
                chat_id, progress_msg['message_id'],
                result_text, parse_mode='Markdown',
                reply_markup=keyboard
            )
            
        except Exception as e:
            logger.error(f"خطا در پاکسازی دیتابیس: {e}")
            await self.bot.edit_message_text(
                chat_id, progress_msg['message_id'],
                f"❌ **خطا در پاکسازی دیتابیس!**\n\n`{str(e)[:200]}`",
                parse_mode='Markdown'
            )
    
    async def show_user_list(self, chat_id, message_id):
        """نمایش لیست کاربران"""
        async with db_lock:
            conn = sqlite3.connect('bot_stats.db', check_same_thread=False)
            cursor = conn.cursor()
            try:
                cursor.execute('''
                    SELECT user_id, username, first_name, last_name, 
                           join_date, total_views_sent, last_active
                    FROM users 
                    ORDER BY join_date DESC
                    LIMIT 50
                ''')
                
                users = cursor.fetchall()
                
                if not users:
                    text = "👥 **هیچ کاربری ثبت نشده است.**"
                else:
                    text = f"👥 **آخرین {len(users)} کاربر:**\n\n"
                    
                    for user in users[:10]:  # فقط 10 کاربر اول
                        user_id, username, first_name, last_name, join_date, views_sent, last_active = user
                        
                        name = f"{first_name or ''} {last_name or ''}".strip() or "بدون نام"
                        username_display = f"@{username}" if username else "بدون یوزرنیم"
                        
                        text += f"""
👤 **{name}**
├ آیدی: `{user_id}`
├ یوزرنیم: {username_display}
├ ویو ارسال شده: {views_sent:,}
├ عضویت: {join_date[:10]}
└ آخرین فعالیت: {last_active[:19] if last_active else 'نامشخص'}

"""
                
                if len(users) > 10:
                    text += f"\n📋 **و {len(users)-10} کاربر دیگر...**"
                
                text += f"\n📊 **مجموع کاربران:** {len(users):,}"
                
                keyboard = self.create_keyboard([
                    ("📊 آمار کامل", "stats"),
                    ("🧹 پاکسازی", "cleanup"),
                    ("🔙 پنل مدیریت", "admin_panel")
                ])
                
                await self.bot.edit_message_text(
                    chat_id, message_id, 
                    text, parse_mode='Markdown',
                    reply_markup=keyboard
                )
                
            finally:
                conn.close()
    
    async def show_help(self, chat_id, message_id):
        """نمایش راهنما"""
        text = """
📖 **راهنمای استفاده از ربات**

🎯 **ویژگی‌های اصلی:**

1️⃣ **📄 آپلود فایل پروکسی**
   • آپلود فایل txt/csv حاوی پروکسی
   • پشتیبانی از فرمت‌های مختلف پروکسی
   • حذف خودکار تکراری‌ها

2️⃣ **🌐 دریافت پروکسی آنلاین**
   • دریافت خودکار از منابع معتبر
   • ذخیره در دیتابیس و فایل
   • گزارش پیشرفت زنده

3️⃣ **📈 افزایش ویو تلگرام**
   • افزایش ویو پست‌های تلگرام
   • استفاده از پروکسی‌های ذخیره شده
   • گزارش پیشرفت و نتایج

4️⃣ **📊 آمار ربات**
   • آمار کامل کاربران و پروکسی‌ها
   • گزارش عملکرد سیستم
   • آمار لحظه‌ای

5️⃣ **⚙️ پنل مدیریت** (فقط مدیران)
   • مدیریت کاربران
   • ارسال پیام همگانی
   • پاکسازی دیتابیس

🔸 **دستورات اصلی:**
• /start - راه‌اندازی ربات
• /stats - مشاهده آمار
• /help - نمایش این راهنما
• /cancel - لغو عملیات جاری

⚠️ **نکات مهم:**
• ربات از پروکسی‌های عمومی استفاده می‌کند
• سرعت ارسال ویو بستگی به کیفیت پروکسی‌ها دارد
• برای بهترین نتاید، پروکسی‌های با کیفیت آپلود کنید

👨‍💻 **پشتیبانی:** @Erfan138600
"""
        
        keyboard = self.create_keyboard([
            ("📄 آپلود پروکسی", "upload_proxy"),
            ("🌐 دریافت پروکسی", "fetch_online_proxies"),
            ("📈 افزایش ویو", "increase_views"),
            ("📊 آمار", "stats"),
            ("🔙 منوی اصلی", "back_to_main")
        ])
        
        await self.bot.edit_message_text(
            chat_id, message_id,
            text, parse_mode='Markdown',
            reply_markup=keyboard
        )
    
    async def cleanup_old_files(self, directory, max_age_hours=24):
        """پاکسازی فایل‌های قدیمی"""
        try:
            if not await async_os.path.exists(directory):
                return
            
            current_time = time.time()
            for filename in await async_os.listdir(directory):
                file_path = os.path.join(directory, filename)
                if await async_os.path.isfile(file_path):
                    file_age = current_time - (await async_os.stat(file_path)).st_mtime
                    if file_age > max_age_hours * 3600:
                        await async_os.remove(file_path)
                        logger.info(f"فایل قدیمی حذف شد: {file_path}")
        except Exception as e:
            logger.error(f"خطا در پاکسازی فایل‌های قدیمی: {e}")
    
    async def process_updates(self):
        """پردازش آپدیت‌ها"""
        offset = None
        
        while True:
            try:
                updates = await self.bot.get_updates(offset, timeout=30)
                
                for update in updates:
                    offset = update['update_id'] + 1
                    
                    if 'message' in update:
                        message = update['message']
                        
                        if 'document' in message:
                            await self.handle_document(message)
                        elif 'text' in message:
                            await self.handle_text(message)
                    
                    elif 'callback_query' in update:
                        callback_query = update['callback_query']
                        message = callback_query.get('message', {})
                        await self.handle_callback_query(callback_query, message)
                
                await asyncio.sleep(0.1)
                
            except Exception as e:
                logger.error(f"خطا در پردازش آپدیت: {e}")
                logger.error(traceback.format_exc())
                await asyncio.sleep(5)

# ============================
# تابع اصلی
# ============================
async def main():
    """تابع اصلی اجرای ربات"""
    # ایجاد دیتابیس
    init_db()
    
    # پاکسازی فایل‌های قدیمی در شروع
    for directory in ["proxy_files", "temp_files", "uploaded_files"]:
        if os.path.exists(directory):
            for filename in os.listdir(directory):
                file_path = os.path.join(directory, filename)
                try:
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                except:
                    pass
    
    handler = BotHandler()
    
    print("🤖 ربات فعال شد...")
    print("✅ بخش‌های کامل پیاده‌سازی شده:")
    print("   📁 آپلود و پردازش فایل پروکسی")
    print("   🌐 دریافت خودکار پروکسی از اینترنت")
    print("   📈 افزایش ویو پست‌های تلگرام (کامل)")
    print("   📊 آمار و گزارش‌های کامل")
    print("   ⚙️ پنل مدیریت پیشرفته")
    print("   📨 سیستم پیام همگانی")
    print("   🧹 پاکسازی و بهینه‌سازی دیتابیس")
    print("   📖 راهنمای کامل")
    print("   🔒 مدیریت وضعیت کاربران")
    
    try:
        await handler.process_updates()
    finally:
        await handler.bot.close()
        await handler.proxy_manager.cleanup()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 ربات متوقف شد.")
    except Exception as e:
        print(f"❌ خطای بحرانی: {e}")
        traceback.print_exc()