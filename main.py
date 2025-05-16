import os
import telegram
from telegram.ext import Dispatcher, MessageHandler, Filters
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
    "Investigator": "🎙️ أرسل اسم المحقق.",
    "LocationObservations": "🎙️ أرسل معاينة الموقع.",
    "Examination": "🎙️ أرسل نتيجة الفحص الفني.",
    "Outcomes": "🎙️ أرسل النتيجة النهائية.",
    "TechincalOpinion": "🎙️ أرسل الرأي الفني."
}

# === Transcription ===
def transcribe(file_path):
    audio = AudioSegment.from_file(file_path)
    audio.export("converted.wav", format="wav")
    with open("converted.wav", "rb") as f:
        result = client.audio.transcriptions.create(model="whisper-1", file=f, language="ar")
    return result.text

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
        update.message.reply_text("✅ تم البدء. " + field_prompts[expected_fields[0]])
        return

    step = user_state[user_id]["step"]
    field = expected_fields[step]
    user_state[user_id]["data"][field] = text

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

# === Telegram setup ===
voice_handler = MessageHandler(Filters.voice, handle_voice)
dispatcher.add_handler(voice_handler)

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
