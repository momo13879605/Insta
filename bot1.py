import os
import sqlite3
import asyncio
import aiohttp
import aiofiles
import requests
import re
from datetime import datetime
from urllib.parse import urlparse
from typing import Dict, List, Optional, Tuple, Set
import json
import random
from fake_useragent import UserAgent
from concurrent.futures import ThreadPoolExecutor
import warnings
import string
import time

# ============================
# تنظیمات اولیه
# ============================
TOKEN = '7880725906:AAFOl9it7XDtUY6-phnTc90tXq2rqFcME8M'
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB
ADMINS = [5914346958]  # جایگزین کنید با user_id ادمین‌ها
MAX_WORKERS = 500  # حداکثر Thread همزمان
REQUEST_TIMEOUT = 15  # زمان تایم‌اوت درخواست‌ها
PROXY_SOURCES_TIMEOUT = 10  # تایم‌اوت برای دریافت پروکسی‌ها

# URLهای API تلگرام
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TOKEN}"

# لیست منابع پروکسی (شامل منابع اضافه شده)
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
# دیتابیس SQLite
# ============================
def init_db():
    """ایجاد یا اتصال به دیتابیس SQLite با جداول پیشرفته"""
    conn = sqlite3.connect('bot_stats.db')
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
    
    # جدول سفارشات
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            order_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            channel TEXT,
            post_id TEXT,
            proxy_count INTEGER,
            views_sent INTEGER,
            status TEXT DEFAULT 'pending',
            start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            end_time TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    
    # جدول پروکسی‌ها
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS proxies (
            proxy_id INTEGER PRIMARY KEY AUTOINCREMENT,
            proxy_address TEXT UNIQUE,
            proxy_type TEXT,
            country TEXT,
            speed REAL,
            last_check TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active INTEGER DEFAULT 1
        )
    ''')
    
    # جدول منابع پروکسی
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS proxy_sources (
            source_id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_url TEXT UNIQUE,
            last_fetch TIMESTAMP,
            success_count INTEGER DEFAULT 0,
            fail_count INTEGER DEFAULT 0
        )
    ''')
    
    # ایجاد رکورد اولیه در stats اگر وجود نداشت
    cursor.execute('INSERT OR IGNORE INTO stats (id) VALUES (1)')
    
    conn.commit()
    conn.close()

# ============================
# توابع دیتابیس (اصلاح SQL Injection)
# ============================
def add_user(user_id, username="", first_name="", last_name=""):
    """افزودن کاربر جدید به دیتابیس"""
    conn = sqlite3.connect('bot_stats.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR IGNORE INTO users 
        (user_id, username, first_name, last_name) 
        VALUES (?, ?, ?, ?)
    ''', (user_id, username, first_name, last_name))
    cursor.execute('UPDATE stats SET total_users = (SELECT COUNT(*) FROM users) WHERE id = 1')
    conn.commit()
    conn.close()

def increment_stats(field, value=1):
    """افزایش آمار کلی - با امنیت در برابر SQL Injection"""
    # لیست فیلدهای مجاز
    allowed_fields = {
        'total_users',
        'total_proxies_processed', 
        'total_proxies_deleted',
        'total_views_sent',
        'total_orders'
    }
    
    if field not in allowed_fields:
        raise ValueError(f"فیلد غیرمجاز: {field}")
    
    conn = sqlite3.connect('bot_stats.db')
    cursor = conn.cursor()
    cursor.execute(f'UPDATE stats SET {field} = {field} + ? WHERE id = 1', (value,))
    conn.commit()
    conn.close()

def add_order(user_id, channel, post_id, proxy_count):
    """افزودن سفارش جدید"""
    conn = sqlite3.connect('bot_stats.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO orders (user_id, channel, post_id, proxy_count)
        VALUES (?, ?, ?, ?)
    ''', (user_id, channel, post_id, proxy_count))
    order_id = cursor.lastrowid
    conn.commit()
    conn.close()
    increment_stats('total_orders')
    return order_id

