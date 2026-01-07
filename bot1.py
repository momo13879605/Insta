import os
import sys
import json
import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict
import tempfile

# کتابخانه‌های اینستاگرام
from instagrapi import Client
from instagrapi.exceptions import (
    ClientError, LoginRequired, ChallengeRequired,
    FeedbackRequired, MediaNotFound, UserNotFound
)

# کتابخانه‌های تلگرام
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message, FSInputFile, InputMediaPhoto, InputMediaVideo,
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# تنظیمات لاگ
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# توکن ربات تلگرام - اینجا قرار بده
BOT_TOKEN = "7413084969:AAHglr2N6eO_9VxhGCepns0iWKr9nYgmDZg"

# حالت‌های ربات
class LoginStates(StatesGroup):
    waiting_for_username = State()
    waiting_for_password = State()
    waiting_for_2fa = State()
    waiting_for_challenge = State()
    logged_in = State()

class UserSelectionStates(StatesGroup):
    waiting_for_username = State()
    waiting_for_action = State()
    waiting_for_post_count = State()

# کلاس مدیریت اینستاگرام
class InstagramManager:
    def __init__(self):
        self.script_dir = Path(__file__).resolve().parent
        self.session_dir = self.script_dir / "sessions"
        self.download_dir = self.script_dir / "downloads"
        
        # ساخت پوشه‌ها
        self.session_dir.mkdir(exist_ok=True)
        self.download_dir.mkdir(exist_ok=True)
        
        self.clients = {}  # {user_id: Client}
        self.user_data = {}  # {user_id: {username: "", target_user: ""}}

    async def login_user(self, user_id: int, username: str, password: str) -> tuple[bool, str, Optional[str]]:
        """لاگین کاربر و ذخیره سشن"""
        try:
            # ایجاد کلاینت جدید
            cl = Client()
            cl.delay_range = [2, 5]
            
            # مسیر سشن
            session_file = self.session_dir / f"{user_id}_{username}.json"
            
            # تلاش برای بارگذاری سشن قبلی
            if session_file.exists():
                try:
                    cl.load_settings(str(session_file))
                    await cl.get_timeline_feed()
                    self.clients[user_id] = cl
                    self.user_data[user_id] = {"username": username, "target_user": ""}
                    return True, f"✅ با موفقیت با سشن ذخیره شده وارد شدید. (@{username})", None
                except Exception as e:
                    logger.warning(f"Session expired: {e}")
                    if session_file.exists():
                        session_file.unlink()
            
            # لاگین جدید
            login_result = cl.login(username, password)
            
            # بررسی 2FA
            if cl.settings.get("2fa_enabled"):
                self.clients[user_id] = cl
                self.user_data[user_id] = {"username": username, "target_user": ""}
                return False, "🔑 احراز هویت دو مرحله‌ای فعال است. لطفا کد را وارد کنید:", "2fa"
            
            # ذخیره سشن
            cl.dump_settings(str(session_file))
            self.clients[user_id] = cl
            self.user_data[user_id] = {"username": username, "target_user": ""}
            return True, f"✅ لاگین موفقیت‌آمیز! خوش آمدید @{username}", None
            
        except ChallengeRequired:
            self.clients[user_id] = Client()
            self.user_data[user_id] = {"username": username, "target_user": ""}
            return False, "🛡️ چالش امنیتی اینستاگرام. لطفا کد ارسال شده را وارد کنید:", "challenge"
        except Exception as e:
            logger.error(f"Login error: {e}")
            return False, f"❌ خطا در لاگین: {str(e)}", None
    
    async def handle_2fa(self, user_id: int, code: str) -> tuple[bool, str]:
        """مدیریت احراز هویت دو مرحله‌ای"""
        try:
            cl = self.clients.get(user_id)
            if not cl:
                return False, "❌ سشن یافت نشد. لطفا دوباره لاگین کنید."
            
            cl.two_factor_login(code)
            # ذخیره سشن
            username = self.user_data[user_id]["username"]
            session_file = self.session_dir / f"{user_id}_{username}.json"
            cl.dump_settings(str(session_file))
            return True, f"✅ 2FA تایید شد! لاگین کامل شد."
            
        except Exception as e:
            logger.error(f"2FA error: {e}")
            return False, f"❌ خطا در تایید 2FA: {str(e)}"
    
    async def handle_challenge(self, user_id: int, code: str) -> tuple[bool, str]:
        """مدیریت چالش امنیتی"""
        try:
            cl = self.clients.get(user_id)
            if not cl:
                return False, "❌ سشن یافت نشد. لطفا دوباره لاگین کنید."
            
            cl.challenge_resolve(code)
            # ذخیره سشن
            username = self.user_data[user_id]["username"]
            session_file = self.session_dir / f"{user_id}_{username}.json"
            cl.dump_settings(str(session_file))
            return True, f"✅ چالش حل شد! لاگین کامل شد."
            
        except Exception as e:
            logger.error(f"Challenge error: {e}")
            return False, f"❌ خطا در حل چالش: {str(e)}"
    
    async def get_user_info(self, user_id: int, target_username: str) -> tuple[bool, str, Optional[Dict]]:
        """دریافت اطلاعات کاربر"""
        try:
            cl = self.clients.get(user_id)
            if not cl:
                return False, "❌ ابتدا باید لاگین کنید.", None
            
            target_user_id = cl.user_id_from_username(target_username)
            user_info = cl.user_info(target_user_id)
            
            info = {
                "username": user_info.username,
                "full_name": user_info.full_name,
                "bio": user_info.biography,
                "followers": user_info.follower_count,
                "following": user_info.following_count,
                "posts": user_info.media_count,
                "is_private": user_info.is_private,
                "is_verified": user_info.is_verified,
                "profile_pic_url": user_info.profile_pic_url_hd
            }
            
            return True, "✅ اطلاعات کاربر دریافت شد.", info
            
        except UserNotFound:
            return False, f"❌ کاربر @{target_username} یافت نشد.", None
        except Exception as e:
            logger.error(f"Get user info error: {e}")
            return False, f"❌ خطا: {str(e)}", None
    
    async def download_profile_pic(self, user_id: int, target_username: str) -> tuple[bool, str, List[str]]:
        """دانلود عکس پروفایل"""
        try:
            cl = self.clients.get(user_id)
            if not cl:
                return False, "❌ ابتدا باید لاگین کنید.", []
            
            target_user_id = cl.user_id_from_username(target_username)
            user_info = cl.user_info(target_user_id)
            
            # ایجاد پوشه موقت
            temp_dir = Path(tempfile.mkdtemp())
            file_path = temp_dir / f"{target_username}_profile.jpg"
            
            # دانلود عکس پروفایل
            response = cl.http.get(user_info.profile_pic_url_hd)
            if response.status_code == 200:
                with open(file_path, 'wb') as f:
                    f.write(response.content)
                
                caption = f"👤 پروفایل: @{target_username}\n"
                caption += f"📛 نام: {user_info.full_name}\n"
                caption += f"👥 فالوور: {user_info.follower_count:,}\n"
                if user_info.biography:
                    caption += f"📝 بیو: {user_info.biography}"
                
                return True, caption, [str(file_path)]
            else:
                return False, "❌ خطا در دانلود عکس پروفایل.", []
                
        except Exception as e:
            logger.error(f"Download profile pic error: {e}")
            return False, f"❌ خطا: {str(e)}", []
    
    async def download_stories(self, user_id: int, target_username: str) -> tuple[bool, str, List[str]]:
        """دانلود استوری‌های کاربر"""
        try:
            cl = self.clients.get(user_id)
            if not cl:
                return False, "❌ ابتدا باید لاگین کنید.", []
            
            target_user_id = cl.user_id_from_username(target_username)
            stories = cl.user_stories(target_user_id)
            
            if not stories:
                return False, f"❌ استوری فعالی برای @{target_username} یافت نشد.", []
            
            # ایجاد پوشه موقت
            temp_dir = Path(tempfile.mkdtemp())
            file_paths = []
            
            with open(temp_dir / "info.txt", "w", encoding="utf-8") as f:
                f.write(f"استوری‌های @{target_username}\n")
                f.write(f"تاریخ دانلود: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"تعداد استوری: {len(stories)}\n")
                f.write("="*50 + "\n")
                
                for i, story in enumerate(stories):
                    try:
                        if story.media_type == 2:  # ویدیو
                            path = cl.video_download(story.pk, folder=str(temp_dir))
                        else:  # عکس
                            path = cl.photo_download(story.pk, folder=str(temp_dir))
                        
                        if path:
                            file_paths.append(path)
                            f.write(f"استوری {i+1}: {os.path.basename(path)}\n")
                            f.write(f"تاریخ: {story.taken_at}\n")
                            f.write(f"نوع: {'ویدیو' if story.media_type == 2 else 'عکس'}\n")
                            f.write("-"*30 + "\n")
                            
                    except Exception as e:
                        logger.error(f"Error downloading story {i}: {e}")
                        continue
            
            caption = f"📖 استوری‌های @{target_username}\n"
            caption += f"📊 تعداد: {len(file_paths)} از {len(stories)}\n"
            caption += f"⏰ تاریخ دانلود: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            
            # اضافه کردن فایل اطلاعات
            file_paths.append(str(temp_dir / "info.txt"))
            
            return True, caption, file_paths
            
        except Exception as e:
            logger.error(f"Download stories error: {e}")
            return False, f"❌ خطا: {str(e)}", []
    
    async def download_highlights(self, user_id: int, target_username: str) -> tuple[bool, str, List[str]]:
        """دانلود هایلایت‌های کاربر"""
        try:
            cl = self.clients.get(user_id)
            if not cl:
                return False, "❌ ابتدا باید لاگین کنید.", []
            
            target_user_id = cl.user_id_from_username(target_username)
            highlights = cl.user_highlights(target_user_id)
            
            if not highlights:
                return False, f"❌ هایلایتی برای @{target_username} یافت نشد.", []
            
            # ایجاد پوشه موقت
            temp_dir = Path(tempfile.mkdtemp())
            file_paths = []
            total_items = 0
            
            with open(temp_dir / "info.txt", "w", encoding="utf-8") as f:
                f.write(f"هایلایت‌های @{target_username}\n")
                f.write(f"تاریخ دانلود: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"تعداد هایلایت: {len(highlights)}\n")
                f.write("="*50 + "\n")
                
                for h_idx, highlight in enumerate(highlights):
                    f.write(f"\nهایلایت {h_idx+1}: {highlight.title}\n")
                    f.write(f"تعداد آیتم: {len(highlight.items)}\n")
                    
                    highlight_folder = temp_dir / f"highlight_{h_idx+1}"
                    highlight_folder.mkdir(exist_ok=True)
                    
                    for i, item in enumerate(highlight.items):
                        try:
                            if item.media_type == 2:  # ویدیو
                                path = cl.video_download(item.pk, folder=str(highlight_folder))
                            else:  # عکس
                                path = cl.photo_download(item.pk, folder=str(highlight_folder))
                            
                            if path:
                                file_paths.append(path)
                                total_items += 1
                                f.write(f"  آیتم {i+1}: {os.path.basename(path)}\n")
                                
                        except Exception as e:
                            logger.error(f"Error downloading highlight item: {e}")
                            continue
            
            caption = f"🌟 هایلایت‌های @{target_username}\n"
            caption += f"📊 تعداد هایلایت: {len(highlights)}\n"
            caption += f"📁 تعداد آیتم: {total_items}\n"
            caption += f"⏰ تاریخ دانلود: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            
            # اضافه کردن فایل اطلاعات
            file_paths.append(str(temp_dir / "info.txt"))
            
            return True, caption, file_paths
            
        except Exception as e:
            logger.error(f"Download highlights error: {e}")
            return False, f"❌ خطا: {str(e)}", []
    
    async def download_posts(self, user_id: int, target_username: str, count: int = 12) -> tuple[bool, str, List[str]]:
        """دانلود پست‌های کاربر"""
        try:
            cl = self.clients.get(user_id)
            if not cl:
                return False, "❌ ابتدا باید لاگین کنید.", []
            
            target_user_id = cl.user_id_from_username(target_username)
            medias = cl.user_medias(target_user_id, amount=count)
            
            if not medias:
                return False, f"❌ پستی برای @{target_username} یافت نشد.", []
            
            # ایجاد پوشه موقت
            temp_dir = Path(tempfile.mkdtemp())
            file_paths = []
            
            with open(temp_dir / "info.txt", "w", encoding="utf-8") as f:
                f.write(f"پست‌های @{target_username}\n")
                f.write(f"تاریخ دانلود: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"تعداد پست: {len(medias)}\n")
                f.write("="*50 + "\n")
                
                for i, media in enumerate(medias):
                    try:
                        f.write(f"\nپست {i+1}:\n")
                        f.write(f"لینک: https://www.instagram.com/p/{media.code}/\n")
                        f.write(f"تاریخ: {media.taken_at}\n")
                        f.write(f"لایک: {media.like_count}\n")
                        f.write(f"کامنت: {media.comment_count}\n")
                        if media.caption_text:
                            f.write(f"کپشن: {media.caption_text[:200]}...\n")
                        
                        if media.media_type == 8:  # آلبوم
                            album_folder = temp_dir / f"post_{i+1}"
                            album_folder.mkdir(exist_ok=True)
                            
                            for j, resource in enumerate(media.resources):
                                if resource.video_url:
                                    path = cl.video_download(resource.pk, folder=str(album_folder))
                                else:
                                    path = cl.photo_download(resource.pk, folder=str(album_folder))
                                
                                if path:
                                    file_paths.append(path)
                                    f.write(f"  فایل {j+1}: {os.path.basename(path)}\n")
                            
                        elif media.media_type == 2:  # ویدیو
                            path = cl.video_download(media.pk, folder=str(temp_dir))
                            if path:
                                file_paths.append(path)
                                f.write(f"فایل: {os.path.basename(path)}\n")
                                
                        else:  # عکس
                            path = cl.photo_download(media.pk, folder=str(temp_dir))
                            if path:
                                file_paths.append(path)
                                f.write(f"فایل: {os.path.basename(path)}\n")
                                
                        f.write("-"*30 + "\n")
                        
                    except Exception as e:
                        logger.error(f"Error downloading post {i}: {e}")
                        f.write(f"خطا در دانلود: {str(e)}\n")
                        continue
            
            caption = f"📸 پست‌های @{target_username}\n"
            caption += f"📊 تعداد: {len(file_paths)} فایل از {len(medias)} پست\n"
            caption += f"⏰ تاریخ دانلود: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            
            # اضافه کردن فایل اطلاعات
            file_paths.append(str(temp_dir / "info.txt"))
            
            return True, caption, file_paths
            
        except Exception as e:
            logger.error(f"Download posts error: {e}")
            return False, f"❌ خطا: {str(e)}", []
    
    async def download_followers(self, user_id: int, target_username: str, count: int = 100) -> tuple[bool, str, List[str]]:
        """دریافت لیست فالوورها"""
        try:
            cl = self.clients.get(user_id)
            if not cl:
                return False, "❌ ابتدا باید لاگین کنید.", []
            
            target_user_id = cl.user_id_from_username(target_username)
            followers = cl.user_followers(target_user_id, amount=count)
            
            if not followers:
                return False, f"❌ فالووری برای @{target_username} یافت نشد.", []
            
            # ایجاد فایل TXT
            temp_dir = Path(tempfile.mkdtemp())
            txt_file = temp_dir / f"followers_{target_username}.txt"
            
            with open(txt_file, "w", encoding="utf-8") as f:
                f.write(f"لیست فالوورهای @{target_username}\n")
                f.write(f"تاریخ: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"تعداد: {len(followers)}\n")
                f.write("="*50 + "\n\n")
                
                for i, (follower_id, follower_info) in enumerate(followers.items(), 1):
                    f.write(f"{i}. @{follower_info.username}\n")
                    f.write(f"   نام: {follower_info.full_name}\n")
                    f.write(f"   فالوور: {follower_info.follower_count:,}\n")
                    f.write(f"   فالووینگ: {follower_info.following_count:,}\n")
                    f.write(f"   پست: {follower_info.media_count}\n")
                    f.write(f"   خصوصی: {'بله' if follower_info.is_private else 'خیر'}\n")
                    f.write("-"*30 + "\n")
            
            caption = f"👥 فالوورهای @{target_username}\n"
            caption += f"📊 تعداد: {len(followers)} نفر\n"
            caption += f"📁 فایل TXT آماده دانلود"
            
            return True, caption, [str(txt_file)]
            
        except Exception as e:
            logger.error(f"Download followers error: {e}")
            return False, f"❌ خطا: {str(e)}", []
    
    def cleanup_temp_files(self, file_paths: List[str]):
        """پاکسازی فایل‌های موقت"""
        for file_path in file_paths:
            try:
                if os.path.exists(file_path):
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                    elif os.path.isdir(file_path):
                        import shutil
                        shutil.rmtree(file_path)
            except Exception as e:
                logger.error(f"Error cleaning up {file_path}: {e}")

# ایجاد ربات
router = Router()
instagram_manager = InstagramManager()

def create_user_menu() -> InlineKeyboardMarkup:
    """ایجاد منوی انتخاب عملیات برای کاربر"""
    keyboard = [
        [InlineKeyboardButton(text="📊 اطلاعات پروفایل", callback_data="action_profile_info")],
        [InlineKeyboardButton(text="🖼️ عکس پروفایل", callback_data="action_profile_pic")],
        [InlineKeyboardButton(text="📖 استوری‌ها", callback_data="action_stories")],
        [InlineKeyboardButton(text="🌟 هایلایت‌ها", callback_data="action_highlights")],
        [InlineKeyboardButton(text="📸 پست‌ها", callback_data="action_posts")],
        [InlineKeyboardButton(text="👥 فالوورها", callback_data="action_followers")],
        [InlineKeyboardButton(text="❌ انصراف", callback_data="action_cancel")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def create_post_count_menu() -> InlineKeyboardMarkup:
    """منوی انتخاب تعداد پست"""
    keyboard = [
        [InlineKeyboardButton(text="12 پست آخر", callback_data="count_12")],
        [InlineKeyboardButton(text="24 پست آخر", callback_data="count_24")],
        [InlineKeyboardButton(text="50 پست آخر", callback_data="count_50")],
        [InlineKeyboardButton(text="100 پست آخر", callback_data="count_100")],
        [InlineKeyboardButton(text="❌ انصراف", callback_data="action_cancel")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def create_follower_count_menu() -> InlineKeyboardMarkup:
    """منوی انتخاب تعداد فالوور"""
    keyboard = [
        [InlineKeyboardButton(text="100 فالوور", callback_data="fcount_100")],
        [InlineKeyboardButton(text="500 فالوور", callback_data="fcount_500")],
        [InlineKeyboardButton(text="1000 فالوور", callback_data="fcount_1000")],
        [InlineKeyboardButton(text="همه فالوورها", callback_data="fcount_all")],
        [InlineKeyboardButton(text="❌ انصراف", callback_data="action_cancel")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "👋 خوش آمدید به ربات پیشرفته دانلودر اینستاگرام!\n\n"
        "✨ <b>ویژگی‌های ربات:</b>\n"
        "• دانلود استوری‌ها\n"
        "• دانلود هایلایت‌ها\n"
        "• دانلود پست‌ها\n"
        "• دریافت عکس پروفایل\n"
        "• مشاهده اطلاعات کامل پروفایل\n"
        "• دریافت لیست فالوورها\n\n"
        "📋 <b>دستورات:</b>\n"
        "/login - ورود به حساب اینستاگرام\n"
        "/download - انتخاب کاربر و عملیات\n"
        "/logout - خروج از حساب\n"
        "/status - وضعیت فعلی\n"
        "/help - راهنمایی کامل\n\n"
        "⚠️ <i>اطلاعات لاگین شما به صورت امن ذخیره می‌شود.</i>",
        parse_mode=ParseMode.HTML
    )

@router.message(Command("login"))
async def cmd_login(message: Message, state: FSMContext):
    await state.set_state(LoginStates.waiting_for_username)
    await message.answer("📝 لطفا <b>نام کاربری اینستاگرام</b> خود را وارد کنید:", parse_mode=ParseMode.HTML)

@router.message(LoginStates.waiting_for_username)
async def process_username(message: Message, state: FSMContext):
    await state.update_data(username=message.text.strip())
    await state.set_state(LoginStates.waiting_for_password)
    await message.answer("🔑 لطفا <b>رمز عبور</b> خود را وارد کنید:", parse_mode=ParseMode.HTML)

@router.message(LoginStates.waiting_for_password)
async def process_password(message: Message, state: FSMContext):
    await state.update_data(password=message.text.strip())
    user_data = await state.get_data()
    
    # نمایش در حال پردازش
    processing_msg = await message.answer("⏳ <b>در حال لاگین...</b>", parse_mode=ParseMode.HTML)
    
    # انجام لاگین
    result, msg, challenge_type = await instagram_manager.login_user(
        message.from_user.id,
        user_data['username'],
        user_data['password']
    )
    
    if result:
        await state.set_state(LoginStates.logged_in)
        await processing_msg.edit_text(msg + "\n\n✅ <b>اکنون می‌توانید از /download استفاده کنید.</b>", parse_mode=ParseMode.HTML)
    elif challenge_type == "2fa":
        await state.set_state(LoginStates.waiting_for_2fa)
        await processing_msg.edit_text(msg, parse_mode=ParseMode.HTML)
    elif challenge_type == "challenge":
        await state.set_state(LoginStates.waiting_for_challenge)
        await processing_msg.edit_text(msg, parse_mode=ParseMode.HTML)
    else:
        await state.clear()
        await processing_msg.edit_text(msg, parse_mode=ParseMode.HTML)

@router.message(LoginStates.waiting_for_2fa)
async def process_2fa(message: Message, state: FSMContext):
    result, msg = await instagram_manager.handle_2fa(
        message.from_user.id,
        message.text.strip()
    )
    
    if result:
        await state.set_state(LoginStates.logged_in)
        await message.answer(msg + "\n\n✅ <b>اکنون می‌توانید از /download استفاده کنید.</b>", parse_mode=ParseMode.HTML)
    else:
        await state.clear()
        await message.answer(msg + "\n\nلطفا دوباره از /login شروع کنید.")

@router.message(LoginStates.waiting_for_challenge)
async def process_challenge(message: Message, state: FSMContext):
    result, msg = await instagram_manager.handle_challenge(
        message.from_user.id,
        message.text.strip()
    )
    
    if result:
        await state.set_state(LoginStates.logged_in)
        await message.answer(msg + "\n\n✅ <b>اکنون می‌توانید از /download استفاده کنید.</b>", parse_mode=ParseMode.HTML)
    else:
        await state.clear()
        await message.answer(msg + "\n\nلطفا دوباره از /login شروع کنید.")

@router.message(Command("download"))
async def cmd_download(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state != LoginStates.logged_in:
        await message.answer("❌ ابتدا باید لاگین کنید. از /login استفاده کنید.")
        return
    
    await state.set_state(UserSelectionStates.waiting_for_username)
    await message.answer(
        "👤 لطفا <b>نام کاربری اینستاگرام</b> مورد نظر را وارد کنید:\n\n"
        "<i>مثال: instagram یا barackobama</i>\n\n"
        "⚠️ توجه: کاربر باید عمومی باشد یا شما باید او را فالو کرده باشید.",
        parse_mode=ParseMode.HTML
    )

@router.message(UserSelectionStates.waiting_for_username)
async def process_target_username(message: Message, state: FSMContext):
    target_username = message.text.strip().replace("@", "")
    
    # ذخیره نام کاربری هدف
    user_data = instagram_manager.user_data.get(message.from_user.id, {})
    user_data["target_user"] = target_username
    instagram_manager.user_data[message.from_user.id] = user_data
    
    await state.set_state(UserSelectionStates.waiting_for_action)
    
    # نمایش منو
    await message.answer(
        f"🎯 کاربر انتخاب شده: <b>@{target_username}</b>\n\n"
        f"لطفا عملیات مورد نظر را انتخاب کنید:",
        reply_markup=create_user_menu(),
        parse_mode=ParseMode.HTML
    )

@router.callback_query(F.data.startswith("action_"))
async def handle_action(callback: CallbackQuery, state: FSMContext):
    action = callback.data
    user_id = callback.from_user.id
    
    # دریافت اطلاعات کاربر هدف
    user_data = instagram_manager.user_data.get(user_id, {})
    target_username = user_data.get("target_user", "")
    
    if not target_username:
        await callback.answer("❌ کاربری انتخاب نشده!")
        return
    
    if action == "action_cancel":
        await state.set_state(LoginStates.logged_in)
        await callback.message.edit_text("❌ عملیات لغو شد.")
        await callback.answer()
        return
    
    # نمایش در حال پردازش
    processing_msg = await callback.message.answer("⏳ <b>در حال پردازش...</b>", parse_mode=ParseMode.HTML)
    
    if action == "action_profile_info":
        # دریافت اطلاعات پروفایل
        success, msg, info = await instagram_manager.get_user_info(user_id, target_username)
        
        if success and info:
            response = f"📊 <b>اطلاعات پروفایل:</b>\n\n"
            response += f"👤 <b>Username:</b> @{info['username']}\n"
            response += f"📛 <b>Full Name:</b> {info['full_name']}\n"
            response += f"👥 <b>Followers:</b> {info['followers']:,}\n"
            response += f"🔁 <b>Following:</b> {info['following']:,}\n"
            response += f"📸 <b>Posts:</b> {info['posts']}\n"
            response += f"🔒 <b>Private:</b> {'بله' if info['is_private'] else 'خیر'}\n"
            response += f"✅ <b>Verified:</b> {'بله' if info['is_verified'] else 'خیر'}\n"
            if info['bio']:
                response += f"📝 <b>Bio:</b> {info['bio']}\n"
            
            await processing_msg.edit_text(response, parse_mode=ParseMode.HTML)
        else:
            await processing_msg.edit_text(msg, parse_mode=ParseMode.HTML)
    
    elif action == "action_profile_pic":
        # دانلود عکس پروفایل
        success, caption, file_paths = await instagram_manager.download_profile_pic(user_id, target_username)
        
        if success and file_paths:
            for file_path in file_paths:
                if file_path.endswith('.jpg') or file_path.endswith('.png'):
                    file = FSInputFile(file_path)
                    await callback.message.answer_photo(file, caption=caption[:1000], parse_mode=ParseMode.HTML)
            
            await processing_msg.delete()
        else:
            await processing_msg.edit_text(caption, parse_mode=ParseMode.HTML)
        
        # پاکسازی فایل‌ها
        instagram_manager.cleanup_temp_files(file_paths)
    
    elif action == "action_stories":
        # دانلود استوری‌ها
        success, caption, file_paths = await instagram_manager.download_stories(user_id, target_username)
        
        if success and file_paths:
            # ارسال فایل‌های مدیا
            media_files = [fp for fp in file_paths if not fp.endswith('.txt')]
            txt_files = [fp for fp in file_paths if fp.endswith('.txt')]
            
            # ارسال مدیاها
            for file_path in media_files[:10]:  # حداکثر 10 فایل
                try:
                    file = FSInputFile(file_path)
                    if file_path.lower().endswith(('.mp4', '.mov', '.avi')):
                        await callback.message.answer_video(file)
                    else:
                        await callback.message.answer_photo(file)
                except:
                    continue
            
            # ارسال فایل اطلاعات
            if txt_files:
                file = FSInputFile(txt_files[0])
                await callback.message.answer_document(file, caption=caption[:1000], parse_mode=ParseMode.HTML)
            
            await processing_msg.delete()
        else:
            await processing_msg.edit_text(caption, parse_mode=ParseMode.HTML)
        
        # پاکسازی فایل‌ها
        instagram_manager.cleanup_temp_files(file_paths)
    
    elif action == "action_highlights":
        # دانلود هایلایت‌ها
        success, caption, file_paths = await instagram_manager.download_highlights(user_id, target_username)
        
        if success and file_paths:
            # ارسال فایل اطلاعات
            txt_files = [fp for fp in file_paths if fp.endswith('.txt')]
            if txt_files:
                file = FSInputFile(txt_files[0])
                await callback.message.answer_document(file, caption=caption[:1000], parse_mode=ParseMode.HTML)
            
            await processing_msg.delete()
        else:
            await processing_msg.edit_text(caption, parse_mode=ParseMode.HTML)
        
        # پاکسازی فایل‌ها
        instagram_manager.cleanup_temp_files(file_paths)
    
    elif action == "action_posts":
        # نمایش منوی تعداد پست
        await processing_msg.delete()
        await callback.message.answer(
            "📊 لطفا تعداد پست‌هایی که می‌خواهید دانلود کنید را انتخاب کنید:",
            reply_markup=create_post_count_menu()
        )
    
    elif action == "action_followers":
        # نمایش منوی تعداد فالوور
        await processing_msg.delete()
        await callback.message.answer(
            "👥 لطفا تعداد فالوورهایی که می‌خواهید دریافت کنید را انتخاب کنید:",
            reply_markup=create_follower_count_menu()
        )
    
    await callback.answer()

@router.callback_query(F.data.startswith("count_"))
async def handle_post_count(callback: CallbackQuery, state: FSMContext):
    count_data = callback.data
    user_id = callback.from_user.id
    
    # دریافت اطلاعات کاربر هدف
    user_data = instagram_manager.user_data.get(user_id, {})
    target_username = user_data.get("target_user", "")
    
    if not target_username:
        await callback.answer("❌ کاربری انتخاب نشده!")
        return
    
    # تعیین تعداد
    if count_data == "count_12":
        count = 12
    elif count_data == "count_24":
        count = 24
    elif count_data == "count_50":
        count = 50
    elif count_data == "count_100":
        count = 100
    else:
        count = 12
    
    # نمایش در حال پردازش
    processing_msg = await callback.message.answer(f"⏳ <b>در حال دانلود {count} پست آخر...</b>", parse_mode=ParseMode.HTML)
    
    # دانلود پست‌ها
    success, caption, file_paths = await instagram_manager.download_posts(user_id, target_username, count)
    
    if success and file_paths:
        # ارسال فایل اطلاعات
        txt_files = [fp for fp in file_paths if fp.endswith('.txt')]
        if txt_files:
            file = FSInputFile(txt_files[0])
            await callback.message.answer_document(file, caption=caption[:1000], parse_mode=ParseMode.HTML)
        
        await processing_msg.delete()
    else:
        await processing_msg.edit_text(caption, parse_mode=ParseMode.HTML)
    
    # پاکسازی فایل‌ها
    instagram_manager.cleanup_temp_files(file_paths)
    await callback.answer()

@router.callback_query(F.data.startswith("fcount_"))
async def handle_follower_count(callback: CallbackQuery, state: FSMContext):
    count_data = callback.data
    user_id = callback.from_user.id
    
    # دریافت اطلاعات کاربر هدف
    user_data = instagram_manager.user_data.get(user_id, {})
    target_username = user_data.get("target_user", "")
    
    if not target_username:
        await callback.answer("❌ کاربری انتخاب نشده!")
        return
    
    # تعیین تعداد
    if count_data == "fcount_100":
        count = 100
    elif count_data == "fcount_500":
        count = 500
    elif count_data == "fcount_1000":
        count = 1000
    elif count_data == "fcount_all":
        count = 5000  # حداکثر
    else:
        count = 100
    
    # نمایش در حال پردازش
    processing_msg = await callback.message.answer(f"⏳ <b>در حال دریافت {count} فالوور...</b>", parse_mode=ParseMode.HTML)
    
    # دریافت فالوورها
    success, caption, file_paths = await instagram_manager.download_followers(user_id, target_username, count)
    
    if success and file_paths:
        # ارسال فایل TXT
        if file_paths:
            file = FSInputFile(file_paths[0])
            await callback.message.answer_document(file, caption=caption[:1000], parse_mode=ParseMode.HTML)
        
        await processing_msg.delete()
    else:
        await processing_msg.edit_text(caption, parse_mode=ParseMode.HTML)
    
    # پاکسازی فایل‌ها
    instagram_manager.cleanup_temp_files(file_paths)
    await callback.answer()

@router.message(Command("logout"))
async def cmd_logout(message: Message, state: FSMContext):
    user_id = message.from_user.id
    
    # حذف کلاینت کاربر
    if user_id in instagram_manager.clients:
        del instagram_manager.clients[user_id]
    
    # حذف داده‌های کاربر
    if user_id in instagram_manager.user_data:
        del instagram_manager.user_data[user_id]
    
    # حذف فایل سشن
    session_files = list(instagram_manager.session_dir.glob(f"{user_id}_*"))
    for file in session_files:
        try:
            file.unlink()
        except:
            pass
    
    await state.clear()
    await message.answer("✅ از حساب خود خارج شدید. تمام داده‌ها حذف شدند.")

@router.message(Command("status"))
async def cmd_status(message: Message, state: FSMContext):
    current_state = await state.get_state()
    user_id = message.from_user.id
    
    if current_state == LoginStates.logged_in:
        user_data = instagram_manager.user_data.get(user_id, {})
        username = user_data.get("username", "نامشخص")
        
        response = f"✅ <b>وضعیت: لاگین شده</b>\n\n"
        response += f"👤 <b>اکانت:</b> @{username}\n"
        response += f"📋 <b>دستورات قابل استفاده:</b>\n"
        response += f"• /download - انتخاب کاربر و عملیات\n"
        response += f"• /logout - خروج از حساب\n"
        response += f"• /status - وضعیت فعلی\n"
        
        await message.answer(response, parse_mode=ParseMode.HTML)
    else:
        await message.answer("❌ <b>وضعیت: لاگین نشده</b>\n\nلطفا از /login استفاده کنید.", parse_mode=ParseMode.HTML)

@router.message(Command("help"))
async def cmd_help(message: Message):
    help_text = """
📖 <b>راهنمای کامل ربات اینستاگرام</b>

<b>مراحل کار:</b>
1. ابتدا با دستور /login وارد حساب اینستاگرام خود شوید
2. سپس با /download نام کاربری مورد نظر را وارد کنید
3. عملیات مورد نظر را از منو انتخاب کنید

<b>📋 عملیات‌های قابل انجام:</b>
• <b>اطلاعات پروفایل</b> - مشاهده اطلاعات کامل کاربر
• <b>عکس پروفایل</b> - دانلود عکس پروفایل با کیفیت HD
• <b>استوری‌ها</b> - دانلود استوری‌های فعال کاربر
• <b>هایلایت‌ها</b> - دانلود هایلایت‌های کاربر
• <b>پست‌ها</b> - دانلود پست‌های کاربر (قابل انتخاب تعداد)
• <b>فالوورها</b> - دریافت لیست فالوورهای کاربر

<b>⚠️ نکات مهم:</b>
• کاربر هدف باید عمومی باشد یا شما او را فالو کرده باشید
• برای امنیت بیشتر، از یک اکانت dummy استفاده کنید
• دانلود حجم بالا ممکن است باعث محدودیت موقت شود
• از /logout برای خروج امن استفاده کنید

<b>🔧 پشتیبانی فنی:</b>
• کتابخانه: instagrapi
• زبان: Python
• رابط: Telegram Bot API

<i>ربات توسط @ توسعه داده شده است.</i>
"""
    await message.answer(help_text, parse_mode=ParseMode.HTML)

@router.message(F.text)
async def handle_text(message: Message):
    """مدیریت پیام‌های متنی عمومی"""
    await message.answer(
        "🤔 <b>دستور نامعتبر</b>\n\n"
        "از منو استفاده کنید:\n"
        "/start - شروع\n"
        "/login - ورود\n"
        "/download - دانلود\n"
        "/logout - خروج\n"
        "/help - راهنمایی\n"
        "/status - وضعیت",
        parse_mode=ParseMode.HTML
    )

async def main():
    # بررسی توکن
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("❌ لطفا ابتدا توکن ربات خود را در متغیر BOT_TOKEN قرار دهید!")
        print("\n" + "="*60)
        print("❌ لطفا ابتدا توکن ربات خود را در فایل قرار دهید:")
        print("1. فایل را باز کنید")
        print("2. خط 37 را پیدا کنید: BOT_TOKEN = \"YOUR_BOT_TOKEN_HERE\"")
        print("3. YOUR_BOT_TOKEN_HERE را با توکن ربات خود جایگزین کنید")
        print("="*60 + "\n")
        return
    
    # بررسی نسخه پایتون
    if sys.version_info < (3, 7):
        print("❌ این اسکریپت نیاز به پایتون 3.7 یا بالاتر دارد.")
        sys.exit(1)
    
    # ایجاد بوت
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    dp.include_router(router)
    
    logger.info("🤖 ربات پیشرفته اینستاگرام شروع به کار کرد...")
    print("\n" + "="*60)
    print("✅ ربات با موفقیت راه‌اندازی شد!")
    print(f"🤖 آدرس ربات: https://t.me/{(await bot.get_me()).username}")
    print("👤 دستور /start را در ربات ارسال کنید")
    print("="*60 + "\n")
    
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())