import importlib.util
import subprocess
import sys
import os
import time
import json
import random
import string
import threading
import re
import logging
import tempfile
from datetime import datetime, timedelta

# --- AUTOMATIC DEPENDENCY CHECK ---
for pkg in ["flask", "pyTelegramBotAPI", "pillow", "requests"]:
    mod = "telebot" if pkg == "pyTelegramBotAPI" else ("PIL" if pkg == "pillow" else pkg)
    if importlib.util.find_spec(mod) is None:
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])
        except Exception as e:
            print(f"Failed to install {pkg}: {e}")

from flask import Flask
import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from PIL import Image, ImageDraw, ImageFont
import io

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ============================================
# --- WEB SERVER FOR RENDER (KEEP ALIVE) ---
# ============================================
app = Flask('')

@app.route('/')
def home():
    return "🤖 Earning Captcha & BDT Bot Engine is Running 24/7!"

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = threading.Thread(target=run_web_server)
    t.daemon = True
    t.start()

# ============================================
# --- CONFIGURATION & SECURITY ---
# ============================================

MY_DIRECT_BOT_TOKEN = "9296738675:AAG1ywjPCIYsKIGn1TMH3WFhuEbrjDiItB8" 

BOT_TOKEN = os.getenv("BOT_TOKEN") or MY_DIRECT_BOT_TOKEN
ADMIN_ID_RAW = os.getenv("ADMIN_ID", "7833766898")

if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
    logging.critical("CRITICAL: BOT_TOKEN environment variable is missing! Server cannot start.")
    sys.exit("Error: BOT_TOKEN Environment Variable is required.")

try:
    ADMIN_ID = int(ADMIN_ID_RAW)
except ValueError:
    ADMIN_ID = 7833766898

BOT_NAME = "🤖 𝑬𝒂𝒓𝒏𝒊𝒏𝒈 𝑪𝒂𝒑𝒕𝒄𝒉𝒂 & 𝑩𝑫𝑻 𝑩𝑶𝑻 💸"
DATA_FILE = "earning_captcha_bot_data.json"

bot = telebot.TeleBot(BOT_TOKEN, num_threads=50)
db_lock = threading.RLock()

# ============================================
# --- BUTTON COLOR & FACTORY HELPER ---
# ============================================
def make_inline_button(text, callback_data=None, url=None, style=None):
    clean_text = re.sub(r'^[🟢🔴🔵]\s*', '', text).strip()
    prefix = ""
    if style == "success":
        prefix = "🟢 "
    elif style == "danger":
        prefix = "🔴 "
    elif style == "primary":
        prefix = "🔵 "
    
    final_text = f"{prefix}{clean_text}".strip()
    
    if url:
        return InlineKeyboardButton(text=final_text, url=url)
    return InlineKeyboardButton(text=final_text, callback_data=callback_data)

# ============================================
# --- DATABASE MANAGEMENT (ATOMIC LOCKING) ---
# ============================================
def get_dhaka_today_str():
    dhaka_time = datetime.utcnow() + timedelta(hours=6)
    return dhaka_time.strftime("%Y-%m-%d")

def load_db():
    with db_lock:
        default_db = {
            "users": {},
            "banned_users": [],
            "force_channels": [],
            "ref_bonus_verify": 0.40,
            "min_withdraw": 50.0,
            "withdraw_min_ref": 2,
            "withdraw_fee_percent": 0.0,
            "daily_bonus_amount": 5.0,
            "maintenance_mode": False,
            "anti_fraud_enabled": True,
            "auto_payment_api": "",
            "payment_proof_channel": "",
            "custom_buttons": {},
            "sys_texts": {
                "welcome": "Welcome back to our bot! Choose an option below:",
                "refer_rules": "Refer your friends and earn instant rewards once they verify!",
                "help_text": "If you face any issues, send your query here for support."
            },
            "tasks": {
                "captcha": {"desc": "Solve Math & Text Captchas", "rate": 1.0, "limit": 30}
            },
            "pending_withdraws": {},
            "transactions": []
        }

        if not os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "w", encoding='utf-8') as f:
                    json.dump(default_db, f, indent=4, ensure_ascii=False)
            except Exception as e:
                logging.error(f"Error initializing DB: {e}")
            return default_db

        try:
            with open(DATA_FILE, "r", encoding='utf-8') as f:
                data = json.load(f)
                for key, val in default_db.items():
                    if key not in data:
                        data[key] = val
                return data
        except Exception as e:
            logging.error(f"Error loading DB: {e}")
            return default_db

def save_db(data):
    with db_lock:
        try:
            dir_name = os.path.dirname(os.path.abspath(DATA_FILE))
            with tempfile.NamedTemporaryFile('w', dir=dir_name, delete=False, encoding='utf-8') as tf:
                json.dump(data, tf, indent=4, ensure_ascii=False)
                temp_name = tf.name
            os.replace(temp_name, DATA_FILE)
        except Exception as e:
            logging.error(f"Database Save Error (Atomic Failure): {e}")

def get_user(user_id, name="User", username=""):
    with db_lock:
        data = load_db()
        uid = str(user_id)
        today_str = get_dhaka_today_str()

        if uid not in data["users"]:
            data["users"][uid] = {
                "name": name,
                "username": username,
                "balance": 0.0,
                "total_ref_bonus": 0.0,
                "total_withdraw": 0.0,
                "pending_withdraw": 0.0,
                "completed_tasks": 0,
                "rejected_tasks": 0,
                "pending_tasks": 0,
                "lang": "bn",
                "referred_by": None,
                "ref_rewarded": False,
                "referrals": 0,
                "referral_list": [],
                "daily_bonus_claimed": False,
                "last_bonus_date": "",
                "last_active": time.time(),
                "last_captcha_time": 0.0, # Rate Limiting / Cooldown Tracking
                "state": None,
                "temp_data": {},
                "daily_task_counts": {today_str: {}}
            }
            save_db(data)
        else:
            data["users"][uid]["last_active"] = time.time()
            data["users"][uid]["name"] = name
            data["users"][uid]["username"] = username
            if "last_captcha_time" not in data["users"][uid]:
                data["users"][uid]["last_captcha_time"] = 0.0
            if "daily_task_counts" not in data["users"][uid]:
                data["users"][uid]["daily_task_counts"] = {}
            if today_str not in data["users"][uid]["daily_task_counts"]:
                data["users"][uid]["daily_task_counts"][today_str] = {}
            save_db(data)
        return data["users"][uid]

