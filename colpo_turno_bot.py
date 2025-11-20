"""
ColpoTurno Bot - gestione turni settimanali
Requisiti: python-telegram-bot, apscheduler, pandas
"""

import json
import random
import logging
import datetime
import pytz
import os
from functools import wraps

from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Update, ParseMode
from telegram.ext import Updater, CommandHandler, CallbackContext, MessageHandler, Filters

# ---------- CONFIG ----------
TELEGRAM_BOT_TOKEN = "8304535352:AAEr1Cmjct1__bW-twXyy7z0bgDIZW0oU1Q"
# se vuoi mettere subito l'id del gruppo mettilo qui, altrimenti lascialo None e usa /get_group_id nel gruppo
GROUP_CHAT_ID = -970931242

DATA_DIR = "data_colpoturno"
ROTATIONS_FILE = os.path.join(DATA_DIR, "rotazioni.json")
ABSENCES_FILE = os.path.join(DATA_DIR, "assenze.json")
PREFERENCES_FILE = os.path.join(DATA_DIR, "preferenze.json")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")

# Lista lavoratori (fissa)
WORKERS = ["Giova", "Stefi", "Fede", "Daniela", "Anastasia", "Ros", "Marti"]
DAYS = ["lunedì","martedì","mercoledì","giovedì","venerdì","sabato","domenica"]

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------- UTILS: load/save ----------
def ensure_data_dir():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)

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

# initialize files if absent
rotazioni = load_json(ROTATIONS_FILE, {"history": []})  # history: list of weekly schedules
assenze = load_json(ABSENCES_FILE, {})   # {"Giova":[0,3], ...} weekday indices 0=lunedì
preferenze = load_json(PREFERENCES_FILE, {})  # {"Giova":[1,4], ...}
config = load_json(CONFIG_FILE, {"group_chat_id": GROUP_CHAT_ID})

if config.get("group_chat_id") is None and GROUP_CHAT_ID is not None:
    config["group_chat_id"] = GROUP_CHAT_ID
    save_json(CONFIG_FILE, config)

# ---------- SCHEDULER ----------
scheduler = BackgroundScheduler(timezone=pytz.timezone("Europe/Rome"))

# ---------- ALGORITMO DI GENERAZIONE ----------
# Regole implementate:
# - Ogni lavoratore ha esattamente 2 turni nella settimana
# - Le due giornate per lo stesso lavoratore devono essere distanziate di almeno 2 giorni (cioè differenza indice >= 3)
# - Ogni giorno ha esattamente 2 persone (vedi nota: necessario per 14 turni totali)
# - Evitare ripetizioni immediate: non assegnare la stessa coppia di persone che è stata insieme la scorsa settimana (se possibile)
# - Rispetta assenze e cerca di rispettare preferenze quando possibile

def weekday_name_to_idx(name):
    name = name.strip().lower()
    mapping = {
        "lun":0,"lunedì":0,"lunedi":0,
        "mar":1,"martedì":1,"martedi":1,
        "mer":2,"mercoledì":2,"mercoledi":2,
        "gio":3,"giovedì":3,"giovedi":3,
        "ven":4,"venerdì":4,"venerdi":4,
        "sab":5,"sabato":5,
        "dom":6,"domenica":6
    }
    return mapping.get(name, None)

def allowed_pairs_for_worker(worker):
    # all combinations of two distinct days where difference >=3
    pairs = []
    for d1 in range(7):
        for d2 in range(d1+1,7):
            if abs(d2 - d1) >= 3:  # at least 2 full days in between
                # check absences for worker
                absent_days = assenze.get(worker, [])
                if d1 in absent_days or d2 in absent_days:
                    continue
                pairs.append((d1,d2))
    return pairs

def last_week_pairs():
    # returns set of frozenset pairs of workers that were together last week
    if not rotazioni["history"]:
        return set()
    last = rotazioni["history"][-1]["schedule"]  # list of days -> [w1,w2]
    pairs = set()
    for daylist in last:
        if len(daylist) >= 2:
            # add every pair (but days have exactly 2 here)
            for i in range(len(daylist)):
                for j in range(i+1,len(daylist)):
                    pairs.add(frozenset([daylist[i], daylist[j]]))
    return pairs

