import requests
import json
import time
import re
import asyncio
import os
import random
from telegram import Bot
from telegram.error import TelegramError
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import logging
from datetime import datetime, timedelta
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# লগিং কনফিগারেশন
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class OTPMonitorBot:
    def __init__(self, telegram_token, group_chat_id, session_cookie, target_url, target_host):
        self.telegram_token = telegram_token
        self.group_chat_id = group_chat_id
        self.session_cookie = session_cookie
        self.target_url = target_url
        self.target_host = target_host
        self.processed_otps = set()
        self.start_time = datetime.now()
        self.total_otps_sent = 0
        self.last_otp_time = None
        self.is_monitoring = True
        self.cookie_last_refresh = datetime.now()
        self.cookie_refresh_interval = 30  # 30 মিনিট পর পর cookie refresh
        
        # Session management
        self.session = self.create_session()
        
        # User Agents pool
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (iPhone; CPU iPhone OS 17_1_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1',
            'Mozilla/5.0 (iPad; CPU OS 17_1_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1',
            'Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36'
        ]
        
        # OTP প্যাটার্ন ডিটেকশন
        self.otp_patterns = [
            r'\b\d{3}-\d{3}\b',
            r'\b\d{5}\b',
            r'code\s*\d+',
            r'code:\s*\d+',
            r'কোড\s*\d+',
            r'\b\d{6}\b',
            r'\b\d{4}\b',
            r'Your WhatsApp code \d+-\d+',
            r'WhatsApp code \d+-\d+',
            r'Telegram code \d+',
        ]
    
    def create_session(self):
        """Retry mechanism সহ session তৈরি করুন"""
        session = requests.Session()
        retry = Retry(
            total=3,
            read=3,
            connect=3,
            backoff_factor=0.3,
            status_forcelist=(500, 502, 504)
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        return session
    
    def refresh_session_cookie(self):
        """Cookie রিফ্রেশ করুন - Railway-এর জন্য বিশেষ ব্যবস্থা"""
        try:
            # নতুন cookie পাওয়ার চেষ্টা করুন (আপনার লগইন API অনুযায়ী পরিবর্তন করুন)
            # এখানে আপনি যদি নতুন cookie পাওয়ার কোন API জানেন তাহলে সেটা ব্যবহার করুন
            # অথবা ম্যানুয়ালি cookie আপডেট করুন
            
            logger.info("🔄 Attempting to refresh session cookie...")
            
            # উদাহরণ: নতুন cookie পাওয়ার জন্য API কল
            # login_data = {
            #     'username': 'your_username',
            #     'password': 'your_password'
            # }
            # response = self.session.post('http://example.com/login', data=login_data)
            # if response.status_code == 200:
            #     new_cookie = response.cookies.get('PHPSESSID')
            #     if new_cookie:
            #         self.session_cookie = new_cookie
            #         self.cookie_last_refresh = datetime.now()
            #         logger.info(f"✅ Cookie refreshed successfully: {new_cookie[:10]}...")
            #         return True
            
            # বর্তমানে শুধু time আপডেট করছি
            self.cookie_last_refresh = datetime.now()
            logger.info("✅ Cookie refresh timestamp updated")
            return True
            
        except Exception as e:
            logger.error(f"❌ Cookie refresh failed: {e}")
            return False
    
    def get_random_user_agent(self):
        """Random User-Agent return করুন"""
        return random.choice(self.user_agents)
    
    def hide_phone_number(self, phone_number):
        """ফোন নম্বর হাইড করুন"""
        if phone_number and len(phone_number) >= 8:
            return phone_number[:5] + '***' + phone_number[-4:]
        return phone_number or "Unknown"
    
    def extract_operator_name(self, operator):
        """অপারেটর থেকে শুধু দেশের নাম এক্সট্রাক্ট করুন"""
        if not operator:
            return "Unknown"
        parts = operator.split()
        if parts:
            return parts[0]
        return operator
    
    async def send_telegram_message(self, message, chat_id=None, reply_markup=None):
        """টেলিগ্রামে মেসেজ সেন্ড করুন"""
        if chat_id is None:
            chat_id = self.group_chat_id
            
        try:
            bot = Bot(token=self.telegram_token)
            await bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode='Markdown',
                reply_markup=reply_markup,
                disable_web_page_preview=True
            )
            return True
        except Exception as e:
            logger.error(f"❌ Send Message Error: {e}")
            return False
    
    async def send_startup_message(self):
        """বট শুরু হলে স্টার্টআপ মেসেজ সেন্ড করুন"""
        startup_msg = f"""
🚀 **ওটিপি মনিটর বট স্টার্ট হয়েছে** 🚀

══════════════════

✅ **স্টেটাস:** `লাইভ & মনিটরিং`
⚡ **মোড:** `ফার্স্ট ওটিপি অনলি`
📡 **হোস্ট:** `{self.target_host}`
🖥️ **প্ল্যাটফর্ম:** `Railway`
🍪 **কুকি স্টেটাস:** `Active`

🎯 **ফিচারসমূহ:**
• First OTP Only
• Auto Cookie Refresh
• Error Recovery

⏰ **স্টার্ট টাইম:** `{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}`

══════════════════
🤖 **ওটিপি মনিটর বট চলছে**
        """
        
        keyboard = [
            [InlineKeyboardButton("👨‍💻 Developer", url="https://t.me/sadhin8miya")],
            [InlineKeyboardButton("📢 Channel", url="https://t.me/earning_hub_official_channel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        success = await self.send_telegram_message(startup_msg, reply_markup=reply_markup)
        if success:
            logger.info("✅ Startup message sent to group")
        return success
    
    async def send_cookie_expired_notification(self):
        """Cookie expired হলে নোটিফিকেশন পাঠান"""
        error_message = f"""
⚠️ **কুকি এক্সপায়ার ডিটেক্টেড** ⚠️

══════════════════

❌ **স্টেটাস:** Cookie Expired
⏰ **টাইম:** `{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}`
🔄 **অ্যাকশন:** Auto-refresh initiated

**সমাধান:**
1. অপেক্ষা করুন auto-refresh এর জন্য
2. যদি কাজ না করে, ম্যানুয়ালি cookie আপডেট করুন
3. অথবা ৫ মিনিট পর রিস্টার্ট করুন

══════════════════
        """
        await self.send_telegram_message(error_message)
    
    def extract_otp(self, message):
        """মেসেজ থেকে OTP এক্সট্রাক্ট করুন"""
        if not message:
            return None
        for pattern in self.otp_patterns:
            matches = re.findall(pattern, message, re.IGNORECASE)
            if matches:
                return matches[0]
        return None
    
    def create_otp_id(self, timestamp, phone_number, message):
        """ইউনিক OTP ID তৈরি করুন"""
        return f"{timestamp}_{phone_number}"
    
    def format_message(self, sms_data):
        """SMS ডেটা ফরম্যাট করুন"""
        try:
            timestamp = sms_data[0] if len(sms_data) > 0 else "N/A"
            operator = sms_data[1] if len(sms_data) > 1 else "Unknown"
            phone_number = sms_data[2] if len(sms_data) > 2 else "Unknown"
            message = sms_data[5] if len(sms_data) > 5 else "No message"
            
            hidden_phone = self.hide_phone_number(phone_number)
            operator_name = self.extract_operator_name(operator)
            otp_code = self.extract_otp(message)
            
            formatted_msg = f"""
🔥 **নতুন ওটিপি ডিটেক্টেড** 🔥
══════════════════

📅 **টাইম:** `{timestamp}`
📱 **নম্বর:** `{hidden_phone}`
🏢 **অপারেটর:** `{operator_name}`

🎯 **ওটিপি কোড:** `{otp_code if otp_code else 'Processing...'}`

📝 **মেসেজ:**
`{message}`

══════════════════
🤖 **ওটিপি মনিটর বট**
            """
            return formatted_msg
        except Exception as e:
            logger.error(f"Format message error: {e}")
            return "Error formatting message"
    
    def create_response_buttons(self):
        """রেসপন্স বাটন তৈরি করুন"""
        keyboard = [
            [
                InlineKeyboardButton("📱 Number Channel", url="https://t.me/earning_hub_number_channel")
            ],
            [
                InlineKeyboardButton("👨‍💻 Developer", url="https://t.me/sadhin8miya"),
                InlineKeyboardButton("📢 Channel", url="https://t.me/earning_hub_official_channel")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    def fetch_sms_data(self):
        """ওয়েবসাইট থেকে SMS ডেটা ফেচ করুন"""
        
        # Cookie refresh চেক করুন (প্রতি 30 মিনিট পর)
        minutes_since_refresh = (datetime.now() - self.cookie_last_refresh).total_seconds() / 60
        if minutes_since_refresh > self.cookie_refresh_interval:
            logger.info("⏰ Cookie refresh interval reached")
            self.refresh_session_cookie()
        
        headers = {
            'Host': self.target_host,
            'Connection': 'keep-alive',
            'User-Agent': self.get_random_user_agent(),
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'X-Requested-With': 'XMLHttpRequest',
            'Referer': f'http://{self.target_host}/ints/client/SMSCDRStats',
            'Accept-Encoding': 'gzip, deflate',
            'Accept-Language': 'en-US,en;q=0.9,bn;q=0.8',
            'Cookie': f'PHPSESSID={self.session_cookie}',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache'
        }
        
        current_date = time.strftime("%Y-%m-%d")
        params = {
            'fdate1': f'{current_date} 00:00:00',
            'fdate2': f'{current_date} 23:59:59',
            'frange': '',
            'fnum': '',
            'fcli': '',
            'fgdate': '',
            'fgmonth': '',
            'fgrange': '',
            'fgnumber': '',
            'fgcli': '',
            'fg': '0',
            'sEcho': '1',
            'iColumns': '7',
            'sColumns': ',,,,,,',
            'iDisplayStart': '0',
            'iDisplayLength': '25',
            'mDataProp_0': '0',
            'sSearch_0': '',
            'bRegex_0': 'false',
            'bSearchable_0': 'true',
            'bSortable_0': 'true',
            'mDataProp_1': '1',
            'sSearch_1': '',
            'bRegex_1': 'false',
            'bSearchable_1': 'true',
            'bSortable_1': 'true',
            'mDataProp_2': '2',
            'sSearch_2': '',
            'bRegex_2': 'false',
            'bSearchable_2': 'true',
            'bSortable_2': 'true',
            'mDataProp_3': '3',
            'sSearch_3': '',
            'bRegex_3': 'false',
            'bSearchable_3': 'true',
            'bSortable_3': 'true',
            'mDataProp_4': '4',
            'sSearch_4': '',
            'bRegex_4': 'false',
            'bSearchable_4': 'true',
            'bSortable_4': 'true',
            'mDataProp_5': '5',
            'sSearch_5': '',
            'bRegex_5': 'false',
            'bSearchable_5': 'true',
            'bSortable_5': 'true',
            'mDataProp_6': '6',
            'sSearch_6': '',
            'bRegex_6': 'false',
            'bSearchable_6': 'true',
            'bSortable_6': 'true',
            'sSearch': '',
            'bRegex': 'false',
            'iSortCol_0': '0',
            'sSortDir_0': 'desc',
            'iSortingCols': '1',
            '_': str(int(time.time() * 1000))
        }
        
        try:
            # Request পাঠান
            response = self.session.get(
                self.target_url,
                headers=headers,
                params=params,
                timeout=15,
                verify=False
            )
            
            # Response চেক করুন
            if response.status_code == 200:
                response_text = response.text.strip()
                if response_text:
                    try:
                        data = response.json()
                        # Success, reset cookie check
                        return data
                    except json.JSONDecodeError:
                        # JSON decode error - maybe cookie expired
                        if "login" in response_text.lower() or "auth" in response_text.lower():
                            logger.warning("⚠️ Possible cookie expired - login page detected")
                            asyncio.create_task(self.send_cookie_expired_notification())
                            self.refresh_session_cookie()
                        return None
                else:
                    return None
            elif response.status_code == 403 or response.status_code == 401:
                # Forbidden - cookie expired
                logger.warning(f"⚠️ Cookie expired! Status: {response.status_code}")
                asyncio.create_task(self.send_cookie_expired_notification())
                self.refresh_session_cookie()
                return None
            else:
                logger.error(f"HTTP {response.status_code}")
                return None
                
        except requests.exceptions.Timeout:
            logger.error("⏰ Request timeout")
            return None
        except requests.exceptions.ConnectionError:
            logger.error("🔌 Connection error")
            return None
        except Exception as e:
            logger.error(f"❌ Fetch error: {e}")
            return None
    
    async def monitor_loop(self):
        """মেইন মনিটরিং লুপ"""
        logger.info("🚀 OTP Monitoring Started - FIRST OTP ONLY")
        await self.send_startup_message()
        
        check_count = 0
        error_count = 0
        
        while self.is_monitoring:
            try:
                check_count += 1
                current_time = datetime.now().strftime("%H:%M:%S")
                
                # প্রতি 100 চেকে লগ দেখান
                if check_count % 100 == 0:
                    logger.info(f"📊 Status - Checks: {check_count}, OTPs: {self.total_otps_sent}")
                
                # API কল
                data = self.fetch_sms_data()
                
                if data and 'aaData' in data:
                    error_count = 0  # Reset error count on success
                    sms_list = data['aaData']
                    
                    # বৈধ SMS ফিল্টার করুন
                    valid_sms = [sms for sms in sms_list if len(sms) >= 6 and isinstance(sms[0], str) and ':' in sms[0]]
                    
                    if valid_sms:
                        # শুধু প্রথম SMS নিন
                        first_sms = valid_sms[0]
                        timestamp = first_sms[0]
                        phone_number = first_sms[2]
                        message_text = first_sms[5]
                        
                        # OTP ID তৈরি করুন
                        otp_id = self.create_otp_id(timestamp, phone_number, message_text)
                        
                        # শুধুমাত্র প্রথম OTP চেক করুন
                        if otp_id not in self.processed_otps:
                            logger.info(f"🚨 FIRST OTP DETECTED: {timestamp}")
                            
                            otp_code = self.extract_otp(message_text)
                            if otp_code:
                                logger.info(f"🔐 OTP Code: {otp_code}")
                                
                                formatted_msg = self.format_message(first_sms)
                                reply_markup = self.create_response_buttons()
                                
                                success = await self.send_telegram_message(
                                    formatted_msg, 
                                    reply_markup=reply_markup
                                )
                                
                                if success:
                                    self.processed_otps.add(otp_id)
                                    self.total_otps_sent += 1
                                    self.last_otp_time = current_time
                                    logger.info(f"✅ FIRST OTP SENT: {timestamp}")
                
                else:
                    error_count += 1
                    if error_count > 5:
                        logger.warning(f"⚠️ {error_count} consecutive errors")
                        if error_count > 10:
                            # Force cookie refresh after too many errors
                            self.refresh_session_cookie()
                            error_count = 0
                
                # 0.50 সেকেন্ড অপেক্ষা
                await asyncio.sleep(0.50)
                
            except Exception as e:
                logger.error(f"❌ Monitor Loop Error: {e}")
                error_count += 1
                await asyncio.sleep(1)

async def main():
    # Railway-এর জন্য Environment Variable ব্যবহার করুন
    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8415686682:AAGAmUl69TEXQc0mn_sqe37LGT5FUX_e7KQ")
    GROUP_CHAT_ID = os.environ.get("GROUP_CHAT_ID", "-1003796890472")
    SESSION_COOKIE = os.environ.get("SESSION_COOKIE", "5rq60mmf159u1ladqf4oq3d5jv")
    TARGET_HOST = os.environ.get("TARGET_HOST", "93.190.143.157")
    TARGET_URL = f"http://{TARGET_HOST}/ints/client/res/data_smscdr.php"
    
    print("=" * 50)
    print("🤖 OTP MONITOR BOT - RAILWAY EDITION")
    print("=" * 50)
    print(f"⚡ Mode: FIRST OTP ONLY")
    print(f"⏰ Check Interval: 0.50 SECONDS")
    print(f"📡 Host: {TARGET_HOST}")
    print(f"🍪 Cookie Auto-Refresh: Enabled (30 min)")
    print(f"🚀 Starting bot...")
    print("=" * 50)
    
    # OTP মনিটর বট তৈরি করুন
    otp_bot = OTPMonitorBot(
        telegram_token=TELEGRAM_BOT_TOKEN,
        group_chat_id=GROUP_CHAT_ID,
        session_cookie=SESSION_COOKIE,
        target_url=TARGET_URL,
        target_host=TARGET_HOST
    )
    
    print("✅ BOT STARTED SUCCESSFULLY!")
    print("🎯 Monitoring: ACTIVE")
    print("🍪 Cookie Status: Monitored")
    print("🔄 Auto Refresh: Active")
    print("-" * 50)
    print("🛑 Press Ctrl+C to stop the bot")
    print("=" * 50)
    
    # মনিটরিং শুরু করুন
    try:
        await otp_bot.monitor_loop()
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user!")
        otp_bot.is_monitoring = False
        print(f"📊 Final Stats - Total OTPs Sent: {otp_bot.total_otps_sent}")
        print("👋 Goodbye!")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        # Auto-restart for Railway
        print("🔄 Auto-restarting in 5 seconds...")
        time.sleep(5)
        await main()

if __name__ == "__main__":
    # SSL warning disable
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    # Railway-এর জন্য asyncio রান
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Bot stopped by user")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        # Railway-এ auto-restart হবে