def update_user(user_id, key, val):
    with db_lock:
        data = load_db()
        uid = str(user_id)
        if uid in data["users"]:
            data["users"][uid][key] = val
            save_db(data)

def add_transaction(user_id, tx_type, amount, desc):
    with db_lock:
        data = load_db()
        uid = str(user_id)
        bal_before = data["users"].get(uid, {}).get("balance", 0.0)
        tx = {
            "tx_id": f"tx_{int(time.time()*1000)}_{random.randint(100,999)}",
            "user_id": user_id,
            "type": tx_type,
            "amount": amount,
            "balance_after": bal_before,
            "desc": desc,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        data["transactions"].append(tx)
        save_db(data)

# ============================================
# --- IMAGE & MATH CAPTCHA GENERATOR ---
# ============================================
def generate_image_captcha():
    choice_type = random.choice(["text", "math"])
    if choice_type == "text":
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
        actual_ans = code
    else:
        n1 = random.randint(1, 20)
        n2 = random.randint(1, 20)
        op = random.choice(["+", "-"])
        if op == "+":
            actual_ans = str(n1 + n2)
        else:
            if n1 < n2:
                n1, n2 = n2, n1
            actual_ans = str(n1 - n2)
        code = f"{n1}{op}{n2}"

    img = Image.new('RGB', (180, 70), color=(30, 39, 46))
    draw = ImageDraw.Draw(img)
    for _ in range(6):
        x1, y1 = random.randint(0, 180), random.randint(0, 70)
        x2, y2 = random.randint(0, 180), random.randint(0, 70)
        draw.line([(x1, y1), (x2, y2)], fill=(120, 120, 120), width=1)
    try:
        font = ImageFont.truetype("arial.ttf", 28)
    except:
        font = ImageFont.load_default()
    draw.text((25, 18), code, fill=(255, 234, 167), font=font)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf, actual_ans

# ============================================
# --- DYNAMIC WALLET BANNER GENERATOR (PILLOW) ---
# ============================================
def generate_wallet_banner(user_name, balance, referrals, total_withdraw):
    img = Image.new('RGB', (600, 300), color=(15, 23, 42))
    draw = ImageDraw.Draw(img)
    
    # Decorative header box & border
    draw.rectangle([20, 20, 580, 280], outline=(56, 189, 248), width=3)
    draw.rectangle([25, 25, 575, 80], fill=(30, 41, 59))
    
    try:
        font_title = ImageFont.truetype("arial.ttf", 24)
        font_text = ImageFont.truetype("arial.ttf", 20)
    except:
        font_title = ImageFont.load_default()
        font_text = ImageFont.load_default()
        
    draw.text((40, 38), "💎 VIP USER WALLET DASHBOARD 💎", fill=(255, 215, 0), font=font_title)
    
    info_lines = [
        f"👤 Name: {user_name[:20]}",
        f"💰 Balance: ৳{balance:.2f} BDT",
        f"👥 Total Referrals: {referrals} Persons",
        f"📤 Total Withdrawn: ৳{total_withdraw:.2f} BDT"
    ]
    
    y_offset = 105
    for line in info_lines:
        draw.text((45, y_offset), line, fill=(241, 245, 249), font=font_text)
        y_offset += 38
        
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf

# ============================================
# --- FORCE JOIN & LIVE GUARD CHECKER ---
# ============================================
def check_force_join(user_id):
    if int(user_id) == ADMIN_ID:
        return []
    data = load_db()
    left_channels = []
    for ch in data.get("force_channels", []):
        try:
            member = bot.get_chat_member(ch, user_id)
            if member.status in ['left', 'kicked']:
                left_channels.append(ch)
        except Exception as e:
            logging.warning(f"Could not check force join status for {ch}: {e}")
            continue
    return left_channels

def get_force_join_markup(left_channels):
    # বাটনগুলো পাশাপাশি (row_width=2) সাজানো হয়েছে
    markup = InlineKeyboardMarkup(row_width=2)
    buttons = []
    for ch in left_channels:
        clean_ch = ch.replace("@", "")
        buttons.append(make_inline_button(text=f"📢 Join {ch}", url=f"https://t.me/{clean_ch}", style="primary"))
    
    if len(buttons) > 0:
        markup.add(*buttons)
    
    markup.add(make_inline_button(text="✅ Verify Now", callback_data="verify_join", style="success"))
    return markup

# ============================================
# --- KEYBOARDS & MENUS ---
# ============================================
TXT_WALLET = "💰 𝑴𝒚 𝑾𝒂𝒍𝒍𝒆𝒕"
TXT_REFER = "⚡ 𝑰𝒏𝒔𝒕𝒂𝒏𝒕 𝑹𝒆𝒇𝒆𝒓"
TXT_DAILY_BONUS = "🎁 𝑫𝒂𝒊𝒍𝒚 𝑩𝒐𝒏𝒖ْس"
TXT_CAPTCHA_SOLVE = "⌨️ 𝑬𝒂𝒓𝒏𝒊𝒏𝒈 𝑪𝒂𝒑𝒕𝒄𝒉𝒂"
TXT_WITHDRAW = "📥 𝑾𝒊𝒕𝒉𝒅𝒓𝒂𝒘 𝑩𝑫𝑻"
TXT_SETTINGS = "⚙️ 𝑺𝒆𝒕𝒕𝒊𝒏𝒈𝒔 / 𝑯𝒆𝒍𝒑"
TXT_ADMIN = "⚙️ Admin Panel"

def get_main_menu(user_id):
    data = load_db()
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)

    markup.add(KeyboardButton(TXT_WALLET), KeyboardButton(TXT_REFER))
    markup.add(KeyboardButton(TXT_DAILY_BONUS), KeyboardButton(TXT_CAPTCHA_SOLVE))
    markup.add(KeyboardButton(TXT_WITHDRAW), KeyboardButton(TXT_SETTINGS))

    for btn_name in data.get("custom_buttons", {}).keys():
        markup.add(KeyboardButton(btn_name))

    if int(user_id) == ADMIN_ID:
        markup.add(KeyboardButton(TXT_ADMIN))

    return markup

