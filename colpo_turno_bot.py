#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ColpoTurno Bot - versione riscritta per python-telegram-bot v20+ e Render
Requisiti (requirements.txt):
python-telegram-bot==20.7
apscheduler
pytz
"""

import os
import json
import random
import logging
import datetime
import asyncio
from functools import wraps

import pytz
from apscheduler.schedulers.background import BackgroundScheduler

from telegram import Update, ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# -----------------------
# Config & env
# -----------------------
TELEGRAM_BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_CHAT_ID = os.getenv("GROUP_CHAT_ID")
if GROUP_CHAT_ID is not None:
    try:
        GROUP_CHAT_ID = int(GROUP_CHAT_ID)
    except Exception:
        GROUP_CHAT_ID = None

DATA_DIR = "data_colpoturno"
ROTATIONS_FILE = os.path.join(DATA_DIR, "rotazioni.json")
ABSENCES_FILE = os.path.join(DATA_DIR, "assenze.json")
PREFERENCES_FILE = os.path.join(DATA_DIR, "preferenze.json")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")

WORKERS = ["Giova", "Stefi", "Fede", "Daniela", "Anastasia", "Ros", "Marti"]
DAYS = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]

ROME_TZ = pytz.timezone("Europe/Rome")

# -----------------------
# Logging
# -----------------------
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("colpoturno")

# -----------------------
# Utils: file read/write
# -----------------------
def ensure_data_dir():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR, exist_ok=True)

def load_json(path, default):
    ensure_data_dir()
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default

def save_json(path, data):
    ensure_data_dir()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# initialize storage
rotazioni = load_json(ROTATIONS_FILE, {"history": []})
assenze = load_json(ABSENCES_FILE, {})
preferenze = load_json(PREFERENCES_FILE, {})
config = load_json(CONFIG_FILE, {"group_chat_id": GROUP_CHAT_ID})

if config.get("group_chat_id") is None and GROUP_CHAT_ID is not None:
    config["group_chat_id"] = GROUP_CHAT_ID
    save_json(CONFIG_FILE, config)

# -----------------------
# Scheduling / generation logic (same rules as prima)
# -----------------------
def weekday_name_to_idx(name):
    if not name:
        return None
    n = name.strip().lower()
    mapping = {
        "lun":0,"lunedì":0,"lunedi":0,
        "mar":1,"martedì":1,"martedi":1,
        "mer":2,"mercoledì":2,"mercoledi":2,
        "gio":3,"giovedì":3,"giovedi":3,
        "ven":4,"venerdì":4,"venerdi":4,
        "sab":5,"sabato":5,
        "dom":6,"domenica":6
    }
    return mapping.get(n, None)

def allowed_pairs_for_worker(worker):
    pairs = []
    for d1 in range(7):
        for d2 in range(d1+1, 7):
            if abs(d2 - d1) >= 3:
                absent_days = assenze.get(worker, [])
                if d1 in absent_days or d2 in absent_days:
                    continue
                pairs.append((d1, d2))
    return pairs

def last_week_pairs():
    if not rotazioni.get("history"):
        return set()
    last = rotazioni["history"][-1]["schedule"]
    pairs = set()
    for daylist in last:
        if len(daylist) >= 2:
            for i in range(len(daylist)):
                for j in range(i+1, len(daylist)):
                    pairs.add(frozenset([daylist[i], daylist[j]]))
    return pairs

def generate_week(prefer_honour=True, max_tries=5000):
    last_pairs = last_week_pairs()
    workers = WORKERS[:]
    random.shuffle(workers)

    allowed_pairs = {w: allowed_pairs_for_worker(w) for w in workers}
    for w, pairs in allowed_pairs.items():
        if not pairs:
            logger.warning(f"{w} non ha giorni disponibili (assenze troppo restrittive).")
            return None

    workers_sorted = sorted(workers, key=lambda w: len(allowed_pairs[w]))

    attempt = 0
    while attempt < max_tries:
        attempt += 1
        day_slots = [2] * 7
        assignment = {}
        success = True

        # try assign each worker
        for w in workers_sorted:
            pairs = allowed_pairs[w][:]
            if prefer_honour and w in preferenze:
                pref_days = set(preferenze[w])
                def score(pair):
                    return -(len(pref_days.intersection(pair)))
                pairs = sorted(pairs, key=score)
            random.shuffle(pairs)
            chosen = None
            for p in pairs:
                d1, d2 = p
                if day_slots[d1] > 0 and day_slots[d2] > 0:
                    chosen = p
                    break
            if chosen is None:
                success = False
                break
            assignment[w] = chosen
            d1, d2 = chosen
            day_slots[d1] -= 1
            day_slots[d2] -= 1

        if not success:
            continue
        if any(s != 0 for s in day_slots):
            continue

        days = [[] for _ in range(7)]
        for w, p in assignment.items():
            d1, d2 = p
            days[d1].append(w)
            days[d2].append(w)

        bad = any(len(dl) != 2 for dl in days)
        if bad:
            continue

        repeats = 0
        for dl in days:
            if len(dl) >= 2:
                pset = frozenset(dl)
                if pset in last_pairs:
                    repeats += 1

        if repeats == 0:
            logger.info(f"Generazione riuscita dopo {attempt} tentativi (0 ripetizioni).")
            return days
        else:
            if attempt > 2000 and repeats <= 1:
                logger.info(f"Generazione accettata dopo {attempt} tentativi (ripetizioni={repeats}).")
                return days
            continue

    logger.error("Generazione fallita dopo troppi tentativi.")
    return None

def format_week(schedule):
    text = ""
    for i, day in enumerate(schedule):
        text += f"*{DAYS[i].capitalize()}*: " + (", ".join(day) if day else "—") + "\n"
    return text

def schedule_to_dict(schedule):
    return {"generated_at": datetime.datetime.utcnow().isoformat(), "schedule": schedule}

# -----------------------
# Bot command handlers (async)
# -----------------------
def restricted(func):
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        return await func(update, context, *args, **kwargs)
    return wrapped

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Ciao! Sono *ColpoTurno Bot*.\n"
        "Gestisco la generazione automatica dei turni settimanali.\n\n"
        "Comandi principali:\n"
        "/settimana - mostra la pianificazione corrente\n"
        "/oggi - mostra i turni di oggi\n"
        "/assenza [Nome] [giorno] - registra un'assenza\n"
        "/preferenza [Nome] [giorno] - registra una preferenza\n"
        "/rigenera - rigenera la settimana rispettando assenze/preferenze\n"
        "/get_group_id - mostra l'id del gruppo\n"
        "/help - aiuto"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_cmd(update, context)

@restricted
async def get_group_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    await update.message.reply_text(f"Questo gruppo/chat ha id: `{chat.id}`", parse_mode=ParseMode.MARKDOWN)

@restricted
async def settimana_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not rotazioni.get("history"):
        await update.message.reply_text("Non esiste una pianificazione generata: usa /rigenera per generarla.")
        return
    last = rotazioni["history"][-1]
    text = f"*Pianificazione settimana generata il* {last['generated_at']}\n\n" + format_week(last["schedule"])
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

@restricted
async def oggi_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not rotazioni.get("history"):
        await update.message.reply_text("Nessuna pianificazione disponibile. Usa /rigenera.")
        return
    # compute local Rome weekday index
    now = datetime.datetime.now(tz=ROME_TZ)
    today_idx = now.weekday()
    last = rotazioni["history"][-1]
    daylist = last["schedule"][today_idx]
    text = f"*Turno per oggi ({DAYS[today_idx].capitalize()}):* " + (", ".join(daylist) if daylist else "—")
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

@restricted
async def assenza_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Uso: /assenza [Nome] [giorno]. Esempio: /assenza Fede martedì")
        return
    name = args[0].strip().capitalize()
    day = " ".join(args[1:]).strip()
    idx = weekday_name_to_idx(day)
    if name not in WORKERS:
        await update.message.reply_text("Nome non riconosciuto. Usa: " + ", ".join(WORKERS))
        return
    if idx is None:
        await update.message.reply_text("Giorno non riconosciuto. Usa p.es. lunedì, martedì, ...")
        return
    assenze.setdefault(name, [])
    if idx in assenze[name]:
        await update.message.reply_text(f"{name} è già segnato assente {DAYS[idx]}.")
        return
    assenze[name].append(idx)
    save_json(ABSENCES_FILE, assenze)
    await update.message.reply_text(f"Segnata assenza: *{name}* -> *{DAYS[idx]}*", parse_mode=ParseMode.MARKDOWN)

@restricted
async def preferenza_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Uso: /preferenza [Nome] [giorno]. Esempio: /preferenza Marti giovedì")
        return
    name = args[0].strip().capitalize()
    day = " ".join(args[1:]).strip()
    idx = weekday_name_to_idx(day)
    if name not in WORKERS:
        await update.message.reply_text("Nome non riconosciuto. Usa: " + ", ".join(WORKERS))
        return
    if idx is None:
        await update.message.reply_text("Giorno non riconosciuto. Usa p.es. lunedì, martedì, ...")
        return
    preferenze.setdefault(name, [])
    if idx in preferenze[name]:
        await update.message.reply_text(f"{name} ha già la preferenza per {DAYS[idx]}.")
        return
    preferenze[name].append(idx)
    save_json(PREFERENCES_FILE, preferenze)
    await update.message.reply_text(f"Preferenza salvata: *{name}* -> *{DAYS[idx]}*", parse_mode=ParseMode.MARKDOWN)

@restricted
async def rigenera_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Sto generando una nuova pianificazione (potrebbero voler alcuni secondi)...")
    sched = generate_week(prefer_honour=True, max_tries=5000)
    if sched is None:
        await update.message.reply_text("Non sono riuscito a generare una pianificazione valida con le restrizioni attuali. Controlla le assenze/preferenze.")
        return
    record = schedule_to_dict(sched)
    rotazioni.setdefault("history", []).append(record)
    save_json(ROTATIONS_FILE, rotazioni)
    text = "*Nuova pianificazione generata:*\n\n" + format_week(sched)
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

    gid = config.get("group_chat_id")
    if gid:
        try:
            await context.bot.send_message(chat_id=gid, text="📣 *Pianificazione settimanale generata:*\n\n" + format_week(sched), parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error(f"Errore invio al gruppo: {e}")

@restricted
async def staff_getstate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "Stato corrente:\n\n"
    text += f"Assenze: {json.dumps(assenze, ensure_ascii=False)}\n\n"
    text += f"Preferenze: {json.dumps(preferenze, ensure_ascii=False)}\n\n"
    text += f"Rotazioni storiche: {len(rotazioni.get('history', []))} settimane\n"
    await update.message.reply_text(text)

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Comando non riconosciuto. Usa /help per la lista dei comandi.")

# -----------------------
# Jobs called by APScheduler (sync functions that schedule async tasks)
# -----------------------
def schedule_send_weekly(application: Application):
    async def _send():
        logger.info("Eseguo job di generazione automatica settimanale.")
        sched = generate_week(prefer_honour=True, max_tries=5000)
        if sched is None:
            logger.error("Generazione automatica fallita.")
            return
        record = schedule_to_dict(sched)
        rotazioni.setdefault("history", []).append(record)
        save_json(ROTATIONS_FILE, rotazioni)
        gid = config.get("group_chat_id")
        text = "📅 *Pianificazione settimanale (automatica):*\n\n" + format_week(sched)
        if gid:
            try:
                await application.bot.send_message(chat_id=gid, text=text, parse_mode=ParseMode.MARKDOWN)
            except Exception as e:
                logger.error(f"Errore invio pianificazione al gruppo: {e}")
    # schedule as application task
    application.create_task(_send())

def schedule_send_today(application: Application):
    async def _send():
        if not rotazioni.get("history"):
            return
        now = datetime.datetime.now(tz=ROME_TZ)
        today_idx = now.weekday()
        last = rotazioni["history"][-1]
        daylist = last["schedule"][today_idx]
        text = f"🔔 *Turno di oggi ({DAYS[today_idx].capitalize()}):*\n" + (", ".join(daylist) if daylist else "—")
        gid = config.get("group_chat_id")
        if gid:
            try:
                await application.bot.send_message(chat_id=gid, text=text, parse_mode=ParseMode.MARKDOWN)
            except Exception as e:
                logger.error(f"Errore invio messaggio diario: {e}")
    application.create_task(_send())

# -----------------------
# MAIN
# -----------------------
async def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.error("BOT_TOKEN non impostato come variabile d'ambiente. Esci.")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    # handlers
    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("get_group_id", get_group_id))
    application.add_handler(CommandHandler("settimana", settimana_cmd))
    application.add_handler(CommandHandler("oggi", oggi_cmd))
    application.add_handler(CommandHandler("assenza", assenza_cmd))
    application.add_handler(CommandHandler("preferenza", preferenza_cmd))
    application.add_handler(CommandHandler("rigenera", rigenera_cmd))
    application.add_handler(CommandHandler("stato", staff_getstate))
    application.add_handler(MessageHandler(filters.COMMAND, unknown))

    # scheduler setup
    scheduler = BackgroundScheduler(timezone=ROME_TZ)
    # weekly job: sunday 20:00
    scheduler.add_job(lambda: schedule_send_weekly(application), trigger="cron", day_of_week="sun", hour=20, minute=0, id="weekly_gen")
    # daily job: every day at 07:30
    scheduler.add_job(lambda: schedule_send_today(application), trigger="cron", hour=7, minute=30, id="daily_msg")
    scheduler.start()
    logger.info("Scheduler avviato.")

    # start the bot (polling). This call blocks until stopped.
    logger.info("Avvio polling Telegram...")
    await application.run_polling()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Terminazione bot, pulisco...")





