import os
import openai
import telegram
from telegram.ext import Dispatcher, MessageHandler, Filters
from flask import Flask, request
from docxtpl import DocxTemplate
from pydub import AudioSegment
import smtplib
from email.message import EmailMessage

# === Config (environment variables) ===
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
OPENAI_KEY = os.environ["OPENAI_KEY"]
EMAIL_SENDER = os.environ["EMAIL_SENDER"]
EMAIL_PASSWORD = os.environ["EMAIL_PASSWORD"]
EMAIL_RECEIVER = os.environ["EMAIL_RECEIVER"]

openai.api_key = OPENAI_KEY
bot = telegram.Bot(token=TELEGRAM_TOKEN)
app = Flask(__name__)
dispatcher = Dispatcher(bot, update_queue=None, workers=0, use_context=True)

# === Session dictionary to track user inputs ===
user_sessions = {}

# === Transcribe voice ===
def transcribe(file_path):
    audio = AudioSegment.from_file(file_path)
    audio.export("converted.wav", format="wav")
    with open("converted.wav", "rb") as f:
        transcription = openai.Audio.transcriptions.create(
            model="whisper-1",
            file=f,
            language="ar"
        )
    return transcription.text

# === Questions to collect ===
questions = [
    ("Date", "📅 أرسل التاريخ"),
    ("Briefing", "📝 أرسل وصف الحادث"),
    ("Observations", "👀 أرسل الملاحظات"),
    ("Investigator", "👤 أرسل اسم المحقق"),
    ("LocationObservations", "📍 أرسل ملاحظات معاينة الموقع"),
    ("Examination", "🔬 أرسل تفاصيل الفحص الفني"),
    ("Outcomes", "📌 أرسل النتيجة"),
    ("TechincalOpinion", "💡 أرسل الرأي الفني"),
]

# === Handle incoming voice messages ===
def handle_voice(update, context):
    user_id = update.message.from_user.id
    session = user_sessions.get(user_id, {"answers": {}, "step": 0})

    # Save voice and transcribe
    file = update.message.voice.get_file()
    file.download("voice.ogg")
    text = transcribe("voice.ogg")
    update.message.reply_text(f"🗣️ تم تحويل الصوت إلى:\n{text}")

    # Store answer
    key, _ = questions[session["step"]]
    session["answers"][key] = text
    session["step"] += 1

    # Move to next question or generate report
    if session["step"] < len(questions):
        next_key, next_question = questions[session["step"]]
        update.message.reply_text(next_question)
    else:
        update.message.reply_text("📄 يتم الآن توليد التقرير...")
        generate_report(session["answers"])
        send_email()
        update.message.reply_text("📧 تم إرسال التقرير إلى بريدك الإلكتروني.")
        session = {"answers": {}, "step": 0}  # Reset after finish

    user_sessions[user_id] = session

# === Render the report ===
def generate_report(data):
    doc = DocxTemplate("police_report_template.docx")
    doc.render(data)
    doc.save("تقرير_التحقيق.docx")

# === Email the report ===
def send_email():
    msg = EmailMessage()
    msg['Subject'] = "تقرير تحقيق تلقائي"
    msg['From'] = EMAIL_SENDER
    msg['To'] = EMAIL_RECEIVER
    msg.set_content("يرجى مراجعة التقرير المرفق.")

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

# === Setup handlers ===
voice_handler = MessageHandler(Filters.voice, handle_voice)
dispatcher.add_handler(voice_handler)

# === Webhook endpoint ===
@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def webhook():
    update = telegram.Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return "OK"

# === Webhook setup ===
@app.route("/set_webhook", methods=["GET"])
def set_webhook():
    public_url = os.environ.get("RENDER_EXTERNAL_URL")
    if public_url:
        webhook_url = f"{public_url}/{TELEGRAM_TOKEN}"
        bot.set_webhook(webhook_url)
        return f"Webhook set to: {webhook_url}"
    else:
        return "Webhook not set. RENDER_EXTERNAL_URL not found."

# === Start Flask server ===
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