def get_admin_inline_menu():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        make_inline_button("📢 Set Force Join", callback_data="adm_force_join", style="primary"),
        make_inline_button("🎁 Set Ref Bonus", callback_data="adm_set_ref_bonus", style="success")
    )
    markup.add(
        make_inline_button("💳 Set Min Withdraw", callback_data="adm_set_min_withdraw", style="primary"),
        make_inline_button("⌨️ Set Captcha Earn", callback_data="adm_set_captcha_earn", style="success")
    )
    markup.add(
        make_inline_button("💸 Pending Withdrawals", callback_data="adm_pending_withdraws", style="primary"),
        make_inline_button("🚫 Ban/Unban User", callback_data="adm_ban_unban", style="danger")
    )
    markup.add(
        make_inline_button("🛡️ Anti-Fraud Toggle", callback_data="adm_toggle_fraud", style="primary"),
        make_inline_button("📢 Smart Broadcast", callback_data="adm_broadcast_menu", style="primary")
    )
    markup.add(
        make_inline_button("➕ Add Balance", callback_data="adm_add_bal", style="success"),
        make_inline_button("➖ Cut Balance", callback_data="adm_cut_bal", style="danger")
    )
    markup.add(
        make_inline_button("📊 Live Dashboard", callback_data="adm_stats", style="primary"),
        make_inline_button("🔴 Maintenance Mode", callback_data="adm_maint", style="danger")
    )
    markup.add(
        make_inline_button("📁 Database Export", callback_data="adm_export", style="primary"),
        make_inline_button("📝 Edit Text Messages", callback_data="adm_edit_texts", style="primary")
    )
    markup.add(
        make_inline_button("🎁 Set Daily Bonus Range", callback_data="adm_set_daily_range", style="success"),
        make_inline_button("📢 Payment Channel", callback_data="adm_pay_channel", style="primary")
    )
    markup.add(
        make_inline_button("❌ Close Panel", callback_data="adm_close", style="danger")
    )
    return markup

# ============================================
# --- START COMMAND HANDLER ---
# ============================================
@bot.message_handler(commands=['start'])
def start_cmd(message):
    user_id = message.from_user.id
    data = load_db()

    if data.get("maintenance_mode") and int(user_id) != ADMIN_ID:
        bot.send_message(message.chat.id, "🔴 <b>বট বর্তমানে মেইনটেন্যান্স মোডে আছে। কিছুক্ষণ পর আবার চেষ্টা করুন।</b>", parse_mode="HTML")
        return

    if str(user_id) in data.get("banned_users", []):
        bot.send_message(message.chat.id, "⛔ আপনি এই বটে ব্লকড আছেন।")
        return

    user = get_user(user_id, message.from_user.first_name, message.from_user.username or "")
    update_user(user_id, "state", None)

    args = message.text.split()
    if len(args) > 1 and user.get("referred_by") is None:
        ref_id = args[1]
        # Fake / Self-Referral Detection (প্রিভেন্টিভ সিকিউরিটি)
        if ref_id != str(user_id) and ref_id in data["users"]:
            # অ্যান্টি-ফ্রড টগল অন থাকলে একই আইপি বা ডিভাইস চেক করা যায়, এখানে সেলফ রেফার ব্লক করা হলো
            update_user(user_id, "referred_by", ref_id)

    left = check_force_join(user_id)
    if left:
        msg = f"👋 <b>Welcome to {BOT_NAME}!</b>\n\nবটটি ব্যবহার করতে নিচের চ্যানেলগুলোতে জয়েন করুন এবং <b>Verify Now</b> বাটনে ক্লিক করুন:"
        bot.send_message(message.chat.id, msg, parse_mode="HTML", reply_markup=get_force_join_markup(left))
        return

    bot.send_message(message.chat.id, f"✅ <b>স্বাগতম!</b>\n\n{data['sys_texts']['welcome']}", parse_mode="HTML", reply_markup=get_main_menu(user_id))