def update_order(order_id, views_sent, status='completed'):
    """به‌روزرسانی سفارش"""
    conn = sqlite3.connect('bot_stats.db')
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE orders 
        SET views_sent = ?, status = ?, end_time = CURRENT_TIMESTAMP
        WHERE order_id = ?
    ''', (views_sent, status, order_id))
    conn.commit()
    conn.close()

def get_stats():
    """دریافت آمار کامل"""
    conn = sqlite3.connect('bot_stats.db')
    cursor = conn.cursor()
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
    
    # آمار سفارشات امروز
    cursor.execute('''
        SELECT COUNT(*) FROM orders 
        WHERE DATE(start_time) = DATE('now')
    ''')
    today_orders = cursor.fetchone()[0]
    
    conn.close()
    return stats, today_orders

# ============================
# کلاس دریافت پروکسی از منابع آنلاین با گزارش پیشرفت
# ============================
class OnlineProxyFetcher:
    def __init__(self):
        self.ua = UserAgent()
        self.all_proxies = set()
        self.verified_proxies = []
        self.session = None
        self.current_progress = 0
        self.current_stage = ""
        
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
    
    async def fetch_from_source(self, source_url):
        """دریافت پروکسی‌ها از یک منبع"""
        try:
            if not self.session:
                await self.initialize_session()
            
            async with self.session.get(source_url, ssl=False) as response:
                if response.status == 200:
                    text = await response.text()
                    # استخراج پروکسی‌ها با الگوهای مختلف
                    proxies = set()
                    
                    # الگوهای مختلف پروکسی
                    patterns = [
                        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d{2,5}',  # IP:Port
                        r'http[s]?://\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d{2,5}',  # http://IP:Port
                        r'socks[4-5]?://\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d{2,5}',  # socks://IP:Port
                        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d{2,5}:\w+:\w+',  # IP:Port:User:Pass
                        r'http[s]?://\w+:\w+@\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d{2,5}',  # http://user:pass@IP:Port
                    ]
                    
                    for pattern in patterns:
                        found = re.findall(pattern, text)
                        proxies.update(found)
                    
                    return list(proxies), len(proxies)
                    
        except Exception as e:
            print(f"❌ خطا در دریافت از {source_url}: {e}")
        
        return [], 0
    
    async def fetch_all_sources(self, update_progress_callback=None):
        """دریافت پروکسی‌ها از تمام منابع با گزارش پیشرفت"""
        total_sources = len(PROXY_SOURCES)
        current_source = 0
        total_found = 0
        
        # مرحله 1: شروع دریافت
        if update_progress_callback:
            await update_progress_callback(
                stage="دریافت از منابع",
                progress=0,
                current=0,
                total=total_sources,
                found=0
            )
        
        tasks = []
        
        # ایجاد تسک‌ها برای تمام منابع
        for source in PROXY_SOURCES:
            tasks.append(self.fetch_from_source(source))
        
        # اجرای همزمان تمام تسک‌ها
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # پردازش نتایج
        for i, result in enumerate(results):
            current_source += 1
            progress_percent = int((current_source / total_sources) * 100)
            
            if isinstance(result, Exception):
                print(f"❌ خطا در منبع {PROXY_SOURCES[i].split('/')[2]}: {result}")
            else:
                proxies, count = result
                if proxies:
                    self.all_proxies.update(proxies)
                    total_found += count
            
            # آپدیت پیشرفت
            if update_progress_callback:
                await update_progress_callback(
                    stage="دریافت از منابع",
                    progress=progress_percent,
                    current=current_source,
                    total=total_sources,
                    found=len(self.all_proxies)
                )
            
            await asyncio.sleep(0.1)  # وقفه کوتاه
        
        return list(self.all_proxies)
    
    def normalize_proxy(self, proxy_line):
        """نرمال‌سازی پروکسی به فرمت استاندارد"""
        proxy_line = proxy_line.strip()
        if not proxy_line:
            return None
        
        # اگر پروکسی بدون پروتکل بود، پروتکل http اضافه کن
        if '://' not in proxy_line:
            # بررسی فرمت user:pass@host:port
            if '@' in proxy_line:
                return f"http://{proxy_line}"
            # بررسی فرمت host:port:user:pass
            elif proxy_line.count(':') == 3:
                parts = proxy_line.split(':')
                if len(parts) == 4:
                    host, port, user, pwd = parts
                    return f"http://{user}:{pwd}@{host}:{port}"
            # فرمت ساده host:port
            elif ':' in proxy_line:
                return f"http://{proxy_line}"
        
        return proxy_line
    
    async def verify_proxy_async(self, proxy_url):
        """تأیید پروکسی به صورت ناهمزمان"""
        try:
            # نرمال‌سازی پروکسی
            normalized_proxy = self.normalize_proxy(proxy_url)
            if not normalized_proxy:
                return None
            
            # تشخیص نوع پروکسی
            if 'socks5://' in normalized_proxy:
                proxy_type = 'socks5'
            elif 'socks4://' in normalized_proxy:
                proxy_type = 'socks4'
            elif 'https://' in normalized_proxy:
                proxy_type = 'https'
            else:
                proxy_type = 'http'
            
            # تست پروکسی
            connector = aiohttp.TCPConnector(ssl=False)
            
            async with aiohttp.ClientSession(
                connector=connector,
                headers={'User-Agent': self.ua.random}
            ) as session:
                
                # تنظیم پروکسی
                session.proxy = normalized_proxy
                
                # ارسال درخواست تست
                async with session.get(
                    'http://httpbin.org/ip',
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    
                    if response.status == 200:
                        data = await response.json()
                        if 'origin' in data:
                            return {
                                'url': normalized_proxy,
                                'type': proxy_type,
                                'working': True
                            }
        
        except Exception as e:
            pass
        
        return None
    
    async def verify_proxies_batch(self, proxies, update_progress_callback=None, batch_size=50):
        """تأیید دسته‌ای پروکسی‌ها با گزارش پیشرفت"""
        verified_proxies = []
        total = len(proxies)
        processed = 0
        last_update_time = 0
        
        # مرحله 2: شروع تأیید
        if update_progress_callback:
            await update_progress_callback(
                stage="تأیید سلامت پروکسی‌ها",
                progress=0,
                current=0,
                total=total,
                verified=0
            )
        
        # پردازش دسته‌ای
        for i in range(0, total, batch_size):
            batch = proxies[i:i+batch_size]
            tasks = []
            
            for proxy in batch:
                tasks.append(self.verify_proxy_async(proxy))
            
            # اجرای همزمان
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # پردازش نتایج
            for result in results:
                if isinstance(result, Exception):
                    continue
                if result and result['working']:
                    verified_proxies.append(result)
            
            processed += len(batch)
            progress = int((processed / total) * 100)
            
            # آپدیت پیشرفت (هر 5 درصد یا هر 5 ثانیه)
            current_time = time.time()
            if update_progress_callback and (progress % 5 == 0 or current_time - last_update_time > 5):
                last_update_time = current_time
                await update_progress_callback(
                    stage="تأیید سلامت پروکسی‌ها",
                    progress=progress,
                    current=processed,
                    total=total,
                    verified=len(verified_proxies)
                )
            
            await asyncio.sleep(0.5)  # وقفه برای جلوگیری از overload
        
        # مرحله 3: تکمیل تأیید
        if update_progress_callback:
            await update_progress_callback(
                stage="تأیید سلامت پروکسی‌ها",
                progress=100,
                current=total,
                total=total,
                verified=len(verified_proxies)
            )
        
        return verified_proxies
    
    def classify_proxy(self, proxy_url):
        """طبقه‌بندی پروکسی بر اساس ISP"""
        proxy_lower = proxy_url.lower()
        
        # تشخیص کشور/ISP بر اساس IP یا domain
        iran_keywords = ['ir', 'iran', 'mci', 'mtn', 'rightel', 'tci']
        for keyword in iran_keywords:
            if keyword in proxy_lower:
                return 'iran'
        
        # تشخیص تلگرام
        if 'telegram' in proxy_lower or 't.me' in proxy_lower or 'tg' in proxy_lower:
            return 'telegram'
        
        # تشخیص نوع پروکسی
        if 'socks5' in proxy_lower:
            return 'socks5'
        elif 'socks4' in proxy_lower:
            return 'socks4'
        elif 'https' in proxy_lower:
            return 'https'
        
        return 'http'
    
    async def fetch_and_verify_proxies(self, update_progress_callback=None, max_proxies=1000):
        """دریافت و تأیید پروکسی‌ها با گزارش پیشرفت کامل"""
        try:
            # مرحله 1: دریافت پروکسی‌ها از منابع
            all_proxies = await self.fetch_all_sources(update_progress_callback)
            
            if not all_proxies:
                if update_progress_callback:
                    await update_progress_callback(
                        stage="خطا",
                        progress=0,
                        current=0,
                        total=0,
                        found=0,
                        error="هیچ پروکسی یافت نشد!"
                    )
                return {}
            
            # مرحله 2: تأیید پروکسی‌ها
            verified = await self.verify_proxies_batch(
                all_proxies[:max_proxies*2],
                update_progress_callback
            )
            
            # مرحله 3: دسته‌بندی پروکسی‌ها
            categorized_proxies = {
                'http': [], 'https': [], 'socks4': [], 'socks5': [],
                'iran': [], 'telegram': [], 'all': []
            }
            
            for proxy_info in verified[:max_proxies]:
                proxy_type = proxy_info['type']
                proxy_url = proxy_info['url']
                
                # اضافه به دسته نوع پروکسی
                if proxy_type in categorized_proxies:
                    categorized_proxies[proxy_type].append(proxy_url)
                
                # اضافه به دسته ISP/کشور
                isp_type = self.classify_proxy(proxy_url)
                if isp_type in categorized_proxies:
                    categorized_proxies[isp_type].append(proxy_url)
                
                # اضافه به لیست همه
                categorized_proxies['all'].append(proxy_url)
            
            # مرحله 4: ذخیره در فایل با aiofiles (غیرمسدودکننده)
            await self.save_categorized_proxies(categorized_proxies)
            
            # مرحله 5: تکمیل
            if update_progress_callback:
                await update_progress_callback(
                    stage="تکمیل",
                    progress=100,
                    current=len(verified),
                    total=len(verified),
                    verified=len(verified),
                    categorized=len(categorized_proxies['all'])
                )
            
            return categorized_proxies
            
        except Exception as e:
            if update_progress_callback:
                await update_progress_callback(
                    stage="خطا",
                    progress=0,
                    current=0,
                    total=0,
                    error=str(e)
                )
            print(f"❌ خطا در دریافت پروکسی‌ها: {e}")
            return {}
    
    async def save_categorized_proxies(self, categorized_proxies):
        """ذخیره پروکسی‌ها در فایل‌های جداگانه با aiofiles"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        for category, proxies in categorized_proxies.items():
            if proxies and category != 'all':
                filename = f"proxies_{category}_{timestamp}.txt"
                async with aiofiles.open(filename, 'w', encoding='utf-8') as f:
                    await f.write('\n'.join(proxies))
                print(f"💾 {len(proxies)} پروکسی {category} در {filename} ذخیره شد")
        
        # ذخیره همه پروکسی‌ها در یک فایل
        all_proxies = categorized_proxies.get('all', [])
        if all_proxies:
            filename = f"all_proxies_{timestamp}.txt"
            async with aiofiles.open(filename, 'w', encoding='utf-8') as f:
                await f.write('\n'.join(all_proxies))
            print(f"📁 همه پروکسی‌ها ({len(all_proxies)}) در {filename} ذخیره شد")

# ============================
# کلاس مدیریت پروکسی پیشرفته
# ============================
class AdvancedProxyManager:
    def __init__(self):
        self.ua = UserAgent()
        self.online_fetcher = OnlineProxyFetcher()
        self.categorized_proxies = {}
    
    async def update_progress_in_telegram(self, bot, chat_id, message_id, **kwargs):
        """آپدیت پیشرفت در پیام تلگرام"""
        stage = kwargs.get('stage', '')
        progress = kwargs.get('progress', 0)
        current = kwargs.get('current', 0)
        total = kwargs.get('total', 0)
        found = kwargs.get('found', 0)
        verified = kwargs.get('verified', 0)
        categorized = kwargs.get('categorized', 0)
        error = kwargs.get('error', '')
        
        # ایجاد متن پیشرفت
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
        elif stage == "تأیید سلامت پروکسی‌ها":
            text = f"""
🔍 **در حال تأیید سلامت پروکسی‌ها...**

📋 **مرحله:** {stage}
{progress_bar}
📊 **پیشرفت:** {progress}%

✅ پروکسی‌های تأیید شده: {verified}/{current}
📦 کل پروکسی‌ها برای بررسی: {total}

⏳ این مرحله ممکن است چند دقیقه طول بکشد...
"""
        elif stage == "تکمیل":
            text = f"""
✅ **دریافت پروکسی‌ها با موفقیت کامل شد!**

🎉 **عملیات با موفقیت به پایان رسید**
📦 پروکسی‌های نهایی: {categorized}

📊 **در حال ذخیره‌سازی در فایل...**
⏳ چند لحظه صبر کنید...
"""
        else:
            text = f"""
🔄 **در حال پردازش...**

📋 **مرحله:** {stage}
{progress_bar}
📊 **پیشرفت:** {progress}%

⏳ لطفاً صبر کنید...
"""
        
        # آپدیت پیام
        await bot.edit_message_text(chat_id, message_id, text, parse_mode='Markdown')
    
    def _create_progress_bar(self, percentage, length=20):
        """ایجاد نوار پیشرفت"""
        filled_length = int(length * percentage // 100)
        bar = '█' * filled_length + '░' * (length - filled_length)
        return f"[{bar}]"
    
    async def get_proxies(self, source_type='online', max_proxies=500, bot=None, chat_id=None, message_id=None):
        """دریافت پروکسی‌ها از منابع مختلف با گزارش پیشرفت"""
        
        if source_type == 'online':
            print("🌍 در حال دریافت پروکسی‌ها از اینترنت...")
            
            # تابع callback برای آپدیت پیشرفت
            async def update_callback(**kwargs):
                if bot and chat_id and message_id:
                    await self.update_progress_in_telegram(bot, chat_id, message_id, **kwargs)
            
            self.categorized_proxies = await self.online_fetcher.fetch_and_verify_proxies(
                update_progress_callback=update_callback,
                max_proxies=max_proxies
            )
            return self.categorized_proxies
        else:
            print("❌ نوع منبع پشتیبانی نمی‌شود")
            return {}
    
    def get_proxy_count(self):
        """دریافت تعداد پروکسی‌های دسته‌بندی شده"""
        counts = {}
        total = 0
        
        for category, proxies in self.categorized_proxies.items():
            count = len(proxies)
            counts[category] = count
            total += count
        
        counts['total'] = total
        return counts
    
    async def save_all_proxies(self, filename="all_proxies_combined.txt"):
        """ذخیره همه پروکسی‌ها در یک فایل با aiofiles"""
        all_proxies = []
        
        for category, proxies in self.categorized_proxies.items():
            if category != 'all':  # از تکرار جلوگیری کن
                all_proxies.extend(proxies)
        
        # حذف duplicates
        unique_proxies = list(set(all_proxies))
        
        if unique_proxies:
            async with aiofiles.open(filename, 'w', encoding='utf-8') as f:
                await f.write('\n'.join(unique_proxies))
            
            print(f"💾 {len(unique_proxies)} پروکسی منحصربه‌فرد در {filename} ذخیره شد")
            return filename
        
        return None

# ============================
# کلاس HTTP Client با aiohttp
# ============================
class AsyncHTTPClient:
    def __init__(self):
        self.ua = UserAgent()
        self.timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
    
    async def make_request(self, method: str, url: str, **kwargs) -> Optional[aiohttp.ClientResponse]:
        """ایجاد درخواست HTTP ناهمزمان"""
        headers = kwargs.get('headers', {})
        if 'User-Agent' not in headers:
            headers['User-Agent'] = self.ua.random
        
        kwargs['headers'] = headers
        kwargs['timeout'] = self.timeout
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.request(method, url, **kwargs) as response:
                    return response
        except Exception as e:
            print(f"❌ خطا در درخواست HTTP: {e}")
            return None

# ============================
# کلاس ثبت ویو تلگرام با aiohttp
# ============================
class TelegramViewSender:
    def __init__(self):
        self.ua = UserAgent()
        
    async def fetch_post_data(self, channel, post, proxy=None):
        """دریافت اطلاعات پست تلگرام"""
        try:
            url = f'https://t.me/{channel}/{post}?embed=1'
            headers = {
                'User-Agent': self.ua.random,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'DNT': '1',
                'Upgrade-Insecure-Requests': '1',
            }
            
            connector = None
            if proxy:
                connector = aiohttp.TCPConnector(ssl=False)
            
            async with aiohttp.ClientSession(connector=connector) as session:
                if proxy:
                    session.proxy = proxy
                
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)) as response:
                    if response.status != 200:
                        return None
                    
                    html_content = await response.text()
                    
                    # استخراج کلید از HTML
                    if 'data-view="' in html_content:
                        key = html_content.split('data-view="')[1].split('"')[0]
                    else:
                        # تلاش با regex
                        import re
                        match = re.search(r'data-view="([^"]+)"', html_content)
                        key = match.group(1) if match else None
                    
                    # استخراج کوکی
                    cookies = response.cookies
                    cookie_str = ""
                    for cookie in cookies:
                        cookie_str += f"{cookie.key}={cookie.value}; "
                    
                    if key and cookie_str:
                        return {
                            'key': key, 
                            'cookie': cookie_str.strip(), 
                            'channel': channel, 
                            'post': post
                        }
                    
        except Exception as e:
            print(f"❌ خطا در دریافت داده‌ها: {e}")
        
        return None
    
    async def send_view_async(self, post_data, proxy=None):
        """ارسال ویو به پست"""
        try:
            url = f'https://t.me/v/?views={post_data["key"]}'
            headers = {
                'User-Agent': self.ua.random,
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.5',
                'X-Requested-With': 'XMLHttpRequest',
                'Connection': 'keep-alive',
                'Referer': f'https://t.me/{post_data["channel"]}/{post_data["post"]}?embed=1',
                'Cookie': post_data['cookie'],
            }
            
            connector = None
            if proxy:
                connector = aiohttp.TCPConnector(ssl=False)
            
            async with aiohttp.ClientSession(connector=connector) as session:
                if proxy:
                    session.proxy = proxy
                
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)) as response:
                    return response.status == 200
                    
        except Exception as e:
            print(f"❌ خطا در ارسال ویو: {e}")
        
        return False
    
    async def process_batch_async(self, channel, post, proxy_list, callback=None):
        """پردازش دسته‌ای با پروکسی‌ها"""
        success_count = 0
        
        # دریافت اطلاعات پست یک بار
        post_data = await self.fetch_post_data(channel, post)
        if not post_data:
            return 0
        
        total = len(proxy_list)
        
        # ایجاد تسک‌ها
        tasks = []
        for i, proxy in enumerate(proxy_list):
            task = self.send_view_task(post_data, proxy)
            tasks.append((i, task))
            
            # گزارش پیشرفت
            if callback and i % 10 == 0:
                progress = int((i / total) * 100)
                callback(progress, i, total)
        
        # اجرای همه تسک‌ها
        results = []
        for i, task in tasks:
            try:
                result = await task
                results.append((i, result))
            except:
                results.append((i, False))
            
            # گزارش پیشرفت
            if callback and i % 10 == 0:
                progress = int((i / total) * 100)
                callback(progress, i, total)
        
        # شمارش موفقیت‌ها
        for i, result in results:
            if result:
                success_count += 1
        
        return success_count
    
    async def send_view_task(self, post_data, proxy):
        """تسک ارسال ویو"""
        return await self.send_view_async(post_data, proxy)

# ============================
# کلاس ربات تلگرام با aiohttp (اصلاح شده)
# ============================
class TelegramBot:
    def __init__(self):
        self.token = TOKEN
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.proxy_manager = AdvancedProxyManager()
        self.view_sender = TelegramViewSender()
        
    async def send_message(self, chat_id, text, parse_mode=None, reply_markup=None):
        """ارسال پیام"""
        url = f"{self.base_url}/sendMessage"
        
        payload = {
            'chat_id': chat_id,
            'text': text
        }
        
        if parse_mode:
            payload['parse_mode'] = parse_mode
        
        if reply_markup:
            payload['reply_markup'] = json.dumps(reply_markup)
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get('result', {})
        
        return None
    
    async def send_document(self, chat_id, document_path, caption=None):
        """ارسال فایل - اصلاح شده"""
        url = f"{self.base_url}/sendDocument"
        
        data = aiohttp.FormData()
        data.add_field('chat_id', str(chat_id))
        
        if caption:
            data.add_field('caption', caption)
            
        # فایل باید در حین ارسال باز بماند
        try:
            with open(document_path, 'rb') as file:
                data.add_field('document', file, filename=os.path.basename(document_path))
                
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, data=data) as response:
                        if response.status == 200:
                            return await response.json()
                        else:
                            print(f"Error sending document: {await response.text()}")
        except Exception as e:
            print(f"File upload error: {e}")
        
        return None
    
    async def edit_message_text(self, chat_id, message_id, text, parse_mode=None):
        """ویرایش پیام"""
        url = f"{self.base_url}/editMessageText"
        
        payload = {
            'chat_id': chat_id,
            'message_id': message_id,
            'text': text
        }
        
        if parse_mode:
            payload['parse_mode'] = parse_mode
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    return await response.json()
        
        return None
    
    async def answer_callback_query(self, callback_query_id, text=None, show_alert=False):
        """پاسخ به کوئری callback"""
        url = f"{self.base_url}/answerCallbackQuery"
        
        payload = {
            'callback_query_id': callback_query_id,
            'show_alert': show_alert
        }
        
        if text:
            payload['text'] = text
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as response:
                return response.status == 200
    
    async def get_updates(self, offset=None, timeout=30):
        """دریافت آپدیت‌ها"""
        url = f"{self.base_url}/getUpdates"
        
        params = {
            'timeout': timeout
        }
        
        if offset:
            params['offset'] = offset
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get('result', [])
        
        return []
    
    async def set_webhook(self, url):
        """تنظیم webhook"""
        webhook_url = f"{self.base_url}/setWebhook"
        
        payload = {
            'url': url
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=payload) as response:
                return response.status == 200

# ============================
# توابع اصلی ربات
# ============================
class BotHandler:
    def __init__(self):
        self.bot = TelegramBot()
        self.proxy_manager = AdvancedProxyManager()
        self.view_sender = TelegramViewSender()
        
    def create_keyboard(self, buttons):
        """ایجاد صفحه کلید شیشه‌ای"""
        keyboard = []
        for row in buttons:
            keyboard_row = []
            for button in row:
                if isinstance(button, tuple):
                    text, callback_data = button
                    keyboard_row.append({"text": text, "callback_data": callback_data})
                else:
                    keyboard_row.append({"text": button, "callback_data": button})
            keyboard.append(keyboard_row)
        
        return {"inline_keyboard": keyboard}
    
    async def handle_start(self, chat_id, user):
        """مدیریت دستور /start"""
        add_user(user['id'], user.get('username', ''), user.get('first_name', ''), user.get('last_name', ''))
        
        keyboard = self.create_keyboard([
            [("📄 آپلود فایل پروکسی", "upload_proxy")],
            [("🌐 دریافت پروکسی آنلاین", "fetch_online_proxies")],
            [("🔗 ارسال لینک تلگرام", "upload_link")],
            [("📊 آمار ربات", "stats")],
            [("⚙️ پنل مدیریت", "admin_panel")]
        ])
        
        welcome_text = """
🤖 **ربات حرفه‌ای چکر پروکسی و افزایش ویو تلگرام**

🔥 **ویژگی جدید: دریافت خودکار پروکسی از اینترنت!**
• دریافت از 30+ منبع معتبر
• تأیید خودکار سلامت پروکسی‌ها
• گزارش پیشرفت زنده در ربات
• طبقه‌بندی پروکسی بر اساس ISP
• ذخیره خودکار در فایل‌های مختلف

🔹 **امکانات اصلی:**
• چک کردن پروکسی‌های HTTP/HTTPS/SOCKS4/SOCKS5
• افزایش ویو پست‌های تلگرام
• پنل مدیریت پیشرفته
• آمار لحظه‌ای

🔹 **نحوه استفاده:**
1️⃣ ابتدا پروکسی دریافت کنید (آپلود یا دریافت آنلاین)
2️⃣ سپس لینک پست تلگرام را ارسال کنید
3️⃣ عملیات به صورت خودکار شروع می‌شود

👨‍💻 **توسعه‌دهنده:** @Erfan138600
"""
        
        await self.bot.send_message(chat_id, welcome_text, parse_mode='Markdown', reply_markup=keyboard)
    
    async def handle_fetch_online_proxies(self, chat_id, message_id):
        """دریافت پروکسی‌ها از منابع آنلاین با گزارش پیشرفت"""
        # ارسال پیام اولیه
        initial_text = """
🌐 **شروع دریافت پروکسی‌ها از اینترنت...**

⏳ در حال اتصال به منابع...
📋 **مرحله:** آماده‌سازی
[░░░░░░░░░░░░░░░░░░░░] 0%

📊 **لطفاً صبر کنید، این عملیات ممکن است چند دقیقه طول بکشد...**
"""
        
        progress_msg = await self.bot.send_message(chat_id, initial_text, parse_mode='Markdown')
        
        try:
            # دریافت پروکسی‌ها با گزارش پیشرفت
            proxies = await self.proxy_manager.get_proxies(
                'online', 
                500,
                bot=self.bot,
                chat_id=chat_id,
                message_id=progress_msg['message_id']
            )
            
            if not proxies:
                final_text = """
❌ **دریافت پروکسی‌ها ناموفق بود!**

⚠️ **خطا:** هیچ پروکسی سالمی یافت نشد!

🔧 **راه‌حل‌های ممکن:**
1️⃣ اتصال اینترنت خود را بررسی کنید
2️⃣ بعداً دوباره تلاش کنید
3️⃣ از فایل پروکسی آپلود شده استفاده کنید

📊 برای دریافت مجدد روی «دریافت پروکسی آنلاین» کلیک کنید.
"""
                await self.bot.edit_message_text(
                    chat_id, 
                    progress_msg['message_id'], 
                    final_text, 
                    parse_mode='Markdown'
                )
                return
            
            # نمایش آمار نهایی
            counts = self.proxy_manager.get_proxy_count()
            
            stats_text = f"""
✅ **دریافت پروکسی‌ها با موفقیت کامل شد!**

🎉 **عملیات با موفقیت به پایان رسید**

📊 **آمار پروکسی‌های دریافتی:**

🔸 **بر اساس نوع:**
├ HTTP: {counts.get('http', 0)} پروکسی
├ HTTPS: {counts.get('https', 0)} پروکسی
├ SOCKS4: {counts.get('socks4', 0)} پروکسی
└ SOCKS5: {counts.get('socks5', 0)} پروکسی

🔸 **بر اساس ISP/منطقه:**
├ ایران: {counts.get('iran', 0)} پروکسی
└ تلگرام: {counts.get('telegram', 0)} پروکسی

📈 **مجموع: {counts.get('total', 0)} پروکسی سالم**

💾 پروکسی‌ها به طور خودکار در فایل‌های txt ذخیره شدند.

📁 **در حال ارسال فایل پروکسی‌ها...**
"""
            
            await self.bot.edit_message_text(
                chat_id, 
                progress_msg['message_id'], 
                stats_text, 
                parse_mode='Markdown'
            )
            
            # ارسال فایل ترکیبی
            combined_file = await self.proxy_manager.save_all_proxies()
            if combined_file and os.path.exists(combined_file):
                await self.bot.send_document(
                    chat_id, 
                    combined_file, 
                    caption="📁 **فایل حاوی همه پروکسی‌های سالم**\n\n✅ آماده استفاده برای افزایش ویو!"
                )
                
                # حذف فایل موقت
                await asyncio.sleep(30)
                try:
                    os.remove(combined_file)
                except:
                    pass
            
        except Exception as e:
            error_text = f"""
❌ **خطا در دریافت پروکسی‌ها!**

⚠️ **خطای فنی:** `{str(e)}`

🔧 **علت احتمالی:**
• مشکل اتصال اینترنت
• محدودیت سرور
• مشکل در منابع پروکسی

📊 لطفاً بعداً دوباره تلاش کنید یا از فایل پروکسی آپلود شده استفاده کنید.
"""
            await self.bot.edit_message_text(
                chat_id, 
                progress_msg['message_id'], 
                error_text, 
                parse_mode='Markdown'
            )
    
    async def handle_callback_query(self, callback_query, message):
        """مدیریت کلیک روی دکمه‌ها - اصلاح شده"""
        data = callback_query.get('data')
        chat_id = message['chat']['id']
        message_id = message['message_id']
        user_id = callback_query['from']['id']
        
        await self.bot.answer_callback_query(callback_query['id'])
        
        if data == 'upload_proxy':
            text = (
                "📁 لطفاً فایل txt حاوی پروکسی‌ها را ارسال کنید.\n\n"
                "💡 **فرمت‌های پشتیبانی شده:**\n"
                "• http://user:pass@host:port\n"
                "• https://host:port\n"
                "• socks4://host:port\n"
                "• socks5://host:port\n"
                "• host:port:user:pass\n"
                "• host:port\n"
                "\n⚠️ حداکثر حجم فایل: 20 مگابایت"
            )
            await self.bot.edit_message_text(chat_id, message_id, text)
            
        elif data == 'fetch_online_proxies':
            await self.handle_fetch_online_proxies(chat_id, message_id)
            
        elif data == 'upload_link':
            text = "🔗 لطفاً لینک پست تلگرام را ارسال کنید:\n\nمثال: https://t.me/channel/123"
            await self.bot.edit_message_text(chat_id, message_id, text)
            
        elif data == 'stats':
            await self.show_stats(chat_id, message_id)
            
        elif data == 'admin_panel':
            await self.show_admin_panel(chat_id, message_id, user_id)

        # --- بخش‌های اضافه شده برای دکمه‌های ادمین ---
        elif data == 'back_to_main':
            # بازگشت به منوی اصلی
            await self.handle_start(chat_id, {'id': user_id, 'first_name': ''})
            
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
    
    async def handle_document(self, message):
        """مدیریت دریافت فایل"""
        chat_id = message['chat']['id']
        document = message.get('document', {})
        
        if not document:
            await self.bot.send_message(chat_id, "❌ لطفاً یک فایل ارسال کنید.")
            return
        
        # بررسی حجم فایل
        if document.get('file_size', 0) > MAX_FILE_SIZE:
            await self.bot.send_message(chat_id, "❌ حجم فایل بیشتر از 20 مگابایت است.")
            return
        
        # بررسی فرمت فایل
        file_name = document.get('file_name', '')
        if not file_name.endswith('.txt'):
            await self.bot.send_message(chat_id, "❌ فقط فایل‌های txt پشتیبانی می‌شوند.")
            return
        
        await self.bot.send_message(chat_id, "📥 در حال دانلود فایل...")
        
        # اینجا باید فایل دانلود شود و پردازش شود
        await self.bot.send_message(chat_id, "✅ فایل دریافت شد. این قابلیت نیاز به پیاده‌سازی کامل‌تر دارد.")
    
    async def handle_text(self, message):
        """مدیریت دریافت متن"""
        chat_id = message['chat']['id']
        text = message.get('text', '').strip()
        
        if text.startswith('/'):
            if text == '/start':
                await self.handle_start(chat_id, message['from'])
            elif text == '/fetch':
                # دریافت پیام فعلی برای آپدیت
                await self.handle_fetch_online_proxies(chat_id, message['message_id'])
        elif 't.me/' in text:
            await self.bot.send_message(chat_id, f"🔗 لینک دریافت شد: {text}\n\nاین قابلیت نیاز به پیاده‌سازی کامل‌تر دارد.")
        else:
            await self.bot.send_message(chat_id, "پیام شما دریافت شد.")
    
    async def show_stats(self, chat_id, message_id):
        """نمایش آمار ربات"""
        stats, today_orders = get_stats()
        
        if stats:
            text = f"""
📊 **آمار کامل ربات:**

👥 **کاربران:**
├ کل کاربران: {stats[0]}
└ فعال امروز: {today_orders}

🔧 **پروکسی‌ها:**
├ پردازش شده: {stats[1]}
└ حذف شده: {stats[2]}

🎯 **ویو‌ها:**
├ کل ویو ارسال شده: {stats[3]}
└ سفارشات: {stats[4]}

🕒 آخرین فعالیت: {stats[5]}
📅 تاریخ: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        else:
            text = "❌ آمار یافت نشد."
        
        await self.bot.edit_message_text(chat_id, message_id, text, parse_mode='Markdown')
    
    async def show_admin_panel(self, chat_id, message_id, user_id):
        """نمایش پنل مدیریت"""
        if user_id not in ADMINS:
            await self.bot.edit_message_text(chat_id, message_id, "❌ دسترسی غیرمجاز!")
            return
        
        keyboard = self.create_keyboard([
            [("📊 آمار لحظه‌ای", "live_stats")],
            [("🌐 دریافت پروکسی", "admin_fetch_proxies")],
            [("📨 پیام همگانی", "broadcast")],
            [("🧹 پاکسازی دیتابیس", "cleanup")],
            [("🔙 بازگشت", "back_to_main")]
        ])
        
        text = "⚙️ **پنل مدیریت پیشرفته**\n\nلطفاً یکی از گزینه‌ها را انتخاب کنید:"
        
        await self.bot.edit_message_text(chat_id, message_id, text, parse_mode='Markdown', reply_markup=keyboard)
    
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
                
                # وقفه کوتاه برای جلوگیری از overload
                await asyncio.sleep(0.1)
                
            except Exception as e:
                print(f"❌ خطا در پردازش آپدیت: {e}")
                await asyncio.sleep(5)

# ============================
# تابع اصلی
# ============================
async def main():
    """تابع اصلی اجرای ربات"""
    # ایجاد دیتابیس
    init_db()
    
    # ایجاد handler
    handler = BotHandler()
    
    print("🤖 ربات فعال شد...")
    print("🌐 قابلیت دریافت خودکار پروکسی از 30+ منبع فعال است")
    print("📊 گزارش پیشرفت در داخل ربات نمایش داده می‌شود")
    print("📁 برای دریافت پروکسی‌ها از منو استفاده کنید")
    
    # شروع پردازش آپدیت‌ها
    await handler.process_updates()

if __name__ == '__main__':
    # اجرای event loop
    asyncio.run(main())