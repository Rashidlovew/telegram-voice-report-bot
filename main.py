import os
import telegram
from telegram.ext import Dispatcher, MessageHandler, Filters, CommandHandler
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

# === User session ===
user_state = {}
expected_fields = [
    "Date", "Briefing", "Observations", "Investigator",
    "LocationObservations", "Examination", "Outcomes", "TechincalOpinion"
]
field_prompts = {
    "Date": "🎙️ أرسل تاريخ الواقعة.",
    "Briefing": "🎙️ أرسل ملخص الحادث.",
    "Observations": "🎙️ أرسل الملاحظات.",
    "Investigator": "🎙️ أرسل اسم الفاحص.",
    "LocationObservations": "🎙️ أرسل معاينة الموقع.",
    "Examination": "🎙️ أرسل نتيجة الفحص الفني.",
    "Outcomes": "🎙️ أرسل النتيجة.",
    "TechincalOpinion": "🎙️ أرسل الرأي الفني."
}
welcome_message = (
    "👋 مرحباً بك في بوت إعداد تقارير الفحص الخاص بقسم الهندسة الجنائية.\n"
    "📌 أرسل ملاحظة صوتية عند كل طلب.\n"
    "🔄 لإعادة البدء من جديد أرسل /startover\n"
    "↩️ لإعادة إدخال الخطوة الحالية أرسل /repeat\n"
)

# === Transcription ===
def transcribe(file_path):
    audio = AudioSegment.from_file(file_path)
    audio.export("converted.wav", format="wav")
    with open("converted.wav", "rb") as f:
        result = client.audio.transcriptions.create(model="whisper-1", file=f, language="ar")
    return result.text

# === Enhance input text with GPT-4 ===
def enhance_with_gpt(field_name, user_input):
    prompt = f"أعد صياغة {field_name} التالية بطريقة احترافية ، مع استخدام أسلوب مهني، وكتابة التاريخ بالارقام مثالاَ على ذلك 15/مايو/2025, و أيضاَ يجب كتابة اسم الفاحص كما هو بدون تعديلات. :\n\n{user_input}"
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

# === Voice Handler ===
def handle_voice(update, context):
    user_id = update.message.from_user.id
    file = update.message.voice.get_file()
    file.download("voice.ogg")
    text = transcribe("voice.ogg")

    if user_id not in user_state:
        user_state[user_id] = {"step": 0, "data": {}}
        field = expected_fields[0]
        update.message.reply_text(welcome_message + "\n" + field_prompts[field])
        return

    step = user_state[user_id]["step"]
    field = expected_fields[step]
    enhanced = enhance_with_gpt(field, text)
    user_state[user_id]["data"][field] = enhanced

    step += 1
    if step < len(expected_fields):
        user_state[user_id]["step"] = step
        next_field = expected_fields[step]
        update.message.reply_text(f"✅ تم تسجيل {field}.\n{field_prompts[next_field]}")
    else:
        generate_report(user_state[user_id]["data"])
        send_email()
        update.message.reply_text("📄 تم إنشاء التقرير وإرساله إلى بريدك الإلكتروني.")
        del user_state[user_id]

# === Text Handler ===
def handle_text(update, context):
    user_id = update.message.from_user.id
    if user_id not in user_state:
        user_state[user_id] = {"step": 0, "data": {}}
        field = expected_fields[0]
        update.message.reply_text(welcome_message + "\n" + field_prompts[field])

# === Commands ===
def startover(update, context):
    user_id = update.message.from_user.id
    user_state[user_id] = {"step": 0, "data": {}}
    field = expected_fields[0]
    update.message.reply_text("🔄 تم إعادة البدء.\n" + field_prompts[field])

def repeat(update, context):
    user_id = update.message.from_user.id
    if user_id in user_state:
        step = user_state[user_id]["step"]
        field = expected_fields[step]
        update.message.reply_text("↩️ يرجى إعادة إرسال الخطوة الحالية:\n" + field_prompts[field])
    else:
        update.message.reply_text("ℹ️ لم تبدأ بعد. أرسل رسالة للبدء.")

# === Dispatcher setup ===
dispatcher.add_handler(MessageHandler(Filters.voice, handle_voice))
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_text))
dispatcher.add_handler(CommandHandler("startover", startover))
dispatcher.add_handler(CommandHandler("repeat", repeat))

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
    return "Webhook not set"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