# ============================================
# --- MAIN CALLBACK HANDLER ---
# ============================================
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id
    data = load_db()

    if call.data == "verify_join":
        left = check_force_join(user_id)
        if left:
            bot.answer_callback_query(call.id, "❌ আপনি এখনো সব চ্যানেলে জয়েন করেননি!", show_alert=True)
            return

        with db_lock:
            data = load_db()
            user = get_user(user_id)
            if user.get("referred_by") and not user.get("ref_rewarded"):
                ref_id = str(user["referred_by"])
                if ref_id != str(user_id) and ref_id in data["users"]: # সেলফ রেফারেল চেক সিকিউরিটি
                    bonus = data.get("ref_bonus_verify", 0.40)
                    data["users"][ref_id]["balance"] += bonus
                    data["users"][ref_id]["total_ref_bonus"] += bonus
                    data["users"][ref_id]["referrals"] += 1
                    data["users"][ref_id]["referral_list"].append({
                        "id": user_id,
                        "name": call.from_user.first_name,
                        "username": call.from_user.username or ""
                    })
                    data["users"][str(user_id)]["ref_rewarded"] = True
                    add_transaction(ref_id, "referral_bonus", bonus, f"Referral reward for user {user_id}")
                    save_db(data)
                    try:
                        bot.send_message(ref_id, f"🎉 <b>New Referral Verification!</b>\nআপনি রেফার বোনাস <b>৳{bonus}</b> পেয়েছেন!", parse_mode="HTML")
                    except Exception as e:
                        pass

        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception as e:
            pass

        bot.send_message(call.message.chat.id, f"✅ <b>ভেরিফিকেশন সফল হয়েছে!</b>\n\n{data['sys_texts']['welcome']}", parse_mode="HTML", reply_markup=get_main_menu(user_id))

    # Multi-Language Backend Handler
    elif call.data == "set_lang_bn":
        update_user(user_id, "lang", "bn")
        bot.answer_callback_query(call.id, "🇧🇩 ভাষা সফলভাবে বাংলা সেট করা হয়েছে!")
        try:
            bot.edit_message_text("⚙️ <b>Settings Updated:</b> ভাষা বাংলা সিলেক্ট করা হয়েছে।", call.message.chat.id, call.message.message_id, parse_mode="HTML")
        except:
            pass

    elif call.data == "set_lang_en":
        update_user(user_id, "lang", "en")
        bot.answer_callback_query(call.id, "🇬🇧 Language successfully set to English!")
        try:
            bot.edit_message_text("⚙️ <b>Settings Updated:</b> English language selected.", call.message.chat.id, call.message.message_id, parse_mode="HTML")
        except:
            pass

    elif call.data == "claim_daily_bonus":
        with db_lock:
            data = load_db()
            user = get_user(user_id)
            today_str = get_dhaka_today_str()

            if user.get("last_bonus_date") == today_str:
                bot.answer_callback_query(call.id, "❌ আপনি আজ ইতিমধ্যেই ডেইলি বোনাস ক্লেইম করেছেন!", show_alert=True)
                return

            b_amt = data.get("daily_bonus_amount", 5.0)
            data["users"][str(user_id)]["balance"] += b_amt
            data["users"][str(user_id)]["last_bonus_date"] = today_str
            add_transaction(user_id, "daily_bonus", b_amt, "Daily Bonus Reward")
            save_db(data)

        bot.answer_callback_query(call.id, f"🎉 আপনি ৳{b_amt} ডেইলি বোনাস ক্লেইম করেছেন!", show_alert=True)
        bot.send_message(call.message.chat.id, f"🎉 <b>দৈনিক বোনাস সফলভাবে অ্যাকাউন্টে যোগ করা হয়েছে: ৳{b_amt}</b>", parse_mode="HTML")

    elif call.data.startswith("withdraw_method_"):
        method = call.data.replace("withdraw_method_", "").upper()
        update_user(user_id, "state", "enter_bdt_number")
        with db_lock:
            data = load_db()
            data["users"][str(user_id)]["temp_data"]["withdraw_method"] = method
            save_db(data)
        bot.send_message(call.message.chat.id, f"📱 আপনার <b>{method}</b> অ্যাকাউন্ট নাম্বারটি লিখুন:", parse_mode="HTML")

    elif call.data == "refresh_wallet":
        user = get_user(user_id)
        banner_buf = generate_wallet_banner(user['name'], user['balance'], user['referrals'], user['total_withdraw'])
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except:
            pass
        bot.send_photo(call.message.chat.id, banner_buf, caption=f"👤 <b>Account Details Dashboard</b>\n\n🆔 চ্যাট আইডি: <code>{user_id}</code>\n💰 ব্যালেন্স: <b>৳{user['balance']:.2f}</b>", parse_mode="HTML")
        bot.answer_callback_query(call.id, "✅ রিফ্রেশ করা হয়েছে!")

    # ==================== ADMIN INLINE CALLBACKS ====================
    elif call.data.startswith("adm_") and int(user_id) == ADMIN_ID:
        act = call.data.replace("adm_", "")

        if act == "close":
            try:
                bot.delete_message(call.message.chat.id, call.message.message_id)
            except Exception as e:
                pass

        elif act == "force_join":
            markup = InlineKeyboardMarkup(row_width=2)
            markup.add(
                make_inline_button("➕ Add Channel", callback_data="adm_add_ch", style="success"),
                make_inline_button("🗑️ Remove Channel", callback_data="adm_rem_ch", style="danger")
            )
            bot.send_message(call.message.chat.id, f"📢 <b>Force Join Channels:</b>\n<code>{data.get('force_channels', [])}</code>", parse_mode="HTML", reply_markup=markup)

        elif act == "add_ch":
            update_user(user_id, "state", "adm_input_add_ch")
            bot.send_message(call.message.chat.id, "চ্যানেল ইউজারনেম সেন্ড করুন (যেমন: `@mychannel`):")

        elif act == "rem_ch":
            update_user(user_id, "state", "adm_input_rem_ch")
            bot.send_message(call.message.chat.id, "যে চ্যানেল সরাতে চান তার ইউজারনেম সেন্ড করুন:")

        elif act == "set_ref_bonus":
            update_user(user_id, "state", "adm_set_ref_bonus_val")
            bot.send_message(call.message.chat.id, "নতুন রেফার বোনাস অ্যামাউন্ট লিখুন:")

        elif act == "set_min_withdraw":
            update_user(user_id, "state", "adm_set_min_w_val")
            bot.send_message(call.message.chat.id, "নতুন মিনিমাম উইথড্র অ্যামাউন্ট লিখুন:")

        elif act == "set_captcha_earn":
            update_user(user_id, "state", "adm_set_captcha_earn_val")
            bot.send_message(call.message.chat.id, "Captcha Earn সেট করতে লিখুন:\n`RATE LIMIT`", parse_mode="Markdown")

        elif act == "pending_withdraws":
            withs = data.get("pending_withdraws", {})
            if not withs:
                bot.send_message(call.message.chat.id, "✅ কোনো পেন্ডিং উইথড্র নেই!")
                return
            for w_key, item in list(withs.items()):
                if item.get("status", "pending") != "pending":
                    continue
                markup = InlineKeyboardMarkup(row_width=2)
                markup.add(
                    make_inline_button("✅ Approve", callback_data=f"appr_with_{w_key}", style="success"),
                    make_inline_button("❌ Reject", callback_data=f"rej_with_{w_key}", style="danger")
                )
                msg_txt = (f"💸 <b>Withdrawal Request!</b>\n"
                           f"ID: <code>{w_key}</code>\n"
                           f"User ID: <code>{item['user_id']}</code>\n"
                           f"Method: <b>{item['method']}</b>\n"
                           f"Number: <code>{item['number']}</code>\n"
                           f"Amount: <b>৳{item['amount']:.2f}</b>")
                bot.send_message(call.message.chat.id, msg_txt, parse_mode="HTML", reply_markup=markup)

        elif act == "ban_unban":
            update_user(user_id, "state", "adm_ban_unban_val")
            bot.send_message(call.message.chat.id, "Ban বা Unban করতে ইউজারের ID সেন্ড করুন:")

        elif act == "toggle_fraud":
            with db_lock:
                data = load_db()
                data["anti_fraud_enabled"] = not data.get("anti_fraud_enabled", True)
                save_db(data)
                st = "ON ✅" if data["anti_fraud_enabled"] else "OFF 🔴"
            bot.send_message(call.message.chat.id, f"🛡️ Anti-Fraud Guard: {st}")

        elif act == "broadcast_menu":
            markup = InlineKeyboardMarkup(row_width=1)
            markup.add(
                make_inline_button("📢 Smart CTA Broadcast", callback_data="adm_bcast_text", style="primary")
            )
            bot.send_message(call.message.chat.id, "📢 <b>Advanced Broadcast Panel:</b>", parse_mode="HTML", reply_markup=markup)

        elif act == "bcast_text":
            update_user(user_id, "state", "adm_input_bcast_text")
            bot.send_message(call.message.chat.id, "ব্রডকাস্ট মেসেজটি সেন্ড করুন (সৈজন্যে কল-টু-অ্যাকশন বাটন যুক্ত করার জন্য মেসেজের নিচে `||BUTTON_TEXT|URL` ফরম্যাটে দিতে পারেন):")

        elif act == "add_bal":
            update_user(user_id, "state", "adm_add_bal_val")
            bot.send_message(call.message.chat.id, "লিখুন: `USER_ID AMOUNT`", parse_mode="Markdown")

        elif act == "cut_bal":
            update_user(user_id, "state", "adm_cut_bal_val")
            bot.send_message(call.message.chat.id, "লিখুন: `USER_ID AMOUNT`", parse_mode="Markdown")

        elif act == "stats":
            msg = (f"📊 <b>Live Analytics Dashboard</b>\n\n"
                   f"👥 Total Registered Users: {len(data['users'])}\n"
                   f"💸 Pending Withdrawals: {len(data['pending_withdraws'])}\n"
                   f"🚫 Banned Users: {len(data['banned_users'])}")
            bot.send_message(call.message.chat.id, msg, parse_mode="HTML")

        elif act == "maint":
            with db_lock:
                data = load_db()
                data["maintenance_mode"] = not data["maintenance_mode"]
                save_db(data)
                st = "চালু (ON) 🔴" if data["maintenance_mode"] else "বন্ধ (OFF) 🟢"
            bot.send_message(call.message.chat.id, f"🔴 Maintenance Mode: {st}")

        elif act == "export":
            if os.path.exists(DATA_FILE):
                with open(DATA_FILE, "rb") as f:
                    bot.send_document(call.message.chat.id, f, caption="📁 Database JSON File")
            else:
                bot.send_message(call.message.chat.id, "❌ ডাটাবেস ফাইল পাওয়া যায়নি!")

        elif act == "edit_texts":
            update_user(user_id, "state", "adm_edit_texts_val")
            bot.send_message(call.message.chat.id, "টেক্সট টাইপ সিলেক্ট করে লিখুন:\n`TYPE TEXT`\n(Types: welcome, refer_rules, help_text)", parse_mode="Markdown")

        elif act == "set_daily_range":
            update_user(user_id, "state", "adm_set_daily_range_val")
            bot.send_message(call.message.chat.id, "ডেইলি বোনাসের পরিমাণ লিখুন:")

        elif act == "pay_channel":
            update_user(user_id, "state", "adm_pay_ch_val")
            bot.send_message(call.message.chat.id, "পেমেন্ট প্রুফ চ্যানেলের ইউজারনেম লিখুন (যেমন `@my_proofs`):")

    elif call.data.startswith("appr_with_") or call.data.startswith("rej_with_"):
        if int(user_id) != ADMIN_ID:
            return
        act = "appr" if call.data.startswith("appr_with_") else "rej"
        w_key = call.data.replace("appr_with_", "").replace("rej_with_", "")
        with db_lock:
            data = load_db()
            withs = data.get("pending_withdraws", {})
            if w_key in withs:
                item = withs[w_key]
                if item.get("status") != "pending":
                    bot.answer_callback_query(call.id, "⚠️ রিকোয়েস্টটি ইতিপূর্বে প্রোসেস করা হয়েছে!", show_alert=True)
                    return

                u_id = str(item["user_id"])
                amt = item["amount"]

                if act == "appr":
                    item["status"] = "approved"
                    data["users"][u_id]["total_withdraw"] += amt
                    bot.edit_message_text(f"✅ Withdrawal Paid (৳{amt}) to {item['number']} ({item['method']})", call.message.chat.id, call.message.message_id)
                    try:
                        bot.send_message(u_id, f"🎉 আপনার <b>৳{amt:.2f}</b> উইথড্র সফলভাবে পেমেন্ট করা হয়েছে!", parse_mode="HTML")
                    except Exception as e:
                        pass

                    pay_ch = data.get("payment_proof_channel", "")
                    if pay_ch:
                        try:
                            bot.send_message(pay_ch, f"🎉 <b>New Payment Paid Out!</b>\n\n👤 User: <code>{u_id}</code>\n💳 Method: <b>{item['method']}</b>\n📱 Number: <code>{item['number']}</code>\n💰 Amount: <b>৳{amt:.2f}</b>\n⚡ Status: Approved ✅", parse_mode="HTML")
                        except Exception as e:
                            pass
                else:
                    item["status"] = "rejected"
                    data["users"][u_id]["balance"] += amt
                    add_transaction(u_id, "withdraw_refund", amt, f"Withdrawal Refund for Request {w_key}")
                    bot.edit_message_text("❌ Withdrawal Cancelled & Refunded!", call.message.chat.id, call.message.message_id)
                    try:
                        bot.send_message(u_id, f"❌ আপনার <b>৳{amt:.2f}</b> উইথড্র বাতিল করা হয়েছে এবং ব্যালেন্স রিফান্ড করা হয়েছে।", parse_mode="HTML")
                    except Exception as e:
                        pass
                save_db(data)

