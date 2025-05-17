import os
import telegram
from telegram import ReplyKeyboardMarkup
from telegram.ext import Dispatcher, MessageHandler, CommandHandler, Filters
from flask import Flask, request
from docxtpl import DocxTemplate
from pydub import AudioSegment
from email.message import EmailMessage
import smtplib
from openai import OpenAI

# === Config ===
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
OPENAI_KEY = os.environ["OPENAI_KEY"]
EMAIL_SENDER = os.environ["EMAIL_SENDER"]
EMAIL_PASSWORD = os.environ["EMAIL_PASSWORD"]
EMAIL_RECEIVER = os.environ["EMAIL_RECEIVER"]

client = OpenAI(api_key=OPENAI_KEY)
bot = telegram.Bot(token=TELEGRAM_TOKEN)
app = Flask(__name__)
dispatcher = Dispatcher(bot, update_queue=None, workers=0, use_context=True)

# === User state ===
user_state = {}
expected_fields = [
    "Date", "Briefing", "Observations", "LocationObservations",
    "Examination", "Outcomes", "TechincalOpinion"
]
field_prompts = {
    "Date": "🎙️ أرسل تاريخ الواقعة.",
    "Briefing": "🎙️ أرسل ملخص الحادث.",
    "Observations": "🎙️ أرسل الملاحظات.",
    "LocationObservations": "🎙️ أرسل معاينة الموقع.",
    "Examination": "🎙️ أرسل نتيجة الفحص الفني.",
    "Outcomes": "🎙️ أرسل النتيجة.",
    "TechincalOpinion": "🎙️ أرسل الرأي الفني."
}

investigator_names = ["المقدم محمد علي القاسم", "النقيب عبدالله راشد ال علي","النقيب سليمان محمد الزرعوني", "الملازم أول أحمد خالد الشامسي", "العريف راشد محمد بن حسين" ,"المدني محمد ماهر العلي", "المدني امنه خالد المازمي", "المدني حمده ماجد ال علي", "المدني عمر محسن الزقري" ]

# === Transcribe voice to text ===
def transcribe(file_path):
    audio = AudioSegment.from_file(file_path)
    audio.export("converted.wav", format="wav")
    with open("converted.wav", "rb") as f:
        result = client.audio.transcriptions.create(model="whisper-1", file=f, language="ar")
    return result.text

# === Enhance input with GPT ===
def enhance_with_gpt(field_name, user_input):
    prompt = f"أعد صياغة {field_name} التالية مع استخدام أسلوب مهني وعربي فصيح دون ادراج اي نوع من المشاعر و ان يتم صياغة التاريخ بصيغة مماثلة للتالي 20/مايو/2025 و شكرا:\n\n{user_input}"
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content.strip()

# === Report generation ===
def generate_report(data):
    doc = DocxTemplate("police_report_template.docx")
    doc.render(data)
    doc.save("تقرير_التحقيق.docx")

def send_email():
    msg = EmailMessage()
    msg["Subject"] = "تقرير تحقيق تلقائي"
    msg["From"] = EMAIL_SENDER
    msg["To"] = EMAIL_RECEIVER
    msg.set_content("📎 يرجى مراجعة التقرير المرفق.")
    with open("تقرير_التحقيق.docx", "rb") as f:
        msg.add_attachment(
            f.read(),
            maintype="application",
            subtype="vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename="تقرير_التحقيق.docx"
        )
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(EMAIL_SENDER, EMAIL_PASSWORD)
        smtp.send_message(msg)

# === Handlers ===
def start(update, context):
    user_id = update.message.from_user.id
    user_state[user_id] = {"step": 0, "data": {}}
    keyboard = [[name] for name in investigator_names]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    update.message.reply_text(
        "👋 مرحباً بك في بوت إعداد تقارير الفحص الخاص بقسم الهندسة الجنائية.\n"
        "📌 أرسل ملاحظة صوتية عند كل طلب.\n"
        "🔄 لإعادة البدء من جديد أرسل /startover\n"
        "↩️ لإعادة إدخال الخطوة الحالية أرسل /repeat\n"
        "\n👇 اختر اسم الفاحص:",
        reply_markup=reply_markup
    )

def handle_text(update, context):
    user_id = update.message.from_user.id
    text = update.message.text.strip()

    if user_id in user_state and user_state[user_id]["step"] == 0:
        if text in investigator_names:
            user_state[user_id]["data"]["Investigator"] = text
            user_state[user_id]["step"] = 1
            next_field = expected_fields[0]
            update.message.reply_text(f"✅ تم تسجيل اسم الفاحص.\n{field_prompts[next_field]}")
        else:
            update.message.reply_text("❗ يرجى اختيار اسم الفاحص من الخيارات.")

def handle_voice(update, context):
    user_id = update.message.from_user.id

    if user_id not in user_state:
        start(update, context)
        return

    file = update.message.voice.get_file()
    file.download("voice.ogg")
    text = transcribe("voice.ogg")

    step = user_state[user_id]["step"]
    if step == 0:
        update.message.reply_text("❗ يرجى اختيار اسم الفاحص من القائمة أولاً.")
        return

    field = expected_fields[step - 1]
    enhanced = enhance_with_gpt(field, text)
    user_state[user_id]["data"][field] = enhanced

    if step < len(expected_fields):
        user_state[user_id]["step"] += 1
        next_field = expected_fields[step]
        update.message.reply_text(f"✅ تم تسجيل {field}.\n{field_prompts[next_field]}")
    else:
        generate_report(user_state[user_id]["data"])
        send_email()
        update.message.reply_text("📄 تم إنشاء التقرير وإرساله إلى البريد الإلكتروني.")
        del user_state[user_id]

def startover(update, context):
    start(update, context)

def repeat(update, context):
    user_id = update.message.from_user.id
    if user_id in user_state:
        step = user_state[user_id]["step"]
        if step == 0:
            update.message.reply_text("↩️ يرجى اختيار اسم الفاحص.")
        elif step <= len(expected_fields):
            field = expected_fields[step - 1]
            update.message.reply_text(f"↩️ أعد إرسال {field}:\n{field_prompts[field]}")
        else:
            update.message.reply_text("❗ لا توجد خطوة حالية لإعادتها.")
    else:
        update.message.reply_text("❗ لم تبدأ بعد. أرسل /start للبدء.")

# === Telegram setup ===
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(CommandHandler("startover", startover))
dispatcher.add_handler(CommandHandler("repeat", repeat))
dispatcher.add_handler(MessageHandler(Filters.voice, handle_voice))
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_text))

# === Webhook ===
@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def webhook():
    update = telegram.Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return "OK"

@app.route("/set_webhook", methods=["GET"])
def set_webhook():
    public_url = os.environ.get("RENDER_EXTERNAL_URL")
    if public_url:
        bot.set_webhook(f"{public_url}/{TELEGRAM_TOKEN}")
        return f"Webhook set to: {public_url}/{TELEGRAM_TOKEN}"
    return "Webhook not set."

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
