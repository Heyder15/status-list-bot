from datetime import datetime, timedelta

from telegram import Update
from telegram.error import RetryAfter
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# ==========================
#  BURAYA ÖZ TOKENİNİ YAZ
# ==========================
BOT_TOKEN = "8507724579:AAFA97ier5MsIL6rFTa_YVEBJCTCiEQeVtU"  # Məs: "1234567890:AA...."


# ================== KONFİQURASİYA ==================

# Başlanğıcda "Müsait" olan listlər
DEFAULT_AVAILABLE = {1, 3, 4, 5, 6, 11, 12, 13, 14, 15, 17, 19, 20, 22, 23, 26}
AVAILABLE_LISTS = set(DEFAULT_AVAILABLE)

# Başlanğıcda "Meşgul" olan listlər və onların müddəti
# format: liste_no: (gün, saat, dəqiqə, saniyə)
BUSY_CONFIG = {
    2:  (0, 11, 59, 51),
    7:  (40, 14, 17, 51),
    8:  (4, 23, 43, 51),
    9:  (3, 11, 22, 51),
    10: (0, 0, 40, 51),
    16: (22, 12, 59, 51),
    18: (2, 18, 12, 51),
    21: (2, 13, 33, 51),
    24: (0, 1, 2, 51),
    25: (0, 2, 44, 51),
}

# Runtime-da istifadə ediləcək:
BUSY_LISTS: dict[int, datetime] = {}       # {liste_no: bitmə_vaxtı}
ACTIVE_STATUS_MSG: dict[int, int] = {}     # {chat_id: message_id}


def init_busy_lists():
    """Proqram start olanda və ya /reset-də BUSY_LISTS-i doldurur."""
    global BUSY_LISTS
    now = datetime.now()
    BUSY_LISTS = {}
    for no, (days, hours, minutes, seconds) in BUSY_CONFIG.items():
        BUSY_LISTS[no] = now + timedelta(
            days=days,
            hours=hours,
            minutes=minutes,
            seconds=seconds,
        )


def format_remaining(delta: timedelta) -> str:
    """timedelta → '3g, 11s, 22dk, 51sn qaldı' kimi string."""
    total = int(delta.total_seconds())
    if total < 0:
        total = 0

    days = total // 86400
    total %= 86400
    hours = total // 3600
    total %= 3600
    minutes = total // 60
    seconds = total % 60

    parts = []
    if days > 0:
        parts.append(f"{days}g")
    parts.append(f"{hours}s")
    parts.append(f"{minutes}dk")
    parts.append(f"{seconds}sn")
    return ", ".join(parts) + " qaldı"


def build_status_text() -> str:
    """Müsait / Meşgul bloklarını və Son Güncelleme saatını tərtib edir."""
    global AVAILABLE_LISTS, BUSY_LISTS
    now = datetime.now()

    # Vaxtı bitmiş meşgul listləri Müsait-ə keçir
    finished = []
    for no, end_time in BUSY_LISTS.items():
        if end_time <= now:
            finished.append(no)
    for no in finished:
        BUSY_LISTS.pop(no, None)
        AVAILABLE_LISTS.add(no)

    # ---- Müsait hissəsi ----
    text = "╔═════🔹Boş🔹═════╗\n"
    if AVAILABLE_LISTS:
        for no in sorted(AVAILABLE_LISTS):
            text += f"║              HESAB {no}              \n"
    else:
        text += "║         (Müsait liste yok)          \n"
    text += "╚═══════════════╝\n\n"

    # ---- Meşgul hissəsi ----
    text += "╔═════🔸Dolu🔸═════╗\n"
    if BUSY_LISTS:
        for no in sorted(BUSY_LISTS.keys()):
            remaining = BUSY_LISTS[no] - now
            text += f"║HESAB{no}-{format_remaining(remaining)}\n"
    else:
        text += "║         (Meşgul liste yok)          \n"
    text += "╚═══════════════╝\n"

    text += "      İşlemler için : @spookyadmin\n"
    text += "      Whatsapp : +994 55 315 50 60\n\n" 
    text += f"🕒 Son Güncelleme: {now.strftime('%H:%M:%S')}"

    return text


# =============== JOB CALLBACK ==================