def generate_week(prefer_honour=True, max_tries=5000):
    """
    Attempt to generate a weekly schedule satisfying constraints.
    Returns schedule as list of 7 lists (each list length 2 with worker names)
    or None if failed.
    """
    # day slots: 2 per day
    slots = [2]*7
    last_pairs = last_week_pairs()
    workers = WORKERS[:]
    random.shuffle(workers)

    # Precompute allowed pairs of days per worker (considering absences)
    allowed_pairs = {w: allowed_pairs_for_worker(w) for w in workers}
    # If any worker has no allowed pairs -> impossible
    for w,pairs in allowed_pairs.items():
        if not pairs:
            logger.warning(f"{w} non ha giorni disponibili (assenze troppo restrittive).")
            return None

    # heuristics: order workers by fewest options first
    workers_sorted = sorted(workers, key=lambda w: len(allowed_pairs[w]))

    attempt = 0
    while attempt < max_tries:
        attempt += 1
        day_slots = [2]*7
        assignment = {w: None for w in workers_sorted}
        # choose a pair for each worker
        success = True
        for w in workers_sorted:
            # for preferences: sort pairs that include preferred days earlier
            pairs = allowed_pairs[w][:]
            if prefer_honour and w in preferenze:
                pref_days = set(preferenze[w])
                def score(pair):
                    return -(len(pref_days.intersection(pair)))  # more matches => lower score (to be chosen first after sort)
                pairs = sorted(pairs, key=score)
            random.shuffle(pairs)  # add randomness
            chosen = None
            for p in pairs:
                d1,d2 = p
                if day_slots[d1] > 0 and day_slots[d2] > 0:
                    # tentative assign
                    # to try avoid immediate repetition, check tentative pairs formed with existing day assignments:
                    conflict = False
                    # check how many repeated pairs would be created w.r.t. last week
                    if last_pairs:
                        new_repeats = 0
                        # for day d1, current assigned workers:
                        # gather existing in that day
                        # but we don't have full schedule structure yet, so we need to track day->workers chosen
                    chosen = p
                    break
            if chosen is None:
                success = False
                break
            assignment[w] = chosen
            d1,d2 = chosen
            day_slots[d1] -= 1
            day_slots[d2] -= 1

        # after assigning all, check day_slots all zero
        if not success:
            # retry
            continue
        if any(s != 0 for s in day_slots):
            continue

        # build day lists
        days = [[] for _ in range(7)]
        for w,p in assignment.items():
            d1,d2 = p
            days[d1].append(w)
            days[d2].append(w)

        # validate no day has >2 (should not) and distance constraints (already enforced)
        bad = False
        for i,dl in enumerate(days):
            if len(dl) != 2:
                bad = True
                break

        if bad:
            continue

        # check repetition avoidance vs last week: try to avoid any pair that was together last week
        repeats = 0
        for daylist in days:
            if len(daylist) >= 2:
                p = frozenset(daylist)
                if p in last_pairs:
                    repeats += 1
        # prefer schedule with repeats == 0; allow 1 if nothing better
        if repeats == 0:
            logger.info(f"Generazione riuscita dopo {attempt} tentativi (0 ripetizioni).")
            return days
        else:
            # keep it if no perfect found after some attempts
            if attempt > 2000 and repeats <= 1:
                logger.info(f"Generazione accettata dopo {attempt} tentativi (ripetizioni={repeats}).")
                return days
            # otherwise continue searching
            continue

    logger.error("Generazione fallita dopo troppi tentativi.")
    return None

# ---------- FORMATTING ----------
def format_week(schedule):
    text = ""
    for i, day in enumerate(schedule):
        text += f"*{DAYS[i].capitalize()}*: " + (", ".join(day) if day else "—") + "\n"
    return text

def schedule_to_dict(schedule):
    # returns simple serializable structure
    return {"generated_at": datetime.datetime.utcnow().isoformat(), "schedule": schedule}

# ---------- COMMANDS ----------
def restricted(func):
    @wraps(func)
    def wrapped(update: Update, context: CallbackContext, *args, **kwargs):
        # allow in groups/admins - for simplicity allow everyone
        return func(update, context, *args, **kwargs)
    return wrapped

