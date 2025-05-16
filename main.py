import os
import openai
import telegram
from telegram.ext import Dispatcher, MessageHandler, Filters
from flask import Flask, request
from docxtpl import DocxTemplate
from pydub import AudioSegment
import smtplib
from email.message import EmailMessage

# === Config ===
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
OPENAI_KEY = os.environ["OPENAI_KEY"]
EMAIL_SENDER = os.environ["EMAIL_SENDER"]
EMAIL_PASSWORD = os.environ["EMAIL_PASSWORD"]
EMAIL_RECEIVER = os.environ["EMAIL_RECEIVER"]
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL")

app = Flask(__name__)
bot = telegram.Bot(token=TELEGRAM_TOKEN)
dispatcher = Dispatcher(bot, update_queue=None, workers=0, use_context=True)

client = openai.OpenAI(api_key=OPENAI_KEY)

# === Session state per user ===
user_sessions = {}

# === Transcribe ===
def transcribe(file_path):
    audio = AudioSegment.from_file(file_path)
    audio.export("converted.wav", format="wav")
    with open("converted.wav", "rb") as f:
        transcription = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            language="ar"
        )
    return transcription.text

# === Report generation ===
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

    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}]
    )
    data["FullReport"] = response.choices[0].message.content

    doc = DocxTemplate("police_report_template.docx")
    doc.render(data)
    doc.save("تقرير_التحقيق.docx")

# === Email ===
def send_email():
    msg = EmailMessage()
    msg["Subject"] = "تقرير تحقيق تلقائي"
    msg["From"] = EMAIL_SENDER
    msg["To"] = EMAIL_RECEIVER
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

# === Bot field flow ===
fields = [
    ("Date", "🗓️ أرسل الآن المقطع الصوتي الذي يحتوي على **التاريخ**."),
    ("Briefing", "📌 أرسل المقطع الذي يحتوي على **موجز الحادث**."),
    ("Observations", "📝 أرسل المقطع الذي يحتوي على **الملاحظات**."),
    ("Investigator", "👮‍♂️ أرسل المقطع الذي يحتوي على **اسم المحقق**."),
    ("LocationObservations", "📍 أرسل المقطع الذي يحتوي على **معاينة الموقع**."),
    ("Examination", "🔍 أرسل المقطع الذي يحتوي على **الفحص الفني**."),
    ("Outcomes", "📊 أرسل المقطع الذي يحتوي على **النتيجة**."),
    ("TechincalOpinion", "💡 أرسل المقطع الذي يحتوي على **الرأي الفني**.")
]

def handle_voice(update, context):
    user_id = update.effective_user.id
    session = user_sessions.setdefault(user_id, {"current": 0, "data": {}})

    try:
        file = update.message.voice.get_file()
        file.download("voice.ogg")
        update.message.reply_text("🎙️ جاري تحويل الصوت إلى نص...")

        text = transcribe("voice.ogg")
        field_key, _ = fields[session["current"]]
        session["data"][field_key] = text
        update.message.reply_text(f"✅ تم استلام {field_key}: {text}")

        session["current"] += 1

        if session["current"] < len(fields):
            next_prompt = fields[session["current"]][1]
            update.message.reply_text(next_prompt, parse_mode="Markdown")
        else:
            update.message.reply_text("📄 جاري توليد التقرير...")
            generate_report(session["data"])
            send_email()
            update.message.reply_text("📬 تم إرسال التقرير إلى بريدك الإلكتروني.")
            user_sessions.pop(user_id)

    except Exception as e:
        print("❌ Error:", str(e))
        update.message.reply_text("⚠️ حدث خطأ: " + str(e))

# === Start new session ===
def start(update, context):
    user_id = update.effective_user.id
    user_sessions[user_id] = {"current": 0, "data": {}}
    update.message.reply_text("👋 مرحباً! سنبدأ بجمع بيانات التقرير. " + fields[0][1], parse_mode="Markdown")

# === Routes ===
voice_handler = MessageHandler(Filters.voice, handle_voice)
dispatcher.add_handler(MessageHandler(Filters.text & Filters.command, start))
dispatcher.add_handler(voice_handler)

@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def webhook():
    update = telegram.Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return "OK"

@app.route("/set_webhook", methods=["GET"])
def set_webhook():
    if RENDER_EXTERNAL_URL:
        webhook_url = f"{RENDER_EXTERNAL_URL}/{TELEGRAM_TOKEN}"
        bot.set_webhook(webhook_url)
        return f"✅ Webhook set to {webhook_url}"
    return "⚠️ Missing RENDER_EXTERNAL_URL"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
