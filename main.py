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
    def __init__(self, telegram_token, group_chat_id, session_cookie, target_url, target_host):
        self.telegram_token = telegram_token
        self.group_chat_id = group_chat_id
        self.session_cookie = session_cookie
        self.target_url = target_url
        self.target_host = target_host
        self.processed_otps = set()
        self.processed_count = 0  # memory নিয়ন্ত্রণের জন্য
        self.start_time = datetime.now()
        self.total_otps_sent = 0
        self.last_otp_time = None
        self.is_monitoring = True

        # OTP প্যাটার্ন — specific আগে, generic পরে
        self.otp_patterns = [
            r'#(\d{3}\s\d{3})',                # #209 658 (Instagram)
            r'(?<!\d)(\d{3})\s(\d{3})(?!\d)',  # 209 658 স্পেস দিয়ে
            r'(?<!\d)(\d{3})-(\d{3})(?!\d)',   # 209-658 dash দিয়ে
            r'code[:\s]+(\d{4,8})',             # code: 123456
            r'কোড[:\s]+(\d{4,8})',              # বাংলা কোড
            r'(?<!\d)(\d{6})(?!\d)',            # 6 ডিজিট
            r'(?<!\d)(\d{5})(?!\d)',            # 5 ডিজিট
            r'(?<!\d)(\d{4})(?!\d)',            # 4 ডিজিট
        ]

    def hide_phone_number(self, phone_number):
        phone_str = str(phone_number)
        if len(phone_str) >= 8:
            return phone_str[:5] + '***' + phone_str[-4:]
        return phone_str

    def extract_operator_name(self, operator):
        parts = str(operator).split()
        if parts:
            return parts[0]
        return str(operator)

    def escape_markdown(self, text):
        """Markdown special character escape করো যাতে Telegram error না দেয়"""
        text = str(text)
        # backtick-এর মধ্যে পাঠাব তাই শুধু backtick escape করলেই হবে
        return text.replace('`', "'")

    async def send_telegram_message(self, message, chat_id=None, reply_markup=None):
        if chat_id is None:
            chat_id = self.group_chat_id

        try:
            from telegram.request import HTTPXRequest
            request = HTTPXRequest(connect_timeout=30, read_timeout=30, write_timeout=30)
            bot = Bot(token=self.telegram_token, request=request)
            await bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode='Markdown',
                reply_markup=reply_markup,
                disable_web_page_preview=True
            )
            logger.info("✅ Telegram message sent successfully")
            return True
        except TelegramError as e:
            logger.info(f"❌ Telegram Error: {e}")
            print(f"❌ Telegram Error: {e}")
            return False
        except Exception as e:
            logger.info(f"❌ Send Message Error: {e}")
            print(f"❌ Send Message Error: {e}")
            return False

    async def send_startup_message(self):
        startup_msg = (
            "🚀 *ওটিপি মনিটর বট স্টার্ট হয়েছে* 🚀\n\n"
            "══════════════════\n\n"
            "✅ *স্টেটাস:* `লাইভ & মনিটরিং`\n"
            "⚡ *মোড:* `ফার্স্ট ওটিপি অনলি`\n"
            f"📡 *হোস্ট:* `{self.target_host}`\n\n"
            f"⏰ *স্টার্ট টাইম:* `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n\n"
            "══════════════════\n"
            "🤖 *ওটিপি মনিটর বট চলছে*"
        )

        keyboard = [
            [InlineKeyboardButton("👨‍💻 Developer", url="https://t.me/sadhin8miya")],
            [InlineKeyboardButton("📢 Channel", url="https://t.me/earning_hub_official_channel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            success = await self.send_telegram_message(startup_msg, reply_markup=reply_markup)
            if success:
                logger.info("✅ Startup message sent to group")
        except Exception as e:
            logger.info(f"⚠️ Startup message failed (monitoring will continue): {e}")

    def extract_otp(self, message):
        """মেসেজ থেকে OTP এক্সট্রাক্ট — timestamp/date বাদ দিয়ে"""
        cleaned = re.sub(r'\d{4}-\d{2}-\d{2}', '', str(message))
        cleaned = re.sub(r'\d{2}:\d{2}:\d{2}', '', cleaned)

        for pattern in self.otp_patterns:
            matches = re.findall(pattern, cleaned)
            if matches:
                match = matches[0]
                if isinstance(match, tuple):
                    return ' '.join(m for m in match if m)
                return match
        return None

    def create_otp_id(self, timestamp, phone_number, otp_code=''):
        return f"{timestamp}_{phone_number}_{otp_code}"

    def format_message(self, sms_data, message_text, otp_code):
        timestamp  = self.escape_markdown(sms_data[0])
        operator   = self.escape_markdown(self.extract_operator_name(sms_data[1]))
        phone      = self.escape_markdown(self.hide_phone_number(sms_data[2]))
        service    = self.escape_markdown(sms_data[3] if len(sms_data) > 3 else 'Unknown')
        msg        = self.escape_markdown(message_text)
        code       = self.escape_markdown(otp_code) if otp_code else 'N/A'

        return (
            "🔥 *নতুন ওটিপি ডিটেক্টেড* 🔥\n"
            "══════════════════\n\n"
            f"📅 *টাইম:* `{timestamp}`\n"
            f"📱 *নম্বর:* `{phone}`\n"
            f"🏢 *অপারেটর:* `{operator}`\n"
            f"🌐 *সার্ভিস:* `{service}`\n\n"
            f"🎯 *ওটিপি কোড:* `{code}`\n\n"
            f"📝 *মেসেজ:*\n`{msg}`\n\n"
            "══════════════════\n"
            "🤖 *ওটিপি মনিটর বট*"
        )

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
            'User-Agent': 'Mozilla/5.0 (Linux; Android 16; 23129RN51X) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.7632.120 Mobile Safari/537.36',
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'X-Requested-With': 'XMLHttpRequest',
            'Referer': f'http://{self.target_host}/ints/client/SMSCDRStats',
            'Accept-Encoding': 'gzip, deflate',
            'Accept-Language': 'en-US,en;q=0.9',
            'Cookie': f'PHPSESSID={self.session_cookie}'
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
            'iSortCol_0': '0', 'sSortDir_0': 'desc', 'iSortingCols': '1',
            '_': str(int(time.time() * 1000))
        }

        try:
            response = requests.get(
                self.target_url,
                headers=headers,
                params=params,
                timeout=10,
                verify=False
            )

            if response.status_code == 200:
                if response.text.strip():
                    try:
                        return response.json()
                    except json.JSONDecodeError:
                        logger.error(f"JSON decode error: {response.text[:200]}")
                        return None
                else:
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

                    valid_sms = [
                        sms for sms in sms_list
                        if len(sms) >= 6
                        and isinstance(sms[0], str)
                        and ':' in sms[0]
                    ]

                    if valid_sms:
                        first_sms = valid_sms[0]
                        timestamp = first_sms[0]
                        phone_number = str(first_sms[2])

                        # index 0,1,2,3 skip — শুধু SMS body field থেকে OTP খোঁজো
                        message_text = ""
                        otp_code = None
                        for i, field in enumerate(first_sms):
                            if i <= 3:
                                continue  # timestamp, operator, phone, service skip
                            if isinstance(field, str) and len(field) > 3 and field.strip() not in ('$', '', '-'):
                                found = self.extract_otp(field)
                                if found:
                                    message_text = field
                                    otp_code = found
                                    logger.info(f"📍 OTP found at index {i}: {field[:80]}")
                                    break

                        # fallback
                        if not message_text:
                            message_text = str(first_sms[5]) if len(first_sms) > 5 else ""

                        otp_id = self.create_otp_id(timestamp, phone_number, otp_code or '')

                        if otp_id not in self.processed_otps:
                            logger.info(f"🚨 FIRST OTP DETECTED: {timestamp}")

                            if otp_code:
                                logger.info(f"🔐 OTP Code: {otp_code}")

                                formatted_msg = self.format_message(first_sms, message_text, otp_code)
                                reply_markup = self.create_response_buttons()

                                success = await self.send_telegram_message(
                                    formatted_msg,
                                    reply_markup=reply_markup
                                )

                                # success বা fail যাই হোক processed-এ add করো
                                self.processed_otps.add(otp_id)
                                self.processed_count += 1

                                if self.processed_count >= 1000:
                                    self.processed_otps.clear()
                                    self.processed_count = 0
                                    logger.info("🧹 Processed OTPs cache cleared")

                                if success:
                                    self.total_otps_sent += 1
                                    self.last_otp_time = current_time
                                    logger.info(f"✅ OTP SENT: {timestamp} - Total: {self.total_otps_sent}")
                                else:
                                    logger.info(f"❌ Telegram send failed: {timestamp}")
                            else:
                                self.processed_otps.add(otp_id)
                                logger.info(f"⚠️ OTP not found. Full data: {first_sms}")
                        else:
                            logger.debug(f"⏩ Already Processed: {timestamp}")
                    else:
                        logger.info("ℹ️ No valid SMS records found")
                else:
                    logger.warning("⚠️ No data from API")

                if check_count % 20 == 0:
                    logger.info(f"📊 Status - Total OTPs Sent: {self.total_otps_sent}")

                await asyncio.sleep(0.50)

            except Exception as e:
                logger.error(f"❌ Monitor Loop Error: {e}")
                print(f"❌ Monitor Loop Error: {e}")
                await asyncio.sleep(1)


async def main():
    TELEGRAM_BOT_TOKEN = "8415686682:AAGAmUl69TEXQc0mn_sqe37LGT5FUX_e7KQ"
    GROUP_CHAT_ID = "-1003796890472"
    SESSION_COOKIE = "5rq60mmf159u1ladqf4oq3d5jv"
    TARGET_HOST = "93.190.143.157"
    TARGET_URL = f"http://{TARGET_HOST}/ints/client/res/data_smscdr.php"

    print("=" * 50)
    print("🤖 OTP MONITOR BOT - FIRST OTP ONLY")
    print("=" * 50)
    print(f"📡 Host: {TARGET_HOST}")
    print("📱 Group ID:", GROUP_CHAT_ID)
    print("🚀 Starting bot...")

    otp_bot = OTPMonitorBot(
        telegram_token=TELEGRAM_BOT_TOKEN,
        group_chat_id=GROUP_CHAT_ID,
        session_cookie=SESSION_COOKIE,
        target_url=TARGET_URL,
        target_host=TARGET_HOST
    )

    print("✅ BOT STARTED SUCCESSFULLY!")
    print("🛑 Press Ctrl+C to stop")
    print("=" * 50)

    try:
        await otp_bot.monitor_loop()
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user!")
        otp_bot.is_monitoring = False
        print(f"📊 Total OTPs Sent: {otp_bot.total_otps_sent}")


if __name__ == "__main__":
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    asyncio.run(main())
