import requests
import json
import time
import re
import asyncio
from telegram import Bot
from telegram.error import TelegramError
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import logging
from datetime import datetime

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class OTPMonitorBot:
    def __init__(self, telegram_token, group_chat_id, username, password, target_url, target_host):
        self.telegram_token = telegram_token
        self.group_chat_id = group_chat_id
        self.username = username
        self.password = password
        self.target_url = target_url
        self.target_host = target_host
        self.processed_otps = set()
        self.start_time = datetime.now()
        self.total_otps_sent = 0
        self.last_otp_time = None
        self.is_monitoring = True
        self.session = requests.Session()

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

    def get_captcha_answer(self, html):
        """HTML থেকে ক্যাপচা উত্তর বের করুন"""
        patterns = [
            r'What is\s+(\d+)\s*\+\s*(\d+)',
            r'(\d+)\s*\+\s*(\d+)\s*=\s*\?',
            r'(\d+)\s*\+\s*(\d+)\s*=',
        ]
        for pat in patterns:
            match = re.search(pat, html, re.IGNORECASE)
            if match:
                a = int(match.group(1))
                b = int(match.group(2))
                answer = a + b
                logger.info(f"🔢 Captcha: {a} + {b} = {answer}")
                return answer

        logger.warning(f"⚠️ Captcha pattern পাওয়া যায়নি। HTML (first 600): {html[:600]}")
        return 16

    def login(self):
        """Username ও Password দিয়ে লগিন করুন"""
        try:
            # সম্ভাব্য login URL গুলো চেষ্টা
            possible_urls = [
                f"http://{self.target_host}/signin",
                f"http://{self.target_host}/login",
                f"http://{self.target_host}/ints/signin",
                f"http://{self.target_host}/ints/login",
                f"http://{self.target_host}/",
            ]

            login_page = None
            login_url = None
            for url in possible_urls:
                try:
                    resp = self.session.get(url, timeout=10, verify=False, allow_redirects=True)
                    if resp.status_code == 200 and ('password' in resp.text.lower()):
                        login_page = resp
                        login_url = url
                        logger.info(f"✅ Login page found: {url}")
                        break
                except Exception as e:
                    logger.debug(f"URL {url} failed: {e}")
                    continue

            if not login_page:
                logger.error("❌ কোনো login page পাওয়া যায়নি!")
                return False

            html = login_page.text

            # crlf hidden token
            crlf_value = ''
            crlf_match = re.search(r"name=['\"]crlf['\"]\s+value=['\"]([^'\"]*)['\"]", html)
            if not crlf_match:
                crlf_match = re.search(r"value=['\"]([^'\"]*)['\"][^>]*name=['\"]crlf['\"]", html)
            if crlf_match:
                crlf_value = crlf_match.group(1)
                logger.info(f"🔑 crlf token: {crlf_value}")

            # ক্যাপচা
            captcha_answer = self.get_captcha_answer(html)

            # Form action URL
            action_match = re.search(r"<form[^>]+action=['\"]([^'\"]+)['\"]", html, re.IGNORECASE)
            if action_match:
                action = action_match.group(1)
                if action.startswith('http'):
                    post_url = action
                elif action.startswith('/'):
                    post_url = f"http://{self.target_host}{action}"
                else:
                    post_url = f"http://{self.target_host}/{action}"
                logger.info(f"📋 Form POST URL: {post_url}")
            else:
                post_url = login_url
                logger.warning("⚠️ Form action পাওয়া যায়নি, login_url ব্যবহার হচ্ছে")

            payload = {
                'username': self.username,
                'password': self.password,
                'capt': str(captcha_answer),
                'crlf': crlf_value
            }

            headers = {
                'Host': self.target_host,
                'Content-Type': 'application/x-www-form-urlencoded',
                'Referer': login_url,
                'Origin': f'http://{self.target_host}',
                'User-Agent': 'Mozilla/5.0 (Linux; Android 16; 23129RN51X) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.7632.120 Mobile Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            }

            logger.info(f"📤 POST: {post_url} | user={self.username} | capt={captcha_answer}")

            response = self.session.post(
                post_url,
                data=payload,
                headers=headers,
                timeout=10,
                verify=False,
                allow_redirects=True
            )

            logger.info(f"📥 Response: {response.status_code} | URL: {response.url}")

            if response.status_code == 200:
                resp_lower = response.text.lower()
                if any(k in resp_lower for k in ['logout', 'dashboard', 'smscdr', 'signout']):
                    logger.info("✅ Login সফল হয়েছে!")
                    return True
                elif response.url != login_url and response.url != post_url:
                    logger.info(f"✅ Login সফল (redirect → {response.url})")
                    return True
                elif any(k in resp_lower for k in ['invalid', 'wrong', 'incorrect', 'failed']):
                    logger.error("❌ Login ব্যর্থ - username/password বা captcha ভুল")
                    return False
                else:
                    logger.warning("⚠️ Login অনিশ্চিত, চালিয়ে যাচ্ছি...")
                    return True
            else:
                logger.error(f"❌ Login HTTP Error: {response.status_code}")
                return False

        except Exception as e:
            logger.error(f"❌ Login Exception: {e}")
            return False

    def hide_phone_number(self, phone_number):
        if len(phone_number) >= 8:
            return phone_number[:5] + '***' + phone_number[-4:]
        return phone_number

    def extract_operator_name(self, operator):
        parts = operator.split()
        if parts:
            return parts[0]
        return operator

    async def send_telegram_message(self, message, chat_id=None, reply_markup=None):
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
        except TelegramError as e:
            logger.error(f"❌ Telegram Error: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Send Message Error: {e}")
            return False

    async def send_startup_message(self):
        startup_msg = f"""
🚀 **ওটিপি মনিটর বট স্টার্ট হয়েছে** 🚀

══════════════════

✅ **স্টেটাস:** `লাইভ & মনিটরিং`
⚡ **মোড:** `ফার্স্ট ওটিপি অনলি`
📡 **হোস্ট:** `{self.target_host}`
📋 **পাথ:** `/ints/client/res/data_smscdr.php`

🎯 **ফিচারসমূহ:**
• First OTP Only
• Live Monitoring
• Auto Detection

⏰ **স্টার্ট টাইম:** `{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}`

🔔 **নোট:** Only the FIRST OTP will be forwarded!

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
            logger.info("✅ Startup message sent")
        return success

    def extract_otp(self, message):
        for pattern in self.otp_patterns:
            matches = re.findall(pattern, message)
            if matches:
                return matches[0]
        return None

    def create_otp_id(self, timestamp, phone_number, message):
        return f"{timestamp}_{phone_number}"

    def format_message(self, sms_data):
        timestamp = sms_data[0]
        operator = sms_data[1]
        phone_number = sms_data[2]
        message = sms_data[5]

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

    def create_response_buttons(self):
        keyboard = [
            [InlineKeyboardButton("📱 Number Channel", url="https://t.me/earning_hub_number_channel")],
            [
                InlineKeyboardButton("👨‍💻 Developer", url="https://t.me/sadhin8miya"),
                InlineKeyboardButton("📢 Channel", url="https://t.me/earning_hub_official_channel")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)

    def fetch_sms_data(self):
        headers = {
            'Host': self.target_host,
            'Connection': 'keep-alive',
            'User-Agent': 'Mozilla/5.0 (Linux; Android 16; 23129RN51X Build/BP2A.250605.031.A3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.7632.120 Mobile Safari/537.36',
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'X-Requested-With': 'XMLHttpRequest',
            'Referer': f'http://{self.target_host}/ints/client/SMSCDRStats',
            'Accept-Encoding': 'gzip, deflate',
            'Accept-Language': 'en-US,en;q=0.9,bn-BD;q=0.1,bn;q=0.1',
        }

        current_date = time.strftime("%Y-%m-%d")
        params = {
            'fdate1': f'{current_date} 00:00:00',
            'fdate2': f'{current_date} 23:59:59',
            'frange': '', 'fnum': '', 'fcli': '',
            'fgdate': '', 'fgmonth': '', 'fgrange': '',
            'fgnumber': '', 'fgcli': '', 'fg': '0',
            'sEcho': '1', 'iColumns': '7', 'sColumns': ',,,,,,',
            'iDisplayStart': '0', 'iDisplayLength': '25',
            'mDataProp_0': '0', 'sSearch_0': '', 'bRegex_0': 'false',
            'bSearchable_0': 'true', 'bSortable_0': 'true',
            'mDataProp_1': '1', 'sSearch_1': '', 'bRegex_1': 'false',
            'bSearchable_1': 'true', 'bSortable_1': 'true',
            'mDataProp_2': '2', 'sSearch_2': '', 'bRegex_2': 'false',
            'bSearchable_2': 'true', 'bSortable_2': 'true',
            'mDataProp_3': '3', 'sSearch_3': '', 'bRegex_3': 'false',
            'bSearchable_3': 'true', 'bSortable_3': 'true',
            'mDataProp_4': '4', 'sSearch_4': '', 'bRegex_4': 'false',
            'bSearchable_4': 'true', 'bSortable_4': 'true',
            'mDataProp_5': '5', 'sSearch_5': '', 'bRegex_5': 'false',
            'bSearchable_5': 'true', 'bSortable_5': 'true',
            'mDataProp_6': '6', 'sSearch_6': '', 'bRegex_6': 'false',
            'bSearchable_6': 'true', 'bSortable_6': 'true',
            'sSearch': '', 'bRegex': 'false',
            'iSortCol_0': '0', 'sSortDir_0': 'desc',
            'iSortingCols': '1',
            '_': str(int(time.time() * 1000))
        }

        try:
            response = self.session.get(
                self.target_url,
                headers=headers,
                params=params,
                timeout=10,
                verify=False
            )

            # Session expired হলে আবার login
            if response.status_code in [401, 403] or ('login' in response.url.lower()):
                logger.warning("⚠️ Session expired, re-logging in...")
                if self.login():
                    response = self.session.get(
                        self.target_url,
                        headers=headers,
                        params=params,
                        timeout=10,
                        verify=False
                    )
                else:
                    return None

            if response.status_code == 200 and response.text.strip():
                try:
                    return response.json()
                except json.JSONDecodeError:
                    logger.error(f"JSON decode error: {response.text[:200]}")
                    return None
            else:
                logger.error(f"HTTP {response.status_code}")
                return None

        except requests.exceptions.RequestException as e:
            logger.error(f"Request error: {e}")
            return None
        except Exception as e:
            logger.error(f"Fetch error: {e}")
            return None

    async def monitor_loop(self):
        logger.info("🔐 Username/Password দিয়ে Login করছি...")

        if not self.login():
            logger.error("❌ Login ব্যর্থ হয়েছে! বট বন্ধ হচ্ছে।")
            return

        logger.info("🚀 OTP Monitoring Started - FIRST OTP ONLY")
        await self.send_startup_message()

        check_count = 0

        while self.is_monitoring:
            try:
                check_count += 1
                current_time = datetime.now().strftime("%H:%M:%S")
                logger.info(f"🔍 Check #{check_count} at {current_time}")

                data = self.fetch_sms_data()

                if data and 'aaData' in data:
                    sms_list = data['aaData']
                    valid_sms = [sms for sms in sms_list if len(sms) >= 6 and isinstance(sms[0], str) and ':' in sms[0]]

                    if valid_sms:
                        first_sms = valid_sms[0]
                        timestamp = first_sms[0]
                        phone_number = first_sms[2]
                        message_text = first_sms[5]

                        otp_id = self.create_otp_id(timestamp, phone_number, message_text)

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
                                    logger.info(f"✅ OTP SENT: {timestamp} - Total: {self.total_otps_sent}")
                                else:
                                    logger.error(f"❌ Failed to send OTP: {timestamp}")
                        else:
                            logger.debug(f"⏩ Already Processed: {timestamp}")
                    else:
                        logger.info("ℹ️ No valid SMS records found")
                else:
                    logger.warning("⚠️ No data from API")

                if check_count % 20 == 0:
                    logger.info(f"📊 Status - Total OTPs: {self.total_otps_sent}")

                await asyncio.sleep(0.50)

            except Exception as e:
                logger.error(f"❌ Monitor Loop Error: {e}")
                await asyncio.sleep(1)


async def main():
    TELEGRAM_BOT_TOKEN = "8415686682:AAGAmUl69TEXQc0mn_sqe37LGT5FUX_e7KQ"
    GROUP_CHAT_ID = "-1003796890472"
    USERNAME = "moynulislam473"
    PASSWORD = "moynulislam473"
    TARGET_HOST = "93.190.143.157"
    TARGET_URL = f"http://{TARGET_HOST}/ints/client/res/data_smscdr.php"

    print("=" * 50)
    print("🤖 OTP MONITOR BOT - USERNAME/PASSWORD LOGIN")
    print("=" * 50)
    print(f"👤 Username: {USERNAME}")
    print("⚡ Mode: FIRST OTP ONLY")
    print(f"📡 Host: {TARGET_HOST}")
    print("🚀 Starting bot...")

    otp_bot = OTPMonitorBot(
        telegram_token=TELEGRAM_BOT_TOKEN,
        group_chat_id=GROUP_CHAT_ID,
        username=USERNAME,
        password=PASSWORD,
        target_url=TARGET_URL,
        target_host=TARGET_HOST
    )

    print("🛑 Press Ctrl+C to stop")
    print("=" * 50)

    try:
        await otp_bot.monitor_loop()
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user!")
        otp_bot.is_monitoring = False
        print(f"📊 Total OTPs Sent: {otp_bot.total_otps_sent}")
        print("👋 Goodbye!")


if __name__ == "__main__":
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    asyncio.run(main())