async def update_status_message(context: ContextTypes.DEFAULT_TYPE):
    """Hər 5 saniyədən bir çağrılır – eyni mesaja edit atır."""
    global ACTIVE_STATUS_MSG
    job = context.job
    chat_id = job.data["chat_id"]
    message_id = job.data["message_id"]

    text = build_status_text()

    # Əgər artıq Meşgul list qalmayıbsa, son dəfə update edib işi dayandıraq
    if not BUSY_LISTS:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
            )
        except RetryAfter as e:
            print(f"Flood (final edit): wait {e.retry_after} s")
        except Exception as e:
            print("Final edit error:", e)
        finally:
            job.schedule_removal()
            ACTIVE_STATUS_MSG.pop(chat_id, None)
        return

    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
        )
    except RetryAfter as e:
        # Flood-control çıxsa, job-u dayandırırıq, sonra lazım olanda /durum ilə yenidən açarsan
        print(f"Flood on edit: wait {e.retry_after} s – job stopped for chat {chat_id}")
        job.schedule_removal()
        ACTIVE_STATUS_MSG.pop(chat_id, None)
    except Exception as e:
        print("Edit error:", e)
        job.schedule_removal()
        ACTIVE_STATUS_MSG.pop(chat_id, None)


# =============== KOMANDALAR ==================


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /start və /durum komandası:
    - bir dəfə status mesajını göndərir
    - hər 5 saniyədən bir edit edən job əlavə edir
    """
    global AVAILABLE_LISTS

    chat_id = update.effective_chat.id

    # İlk dəfə çağrılırsa BUSY_LISTS-i initialize et
    if not BUSY_LISTS:
        init_busy_lists()

    text = build_status_text()

    # Əgər bu chat üçün artıq aktiv status mesajı varsa:
    if chat_id in ACTIVE_STATUS_MSG:
        message_id = ACTIVE_STATUS_MSG[chat_id]
        # Sadəcə mövcud mesajı yeniləməyə çalışırıq (yenidən spam mesaj göndərmirik)
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
            )
        except Exception as e:
            print("Existing message edit in /start failed:", e)

        # Job varsa toxunmuruq, yoxdursa yenidən qoşuruq
        current_jobs = context.application.job_queue.get_jobs_by_name(f"status_{chat_id}")
        if not current_jobs:
            context.application.job_queue.run_repeating(
                callback=update_status_message,
                interval=5.0,       # hər 5 saniyədən bir
                first=5.0,
                name=f"status_{chat_id}",
                data={"chat_id": chat_id, "message_id": message_id},
            )
        return

    # Yeni status mesajı göndəririk
    try:
        msg = await update.message.reply_text(text)
    except RetryAfter as e:
        print(f"Flood on reply_text (start): wait {e.retry_after} s")
        return
    except Exception as e:
        print("Error sending status message:", e)
        return

    ACTIVE_STATUS_MSG[chat_id] = msg.message_id

    # Eyni adda köhnə job qalıbsa, silək
    current_jobs = context.application.job_queue.get_jobs_by_name(f"status_{chat_id}")
    for j in current_jobs:
        j.schedule_removal()

    # Hər 5 saniyədən bir statusu yeniləyən job
    context.application.job_queue.run_repeating(
        callback=update_status_message,
        interval=5.0,          # flood riskini azaltmaq üçün 5 saniyə
        first=5.0,
        name=f"status_{chat_id}",
        data={"chat_id": chat_id, "message_id": msg.message_id},
    )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /reset → bütün vaxtları sıfırlayır, Müsait/Meşgul-ları ilkin vəziyyətə qaytarır.
    """
    global AVAILABLE_LISTS
    chat_id = update.effective_chat.id

    AVAILABLE_LISTS = set(DEFAULT_AVAILABLE)
    init_busy_lists()

    # Bu chat üçün job varsa dayandır
    for j in context.application.job_queue.get_jobs_by_name(f"status_{chat_id}"):
        j.schedule_removal()
    ACTIVE_STATUS_MSG.pop(chat_id, None)

    try:
        await update.message.reply_text("Listlər yenidən başlatıldı. Yenidən görmək üçün /durum yaz.")
    except RetryAfter as e:
        print(f"Flood on /reset reply: wait {e.retry_after} s")
    except Exception as e:
        print("Reset reply error:", e)


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Komandalar
    app.add_handler(CommandHandler(["start", "durum", "status"], start))
    app.add_handler(CommandHandler("reset", reset))

    print("Status List Bot işə düşdü...")
    app.run_polling()


if __name__ == "__main__":
    main()

