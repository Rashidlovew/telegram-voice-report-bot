import os
import telegram
from telegram import ReplyKeyboardMarkup
from telegram.ext import Dispatcher, MessageHandler, CommandHandler, Filters
from flask import Flask, request
from docxtpl import DocxTemplate
from docx.shared import Pt
from docx.oxml.ns import qn
from docx.enum.text import WD_PARAGRAPH_ALIGNMENT
from pydub import AudioSegment
from email.message import EmailMessage
import smtplib
from openai import OpenAI
from docx import Document

# === Config ===
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
OPENAI_KEY = os.environ["OPENAI_KEY"]
EMAIL_SENDER = os.environ["EMAIL_SENDER"]
EMAIL_PASSWORD = os.environ["EMAIL_PASSWORD"]

client = OpenAI(api_key=OPENAI_KEY)
bot = telegram.Bot(token=TELEGRAM_TOKEN)
app = Flask(__name__)
dispatcher = Dispatcher(bot, update_queue=None, workers=0, use_context=True)

# === Investigator options with their emails ===
investigator_emails = {
    "المقدم محمد علي القاسم": "mohammed@example.com",
    "النقيب عبدالله راشد ال علي": "abdullah@example.com",
    "النقيب سليمان محمد الزرعوني": "sulaiman@example.com",
    "الملازم أول أحمد خالد الشامسي": "ahmed@example.com",
    "العريف راشد محمد بن حسين": "rashed@example.com",
    "المدني محمد ماهر العلي": "maher@example.com",
    "المدني امنه خالد المازمي": "amna@example.com",
    "المدني حمده ماجد ال علي": "hamda@example.com",
    "المدني عمر محسن الزقري": "omar@example.com"
}
investigator_names = list(investigator_emails.keys())

# === Bot state ===
user_state = {}
expected_fields = [
    "Date", "Briefing", "LocationObservations",
    "Examination", "Outcomes", "TechincalOpinion"
]
field_prompts = {
    "Date": "🎙️ أرسل تاريخ الواقعة.",
    "Briefing": "🎙️ أرسل موجز الواقعة.",
    "LocationObservations": "🎙️ أرسل معاينة الموقع حيث بمعاينة موقع الحادث تبين ما يلي .....",
    "Examination": "🎙️ أرسل نتيجة الفحص الفني ... حيث بفحص موضوع الحادث تبين ما يلي .....",
    "Outcomes": "🎙️ أرسل النتيجة حيث أنه بعد المعاينة و أجراء الفحوص الفنية اللازمة تبين ما يلي:.",
    "TechincalOpinion": "🎙️ أرسل الرأي الفني."
}
field_names_ar = {
    "Date": "التاريخ",
    "Briefing": "ملخص الحادث",
    "LocationObservations": "معاينة الموقع",
    "Examination": "نتيجة الفحص الفني",
    "Outcomes": "النتيجة",
    "TechincalOpinion": "الرأي الفني"
}

# === Utilities ===
def transcribe(file_path):
    audio = AudioSegment.from_file(file_path)
    audio.export("converted.wav", format="wav")
    with open("converted.wav", "rb") as f:
        result = client.audio.transcriptions.create(model="whisper-1", file=f, language="ar")
    return result.text

def enhance_with_gpt(field_name, user_input):
    if field_name == "TechincalOpinion":
        prompt = (
            f"يرجى إعادة صياغة ({field_name}) التالية بطريقة مهنية وتحليلية، "
            f"وباستخدام لغة رسمية وعربية فصحى:\n\n{user_input}"
        )
    elif field_name == "Date":
        prompt = (
            f"يرجى صياغة تاريخ الواقعة بالتنسيق التالي فقط: 20/مايو/2025. النص:\n\n{user_input}"
        )
    else:
        prompt = (
            f"يرجى إعادة صياغة التالي ({field_name}) باستخدام أسلوب مهني وعربي فصيح، "
            f"مع تجنب المشاعر :\n\n{user_input}"
        )

    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content.strip()

def format_report_doc(path):
    doc = Document(path)
    for paragraph in doc.paragraphs:
        paragraph.paragraph_format.alignment = WD_PARAGRAPH_ALIGNMENT.RIGHT
        paragraph._element.set(qn("w:rtl"), "1")
        for run in paragraph.runs:
            run.font.name = "Dubai"
            run._element.rPr.rFonts.set(qn("w:eastAsia"), "Dubai")
            run.font.size = Pt(13)
    doc.save(path)

def generate_report(data):
    filename = f"تقرير_التحقيق_{data['Investigator'].replace(' ', '_')}.docx"
    doc = DocxTemplate("police_report_template.docx")
    doc.render(data)
    doc.save(filename)
    format_report_doc(filename)
    return filename

def send_email(file_path, recipient, investigator_name):
    msg = EmailMessage()
    msg["Subject"] = "تقرير تحقيق تلقائي"
    msg["From"] = EMAIL_SENDER
    msg["To"] = recipient
    msg.set_content(f"📎 يرجى مراجعة التقرير المرفق.\n\nمع تحيات فريق العمل، {investigator_name}.")
    with open(file_path, "rb") as f:
        msg.add_attachment(
            f.read(),
            maintype="application",
            subtype="vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename=os.path.basename(file_path)
        )
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(EMAIL_SENDER, EMAIL_PASSWORD)
        smtp.send_message(msg)

# === Bot Handlers ===
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
        "⬅️ للرجوع إلى الخطوة السابقة أرسل /stepBack\n"
        "\n👇 اختر اسم الفاحص:",
        reply_markup=reply_markup
    )

def handle_text(update, context):
    user_id = update.message.from_user.id
    if user_id not in user_state:
        start(update, context)
        return

    text = update.message.text.strip()
    if user_state[user_id]["step"] == 0:
        if text in investigator_names:
            user_state[user_id]["data"]["Investigator"] = text
            user_state[user_id]["step"] = 1
            next_field = expected_fields[0]
            update.message.reply_text(f"✅ تم تسجيل {field_names_ar[next_field]}.\n{field_prompts[next_field]}")
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
        update.message.reply_text(f"✅ تم تسجيل {field_names_ar[field]}.\n{field_prompts[next_field]}")
    else:
        investigator = user_state[user_id]["data"]["Investigator"]
        recipient_email = investigator_emails.get(investigator, EMAIL_SENDER)
        file_path = generate_report(user_state[user_id]["data"])
        send_email(file_path, recipient_email, investigator)
        update.message.reply_text(
            f"📄 تم إنشاء التقرير وإرساله إلى بريدك الإلكتروني .\n"
            f"✅ شكراً لاستخدامك البوت  {investigator}."
        )
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
            update.message.reply_text(f"↩️ أعد إرسال {field_names_ar[field]}:\n{field_prompts[field]}")
        else:
            update.message.reply_text("❗ لا توجد خطوة حالية لإعادتها.")
    else:
        update.message.reply_text("❗ لم تبدأ بعد. أرسل /start للبدء.")

def step_back(update, context):
    user_id = update.message.from_user.id
    if user_id in user_state and user_state[user_id]["step"] > 1:
        user_state[user_id]["step"] -= 1
        field = expected_fields[user_state[user_id]["step"] - 1]
        update.message.reply_text(f"⬅️ عدنا إلى {field_names_ar[field]}.\n{field_prompts[field]}")
    else:
        update.message.reply_text("❗ لا يمكن الرجوع أكثر من ذلك.")

# === Dispatcher setup ===
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(CommandHandler("startover", startover))
dispatcher.add_handler(CommandHandler("repeat", repeat))
dispatcher.add_handler(CommandHandler("stepBack", step_back))
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