def start(update: Update, context: CallbackContext):
    text = ("Ciao! Sono *ColpoTurno Bot*.\n"
            "Gestisco la generazione automatica dei turni settimanali.\n\n"
            "Comandi principali:\n"
            "/settimana - mostra la pianificazione corrente\n"
            "/oggi - mostra i turni di oggi\n"
            "/assenza [Nome] [giorno] - registra un'assenza (es. /assenza Fede martedì)\n"
            "/preferenza [Nome] [giorno] - registra una preferenza (es. /preferenza Marti giovedì)\n"
            "/rigenera - rigenera la settimana rispettando assenze/preferenze\n"
            "/get_group_id - mostra l'id del gruppo (usa nel gruppo dove hai aggiunto il bot)\n"
            "/help - aiuto")
    update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

def help_cmd(update: Update, context: CallbackContext):
    start(update, context)

@restricted
def get_group_id(update: Update, context: CallbackContext):
    chat = update.effective_chat
    update.message.reply_text(f"Questo gruppo/chat ha id: `{chat.id}`", parse_mode=ParseMode.MARKDOWN)

@restricted
def settimana_cmd(update: Update, context: CallbackContext):
    # show last generated week or generate if none
    if not rotazioni["history"]:
        update.message.reply_text("Non esiste una pianificazione generata: usa /rigenera per generarla.")
        return
    last = rotazioni["history"][-1]
    text = f"*Pianificazione settimana generata il* {last['generated_at']}\n\n"
    text += format_week(last["schedule"])
    update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

@restricted
def oggi_cmd(update: Update, context: CallbackContext):
    if not rotazioni["history"]:
        update.message.reply_text("Nessuna pianificazione disponibile. Usa /rigenera.")
        return
    # determine today's weekday index (0=Monday) in Italian mapping consistent with DAYS
    today_idx = (datetime.datetime.utcnow() + datetime.timedelta(hours=1)).weekday()  # UTC+1 rough
    last = rotazioni["history"][-1]
    daylist = last["schedule"][today_idx]
    text = f"*Turno per oggi ({DAYS[today_idx].capitalize()}):* " + (", ".join(daylist) if daylist else "—")
    update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

@restricted
def assenza_cmd(update: Update, context: CallbackContext):
    # usage: /assenza Fede martedì
    args = context.args
    if len(args) < 2:
        update.message.reply_text("Uso: /assenza [Nome] [giorno]. Esempio: /assenza Fede martedì")
        return
    name = args[0].strip().capitalize()
    day = " ".join(args[1:]).strip()
    idx = weekday_name_to_idx(day)
    if name not in WORKERS:
        update.message.reply_text("Nome non riconosciuto. Usa uno dei seguenti: " + ", ".join(WORKERS))
        return
    if idx is None:
        update.message.reply_text("Giorno non riconosciuto. Usa p.es. lunedì, martedì, ...")
        return
    assenze.setdefault(name, [])
    if idx in assenze[name]:
        update.message.reply_text(f"{name} è già segnato assente {DAYS[idx]}.")
        return
    assenze[name].append(idx)
    save_json(ABSENCES_FILE, assenze)
    update.message.reply_text(f"Segnata assenza: *{name}* -> *{DAYS[idx]}*", parse_mode=ParseMode.MARKDOWN)

@restricted
def preferenza_cmd(update: Update, context: CallbackContext):
    # usage: /preferenza Marti giovedì
    args = context.args
    if len(args) < 2:
        update.message.reply_text("Uso: /preferenza [Nome] [giorno]. Esempio: /preferenza Marti giovedì")
        return
    name = args[0].strip().capitalize()
    day = " ".join(args[1:]).strip()
    idx = weekday_name_to_idx(day)
    if name not in WORKERS:
        update.message.reply_text("Nome non riconosciuto. Usa: " + ", ".join(WORKERS))
        return
    if idx is None:
        update.message.reply_text("Giorno non riconosciuto. Usa p.es. lunedì, martedì, ...")
        return
    preferenze.setdefault(name, [])
    if idx in preferenze[name]:
        update.message.reply_text(f"{name} ha già la preferenza per {DAYS[idx]}.")
        return
    preferenze[name].append(idx)
    save_json(PREFERENCES_FILE, preferenze)
    update.message.reply_text(f"Preferenza salvata: *{name}* -> *{DAYS[idx]}*", parse_mode=ParseMode.MARKDOWN)

