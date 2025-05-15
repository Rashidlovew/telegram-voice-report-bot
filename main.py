import os
import openai
import telegram
from telegram.ext import Dispatcher, MessageHandler, Filters
from flask import Flask, request
from docxtpl import DocxTemplate
from pydub import AudioSegment
import smtplib
from email.message import EmailMessage

# === Config (environment variables for security) ===
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
OPENAI_KEY = os.environ["OPENAI_KEY"]
EMAIL_SENDER = os.environ["EMAIL_SENDER"]
EMAIL_PASSWORD = os.environ["EMAIL_PASSWORD"]
EMAIL_RECEIVER = os.environ["EMAIL_RECEIVER"]

openai.api_key = OPENAI_KEY
bot = telegram.Bot(token=TELEGRAM_TOKEN)
app = Flask(__name__)
dispatcher = Dispatcher(bot, update_queue=None, workers=0, use_context=True)

# === Transcribe voice to text ===
def transcribe(file_path):
    audio = AudioSegment.from_file(file_path)
    audio.export("converted.wav", format="wav")
    with open("converted.wav", "rb") as audio_file:
        result = openai.Audio.transcribe("whisper-1", audio_file, language="ar")
        return result["text"]

# === Extract fields from Arabic input ===
def extract_fields(text):
    lines = text.split("،")
    return {
        "Date": lines[0].replace("التاريخ", "").strip(),
        "Briefing": lines[1].replace("الحادث", "").strip(),
        "Observations": lines[2].replace("الملاحظات", "").strip(),
        "Investigator": lines[3].replace("المحقق", "").strip(),
        "LocationObservations": lines[4].replace("معاينةالموقع", "").strip(),
        "Examination": lines[5].replace("الفحص_الفني", "").strip(),
        "Outcomes": lines[6].replace("النتيحة", "").strip(),
        "TechincalOpinion": lines[3].replace("الرأي_الفني", "").strip(),
    }

# === Generate report using GPT-4 ===
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

    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}]
    )
    data["FullReport"] = response["choices"][0]["message"]["content"]
    template = DocxTemplate("police_report_template.docx")
    template.render(data)
    template.save("تقرير_التحقيق.docx")

# === Send the Word report via email ===
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

# === Telegram voice handler ===
def handle_voice(update, context):
    file = update.message.voice.get_file()
    file.download("voice.ogg")

    text = transcribe("voice.ogg")
    update.message.reply_text(f"📋 تم تحويل الصوت إلى نص:\n{text}")

    data = extract_fields(text)
    generate_report(data)
    send_email()

    update.message.reply_text("📄 تم إرسال التقرير إلى بريدك الإلكتروني.")

voice_handler = MessageHandler(Filters.voice, handle_voice)
dispatcher.add_handler(voice_handler)

# === Webhook endpoint ===
@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def webhook():
    update = telegram.Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return "OK"

# === Set webhook from browser ===
@app.route("/set_webhook", methods=["GET"])
def set_webhook():
    public_url = os.environ.get("RENDER_EXTERNAL_URL")
    if public_url:
        webhook_url = f"{public_url}/{TELEGRAM_TOKEN}"
        bot.set_webhook(webhook_url)
        return f"Webhook set to: {webhook_url}"
    else:
        return "Webhook not set. RENDER_EXTERNAL_URL not found."
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)