# ============================================
# --- MAIN MESSAGE ROUTER ---
# ============================================
@bot.message_handler(func=lambda message: True, content_types=['text', 'photo'])
def handle_text_messages(message):
    user_id = message.from_user.id
    data = load_db()

    if data.get("maintenance_mode") and int(user_id) != ADMIN_ID:
        bot.send_message(message.chat.id, "🔴 <b>বট বর্তমানে মেইনটেন্যান্স মোডে আছে।</b>", parse_mode="HTML")
        return

    if str(user_id) in data.get("banned_users", []):
        bot.send_message(message.chat.id, "⛔ আপনি ব্লকড আছেন।")
        return

    user = get_user(user_id, message.from_user.first_name, message.from_user.username or "")
    txt = message.text.strip() if message.text else ""

    main_menu_buttons = [TXT_WALLET, TXT_REFER, TXT_DAILY_BONUS, TXT_CAPTCHA_SOLVE, TXT_WITHDRAW, TXT_SETTINGS, TXT_ADMIN]
    if txt in main_menu_buttons:
        update_user(user_id, "state", None)
        user = get_user(user_id)

    state = user.get("state")

    # Real-time Force Join Check
    left = check_force_join(user_id)
    if left and int(user_id) != ADMIN_ID:
        bot.send_message(message.chat.id, "⚠️ <b>আপনি আমাদের চ্যানেল থেকে লিভ নিয়েছেন! কাজ চালিয়ে যেতে আবার জয়েন করুন:</b>", parse_mode="HTML", reply_markup=get_force_join_markup(left))
        return

    # Captcha Earning Handler with Rate Limiting / Cooldown Protection (3 Seconds)
    if state == "user_solving_earning_captcha":
        current_time = time.time()
        last_time = user.get("last_captcha_time", 0.0)
        
        if current_time - last_time < 3.0:
            bot.send_message(message.chat.id, "⚠️ অত্যন্ত দ্রুত রিকোয়েস্ট! অনুগ্রহ করে অন্তত ৩ সেকেন্ড অপেক্ষা করুন।", reply_markup=get_main_menu(user_id))
            update_user(user_id, "state", None)
            return

        update_user(user_id, "last_captcha_time", current_time)
        ans = user.get("temp_data", {}).get("earn_captcha_ans", "")
        
        if txt.upper() == ans.upper():
            c_rate = data["tasks"]["captcha"]["rate"]
            with db_lock:
                d = load_db()
                d["users"][str(user_id)]["balance"] += c_rate
                today_str = get_dhaka_today_str()
                counts = d["users"][str(user_id)]["daily_task_counts"].get(today_str, {})
                counts["captcha"] = counts.get("captcha", 0) + 1
                d["users"][str(user_id)]["daily_task_counts"][today_str] = counts
                save_db(d)
                add_transaction(user_id, "captcha_earn", c_rate, "Solved Earning Captcha")
            update_user(user_id, "state", None)
            bot.send_message(message.chat.id, f"✅ <b>সঠিক ক্যাপচা!</b> আপনার ওয়ালেটে <b>৳{c_rate}</b> যোগ করা হয়েছে।", parse_mode="HTML", reply_markup=get_main_menu(user_id))
        else:
            update_user(user_id, "state", None)
            bot.send_message(message.chat.id, "❌ <b>ভুল কোড!</b> পুনরায় চেষ্টার জন্য বাটন প্রেস করুন।", parse_mode="HTML", reply_markup=get_main_menu(user_id))
        return

    # ==================== WITHDRAWAL FLOW STATES ====================
    if state == "enter_bdt_number":
        if len(txt) < 10 or not txt.isdigit():
            bot.send_message(message.chat.id, "❌ ইনভ্যালিড মোবাইল নাম্বার! সঠিক নাম্বার লিখুন:")
            return
        update_user(user_id, "state", "enter_bdt_amount")
        with db_lock:
            data = load_db()
            data["users"][str(user_id)]["temp_data"]["withdraw_number"] = txt
            save_db(data)
        bot.send_message(message.chat.id, "💵 <b>আপনার উইথড্র টাকার পরিমাণ (৳) লিখুন:</b>", parse_mode="HTML")
        return

    elif state == "enter_bdt_amount":
        try:
            amt = float(txt)
            min_w = data.get("min_withdraw", 50.0)

            if amt < min_w or amt > user["balance"]:
                bot.send_message(message.chat.id, f"❌ ইনভ্যালিড পরিমাণ! মিনিমাম উইথড্র ৳{min_w} এবং আপনার ব্যালেন্স: ৳{user['balance']:.2f}")
                return

            method = user["temp_data"].get("withdraw_method", "BKASH")
            number = user["temp_data"].get("withdraw_number", "")

            with db_lock:
                data = load_db()
                data["users"][str(user_id)]["balance"] -= amt
                w_key = f"w_{user_id}_{int(time.time())}"
                data["pending_withdraws"][w_key] = {
                    "user_id": user_id,
                    "method": method,
                    "number": number,
                    "amount": amt,
                    "status": "pending",
                    "time": time.strftime("%Y-%m-%d %H:%M:%S")
                }
                add_transaction(user_id, "withdraw_pending", -amt, f"Withdrawal request {w_key}")
                save_db(data)

            update_user(user_id, "state", None)

            try:
                adm_msg = (f"📥 <b>NEW BDT WITHDRAWAL REQUEST!</b>\n\n"
                           f"ID: <code>{w_key}</code>\n"
                           f"User ID: <code>{user_id}</code>\n"
                           f"Name: {user['name']}\n"
                           f"Method: <b>{method}</b>\n"
                           f"Number: <code>{number}</code>\n"
                           f"Amount: <b>৳{amt:.2f}</b>")
                markup = InlineKeyboardMarkup(row_width=2)
                markup.add(
                    make_inline_button("✅ Approve", callback_data=f"appr_with_{w_key}", style="success"),
                    make_inline_button("❌ Reject", callback_data=f"rej_with_{w_key}", style="danger")
                )
                bot.send_message(ADMIN_ID, adm_msg, parse_mode="HTML", reply_markup=markup)
            except Exception as e:
                logging.error(f"Failed to notify admin about withdrawal: {e}")

            bot.send_message(message.chat.id, "✅ <b>আপনার উইথড্র রিকোয়েস্ট সফলভাবে জমা হয়েছে!</b>", parse_mode="HTML", reply_markup=get_main_menu(user_id))
            return
        except ValueError:
            bot.send_message(message.chat.id, "❌ সঠিক সংখ্যা লিখুন:")
            return

    elif state == "user_submit_support_ticket":
        update_user(user_id, "state", None)
        try:
            bot.send_message(ADMIN_ID, f"📩 <b>New Support Ticket!</b>\nUser: <code>{user_id}</code> (@{user.get('username')})\nMessage: {txt}", parse_mode="HTML")
        except Exception as e:
            pass
        bot.send_message(message.chat.id, "✅ <b>আপনার সাপোর্ট টিকিট এডমিনের কাছে পাঠানো হয়েছে!</b>", parse_mode="HTML", reply_markup=get_main_menu(user_id))
        return

    # ==================== ADMIN INPUT STATES ====================
    if int(user_id) == ADMIN_ID and state:
        if state == "adm_input_add_ch":
            if txt.startswith("@"):
                with db_lock:
                    data = load_db()
                    data["force_channels"].append(txt)
                    save_db(data)
                bot.send_message(message.chat.id, f"✅ চ্যানেল যুক্ত হয়েছে: {txt}")
            else:
                bot.send_message(message.chat.id, "❌ চ্যানেল `@` দিয়ে শুরু হতে হবে।")
            update_user(user_id, "state", None)
            return

        elif state == "adm_input_rem_ch":
            with db_lock:
                data = load_db()
                if txt in data["force_channels"]:
                    data["force_channels"].remove(txt)
                    save_db(data)
                    bot.send_message(message.chat.id, f"🗑️ চ্যানেল রিমুভ হয়েছে: {txt}")
            update_user(user_id, "state", None)
            return

        elif state == "adm_set_ref_bonus_val":
            try:
                v = float(txt)
                with db_lock:
                    data = load_db()
                    data["ref_bonus_verify"] = v
                    save_db(data)
                bot.send_message(message.chat.id, f"✅ নতুন রেফার বোনাস: ৳{v}")
            except:
                bot.send_message(message.chat.id, "❌ সংখ্যা লিখুন।")
            update_user(user_id, "state", None)
            return

        elif state == "adm_set_min_w_val":
            try:
                v = float(txt)
                with db_lock:
                    data = load_db()
                    data["min_withdraw"] = v
                    save_db(data)
                bot.send_message(message.chat.id, f"✅ মিনিমাম উইথড্র: ৳{v}")
            except:
                bot.send_message(message.chat.id, "❌ সংখ্যা লিখুন।")
            update_user(user_id, "state", None)
            return

        elif state == "adm_set_captcha_earn_val":
            try:
                rate, lim = txt.split()
                with db_lock:
                    data = load_db()
                    data["tasks"]["captcha"] = {"rate": float(rate), "limit": int(lim), "desc": "Solve Math & Text Captchas"}
                    save_db(data)
                bot.send_message(message.chat.id, "✅ Captcha Task Updated!")
            except:
                bot.send_message(message.chat.id, "❌ ফরম্যাট: `RATE LIMIT`", parse_mode="Markdown")
            update_user(user_id, "state", None)
            return

        elif state == "adm_ban_unban_val":
            u_target = txt.strip()
            if u_target == str(ADMIN_ID):
                bot.send_message(message.chat.id, "❌ আপনি নিজেকে ব্যান করতে পারবেন না!")
                update_user(user_id, "state", None)
                return
            with db_lock:
                data = load_db()
                if u_target in data["banned_users"]:
                    data["banned_users"].remove(u_target)
                    bot.send_message(message.chat.id, f"🟢 User {u_target} Unbanned!")
                else:
                    data["banned_users"].append(u_target)
                    bot.send_message(message.chat.id, f"⛔ User {u_target} Banned!")
                save_db(data)
            update_user(user_id, "state", None)
            return

        elif state == "adm_input_bcast_text":
            succ, fail = 0, 0
            bcast_parts = txt.split("||")
            actual_msg = bcast_parts[0].strip()
            btn_markup = None
            
            if len(bcast_parts) > 1:
                try:
                    btn_info = bcast_parts[1].split("|")
                    btn_text = btn_info[0].strip()
                    btn_url = btn_info[1].strip()
                    btn_markup = InlineKeyboardMarkup()
                    btn_markup.add(make_inline_button(btn_text, url=btn_url, style="success"))
                except:
                    pass

            for uid in list(data["users"].keys()):
                try:
                    bot.send_message(int(uid), f"📢 <b>Broadcast Notice:</b>\n\n{actual_msg}", parse_mode="HTML", reply_markup=btn_markup)
                    succ += 1
                except Exception as e:
                    fail += 1
                time.sleep(0.05)
            bot.send_message(message.chat.id, f"✅ Broadcast sent!\nSuccess: {succ}\nFailed/Blocked: {fail}")
            update_user(user_id, "state", None)
            return

        elif state == "adm_add_bal_val":
            try:
                u_target, amt = txt.split()
                v_amt = float(amt)
                with db_lock:
                    data = load_db()
                    if u_target in data["users"]:
                        data["users"][u_target]["balance"] += v_amt
                        add_transaction(u_target, "admin_add", v_amt, "Added balance by Admin")
                        save_db(data)
                        bot.send_message(message.chat.id, f"✅ Added ৳{v_amt} to {u_target}")
            except:
                bot.send_message(message.chat.id, "❌ ফরম্যাট: `USER_ID AMOUNT`", parse_mode="Markdown")
            update_user(user_id, "state", None)
            return

        elif state == "adm_cut_bal_val":
            try:
                u_target, amt = txt.split()
                v_amt = float(amt)
                with db_lock:
                    data = load_db()
                    if u_target in data["users"]:
                        data["users"][u_target]["balance"] = max(0.0, data["users"][u_target]["balance"] - v_amt)
                        add_transaction(u_target, "admin_cut", -v_amt, "Cut balance by Admin")
                        save_db(data)
                        bot.send_message(message.chat.id, f"✅ Cut ৳{v_amt} from {u_target}")
            except:
                bot.send_message(message.chat.id, "❌ ফরম্যাট: `USER_ID AMOUNT`", parse_mode="Markdown")
            update_user(user_id, "state", None)
            return

        elif state == "adm_edit_texts_val":
            try:
                t_type, t_val = txt.split(" ", 1)
                with db_lock:
                    data = load_db()
                    if t_type in data["sys_texts"]:
                        data["sys_texts"][t_type] = t_val
                        save_db(data)
                        bot.send_message(message.chat.id, f"✅ Text '{t_type}' updated!")
            except:
                bot.send_message(message.chat.id, "❌ ফরম্যাট: `TYPE TEXT`", parse_mode="Markdown")
            update_user(user_id, "state", None)
            return

        elif state == "adm_set_daily_range_val":
            try:
                v = float(txt)
                with db_lock:
                    data = load_db()
                    data["daily_bonus_amount"] = v
                    save_db(data)
                bot.send_message(message.chat.id, f"✅ Daily Bonus set to ৳{v}")
            except:
                bot.send_message(message.chat.id, "❌ সংখ্যা লিখুন।")
            update_user(user_id, "state", None)
            return

        elif state == "adm_pay_ch_val":
            with db_lock:
                data = load_db()
                data["payment_proof_channel"] = txt.strip()
                save_db(data)
            bot.send_message(message.chat.id, f"✅ Payment Proof Channel set to {txt}")
            update_user(user_id, "state", None)
            return

    # ==================== MAIN MENU COMMANDS ====================
    if txt == TXT_WALLET:
        banner_buf = generate_wallet_banner(user['name'], user['balance'], user['referrals'], user['total_withdraw'])
        markup = InlineKeyboardMarkup()
        markup.add(make_inline_button("🔄 রিফ্রেশ করুন", callback_data="refresh_wallet", style="primary"))
        bot.send_photo(message.chat.id, banner_buf, caption=f"👤 <b>Account Details Dashboard</b>\n\n🆔 টেলিগ্রাম চ্যাট আইডি: <code>{user_id}</code>\n💰 মোট ব্যালেন্স: <b>৳{user['balance']:.2f}</b>", parse_mode="HTML", reply_markup=markup)

    elif txt == TXT_REFER:
        bot_uname = bot.get_me().username
        ref_link = f"https://t.me/{bot_uname}?start={user_id}"
        msg = (f"⚡ <b>Instant Referral Program</b>\n\n"
               f"👤 নাম: <b>{user['name']}</b>\n"
               f"👥 মোট রেফার: <b>{user['referrals']} জন</b>\n"
               f"🔗 রেফার লিংক:\n<code>{ref_link}</code>\n\n"
               f"📜 <b>রুলস:</b> {data['sys_texts']['refer_rules']}")

        markup = InlineKeyboardMarkup(row_width=2)
        share_tg = f"https://t.me/share/url?url={ref_link}&text=Join%20Bot%20and%20Earn!"
        share_wa = f"https://api.whatsapp.com/send?text=Join%20Bot%20and%20Earn:%20{ref_link}"
        markup.add(
            make_inline_button("📲 WhatsApp-শেয়ার", url=share_wa, style="success"),
            make_inline_button("✈️ Telegram-শেয়ার", url=share_tg, style="primary")
        )
        bot.send_message(message.chat.id, msg, parse_mode="HTML", reply_markup=markup)

    elif txt == TXT_DAILY_BONUS:
        markup = InlineKeyboardMarkup()
        markup.add(make_inline_button("🎁 Claim Daily Bonus", callback_data="claim_daily_bonus", style="success"))
        bot.send_message(message.chat.id, "🎁 <b>দৈনিক বোনাস ক্লেম করতে নিচের বাটনে চাপ দিন:</b>", parse_mode="HTML", reply_markup=markup)

    elif txt == TXT_CAPTCHA_SOLVE:
        today_str = get_dhaka_today_str()
        c_limit = data["tasks"]["captcha"].get("limit", 30)
        user_counts = user.get("daily_task_counts", {}).get(today_str, {})
        c_done = user_counts.get("captcha", 0)

        if c_done >= c_limit:
            bot.send_message(message.chat.id, "❌ <b>আজকের ক্যাপচা সীমা শেষ হয়ে গেছে! কাল আবার চেষ্টা করুন।</b>", parse_mode="HTML")
            return

        img_buf, c_code = generate_image_captcha()
        update_user(user_id, "state", "user_solving_earning_captcha")
        with db_lock:
            d = load_db()
            d["users"][str(user_id)]["temp_data"]["earn_captcha_ans"] = c_code
            save_db(d)
        bot.send_photo(message.chat.id, img_buf, caption=f"⌨️ <b>Earning Captcha Task ({c_done+1}/{c_limit}):</b>\n\nউপরে ছবিতে দেওয়া কোড বা অংকটির ফলাফল নিচে সঠিকভাবে লিখুন:", parse_mode="HTML")

    elif txt == TXT_WITHDRAW:
        min_w = data.get('min_withdraw', 50.0)
        bal = user['balance']
        
        progress_percent = min(100.0, (bal / min_w) * 100)
        filled_blocks = int(progress_percent // 10)
        empty_blocks = 10 - filled_blocks
        progress_bar = "█" * filled_blocks + "░" * empty_blocks
        
        msg = (f"📥 <b>BDT Withdrawal System</b>\n\n"
               f"💰 আপনার ব্যালেন্স: <b>৳{bal:.2f} BDT</b>\n"
               f"🎯 মিনিমাম উইথড্র: <b>৳{min_w} BDT</b>\n\n"
               f"📊 <b>প্রোগ্রেস:</b> [{progress_bar}] {progress_percent:.1f}%\n\n"
               f"নিচের মেথডগুলো থেকে আপনার পেমেন্ট মেথড সিলেক্ট করুন:")
        
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            make_inline_button("📱 বিকাশ (Bkash)", callback_data="withdraw_method_bkash", style="success"),
            make_inline_button("📱 নগদ (Nagad)", callback_data="withdraw_method_nagad", style="primary"),
            make_inline_button("📱 রকেট (Rocket)", callback_data="withdraw_method_rocket", style="primary"),
            make_inline_button("💳 USDT", callback_data="withdraw_method_usdt", style="success")
        )
        bot.send_message(message.chat.id, msg, parse_mode="HTML", reply_markup=markup)

    elif txt == TXT_SETTINGS:
        update_user(user_id, "state", "user_submit_support_ticket")
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            make_inline_button("🇧🇩 বাংলা", callback_data="set_lang_bn", style="primary"),
            make_inline_button("🇬🇧 English", callback_data="set_lang_en", style="primary")
        )
        bot.send_message(message.chat.id, f"⚙️ <b>Settings & Support</b>\n\n{data['sys_texts']['help_text']}\n\nআপনার কোনো বার্তা থাকলে নিচে টাইপ করুন:", parse_mode="HTML", reply_markup=markup)

    elif txt == TXT_ADMIN and int(user_id) == ADMIN_ID:
        bot.send_message(message.chat.id, "⚙️ <b>Admin Control Panel:</b>", parse_mode="HTML", reply_markup=get_admin_inline_menu())

    elif txt in data.get("custom_buttons", {}):
        resp = data["custom_buttons"][txt]
        bot.send_message(message.chat.id, f"🔘 <b>{txt}</b>\n\n{resp}", parse_mode="HTML")

# ============================================
# --- ENGINE START ---
# ============================================
if __name__ == "__main__":
    keep_alive()
    logging.info(f"🚀 {BOT_NAME} Engine Started Successfully on Render...")
    bot.infinity_polling(timeout=20, long_polling_timeout=10)
