# main.py (updated for interactive voice prompts)

import os
import openai
import telegram
from telegram.ext import Dispatcher, MessageHandler, Filters
from flask import Flask, request
from docxtpl import DocxTemplate
from pydub import AudioSegment
import smtplib
from email.message import EmailMessage

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
OPENAI_KEY = os.environ["OPENAI_KEY"]
EMAIL_SENDER = os.environ["EMAIL_SENDER"]
EMAIL_PASSWORD = os.environ["EMAIL_PASSWORD"]
EMAIL_RECEIVER = os.environ["EMAIL_RECEIVER"]
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL")

openai.api_key = OPENAI_KEY
bot = telegram.Bot(token=TELEGRAM_TOKEN)
app = Flask(__name__)
dispatcher = Dispatcher(bot, update_queue=None, workers=0, use_context=True)

# Session storage
user_sessions = {}

# Field prompts and keys
fields = [
    ("Date", "🎙️ أرسل الآن التاريخ"),
    ("Briefing", "🎙️ أرسل الآن الحادث"),
    ("Observations", "🎙️ أرسل الآن الملاحظات"),
    ("Investigator", "🎙️ أرسل الآن اسم المحقق"),
    ("LocationObservations", "🎙️ أرسل الآن معاينة الموقع"),
    ("Examination", "🎙️ أرسل الآن الفحص الفني"),
    ("Outcomes", "🎙️ أرسل الآن النتيجة"),
    ("TechincalOpinion", "🎙️ أرسل الآن الرأي الفني")
]

# Transcription
def transcribe(file_path):
    audio = AudioSegment.from_file(file_path)
    audio.export("converted.wav", format="wav")
    with open("converted.wav", "rb") as f:
        transcription = openai.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            language="ar"
        )
    return transcription.text

# Generate report
def generate_report(data):
    prompt = f"""اكتب تقرير تحقيق رسمي باللغة العربية بناءً على:
    التاريخ: {data['Date']}
    الحادث: {data['Briefing']}
    الملاحظات: {data['Observations']}
    المحقق: {data['Investigator']}
    معاينةالموقع: {data['LocationObservations']}
    الفحص_الفني: {data['Examination']}
    النتيحة: {data['Outcomes']}
    الرأي_الفني: {data['TechincalOpinion']}
    بصيغة رسمية ومهنية مع أستطراد في الكلام."""

    response = openai.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}]
    )
    data["FullReport"] = response.choices[0].message.content
    template = DocxTemplate("police_report_template.docx")
    template.render(data)
    template.save("تقرير_التحقيق.docx")

# Send report
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

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(EMAIL_SENDER, EMAIL_PASSWORD)
        smtp.send_message(msg)

# Voice handler

def handle_voice(update, context):
    user_id = update.effective_user.id
    file = update.message.voice.get_file()
    file.download("voice.ogg")
    text = transcribe("voice.ogg")

    # New session
    if user_id not in user_sessions:
        update.message.reply_text("أرسل 'ابدأ التقرير' أولاً.")
        return

    session = user_sessions[user_id]
    step = session["step"]
    field_key, _ = fields[step]
    session["data"][field_key] = text
    session["step"] += 1

    if session["step"] < len(fields):
        next_prompt = fields[session["step"]][1]
        update.message.reply_text(next_prompt)
    else:
        generate_report(session["data"])
        send_email()
        update.message.reply_text("📄 تم إرسال التقرير إلى بريدك الإلكتروني.")
        del user_sessions[user_id]

# Start command

def handle_text(update, context):
    user_id = update.effective_user.id
    if update.message.text.strip() == "ابدأ التقرير":
        user_sessions[user_id] = {"step": 0, "data": {}}
        update.message.reply_text(fields[0][1])
    else:
        update.message.reply_text("أرسل 'ابدأ التقرير' لبدء إنشاء تقرير جديد.")

# Telegram hooks
voice_handler = MessageHandler(Filters.voice, handle_voice)
text_handler = MessageHandler(Filters.text & (~Filters.command), handle_text)
dispatcher.add_handler(voice_handler)
dispatcher.add_handler(text_handler)

# Webhook route
@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def webhook():
    update = telegram.Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return "OK"

@app.route("/set_webhook", methods=["GET"])
def set_webhook():
    if RENDER_EXTERNAL_URL:
        bot.set_webhook(f"{RENDER_EXTERNAL_URL}/{TELEGRAM_TOKEN}")
        return f"Webhook set to: {RENDER_EXTERNAL_URL}/{TELEGRAM_TOKEN}"
    else:
        return "Missing RENDER_EXTERNAL_URL"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