@restricted
def rigenera_cmd(update: Update, context: CallbackContext):
    update.message.reply_text("Sto generando una nuova pianificazione (potrebbero voler alcuni secondi)...")
    sched = generate_week(prefer_honour=True, max_tries=5000)
    if sched is None:
        update.message.reply_text("Non sono riuscito a generare una pianificazione valida con le restrizioni attuali. Controlla le assenze/preferenze.")
        return
    record = schedule_to_dict(sched)
    rotazioni["history"].append(record)
    save_json(ROTATIONS_FILE, rotazioni)
    text = "*Nuova pianificazione generata:*\n\n" + format_week(sched)
    update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    # send to group if configured
    gid = config.get("group_chat_id")
    if gid:
        try:
            context.bot.send_message(chat_id=gid, text="📣 *Pianificazione settimanale generata:*\n\n" + format_week(sched), parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error(f"Errore invio al gruppo: {e}")

@restricted
def staff_getstate(update: Update, context: CallbackContext):
    text = "Stato corrente:\n\n"
    text += f"Assenze: {json.dumps(assenze, ensure_ascii=False)}\n\n"
    text += f"Preferenze: {json.dumps(preferenze, ensure_ascii=False)}\n\n"
    text += f"Rotazioni storiche: {len(rotazioni['history'])} settimane\n"
    update.message.reply_text(text)

def unknown(update: Update, context: CallbackContext):
    update.message.reply_text("Comando non riconosciuto. Usa /help per la lista dei comandi.")

# ---------- JOBS: automatic weekly and daily messages ----------
def job_generate_and_send(context: CallbackContext):
    # generate on Sunday 20:00 (scheduler will set it)
    logger.info("Eseguo job di generazione automatica settimanale.")
    sched = generate_week(prefer_honour=True, max_tries=5000)
    if sched is None:
        logger.error("Generazione automatica fallita.")
        return
    record = schedule_to_dict(sched)
    rotazioni["history"].append(record)
    save_json(ROTATIONS_FILE, rotazioni)
    gid = config.get("group_chat_id")
    text = "📅 *Pianificazione settimanale (automatica):*\n\n" + format_week(sched)
    if gid:
        try:
            context.bot.send_message(chat_id=gid, text=text, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error(f"Errore invio pianificazione al gruppo: {e}")

def job_send_today(context: CallbackContext):
    # sends today's assignment at 07:30
    if not rotazioni["history"]:
        return
    today_idx = (datetime.datetime.utcnow() + datetime.timedelta(hours=1)).weekday()
    last = rotazioni["history"][-1]
    daylist = last["schedule"][today_idx]
    text = f"🔔 *Turno di oggi ({DAYS[today_idx].capitalize()}):*\n" + (", ".join(daylist) if daylist else "—")
    gid = config.get("group_chat_id")
    if gid:
        try:
            context.bot.send_message(chat_id=gid, text=text, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error(f"Errore invio messaggio diario: {e}")

# ---------- MAIN ----------
def main():
    updater = Updater(token=TELEGRAM_BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    # commands
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help_cmd))
    dp.add_handler(CommandHandler("get_group_id", get_group_id))
    dp.add_handler(CommandHandler("settimana", settimana_cmd))
    dp.add_handler(CommandHandler("oggi", oggi_cmd))
    dp.add_handler(CommandHandler("assenza", assenza_cmd, pass_args=True))
    dp.add_handler(CommandHandler("preferenza", preferenza_cmd, pass_args=True))
    dp.add_handler(CommandHandler("rigenera", rigenera_cmd))
    dp.add_handler(CommandHandler("stato", staff_getstate))
    dp.add_handler(MessageHandler(Filters.command, unknown))

    # start scheduler jobs
    scheduler.add_job(lambda: job_generate_and_send(updater.bot), 'cron', day_of_week='sun', hour=20, minute=0)
    scheduler.add_job(lambda: job_send_today(updater.bot), 'cron', hour=7, minute=30)
    scheduler.start()

    # start polling
    updater.start_polling()
    logger.info("ColpoTurno Bot avviato.")
    updater.idle()

if __name__ == "__main__":
    main()
