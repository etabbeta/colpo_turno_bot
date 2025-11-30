#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, json, random, logging, datetime, asyncio, pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ===========================
# CONFIG
# ===========================
TOKEN = os.getenv("BOT_TOKEN")
GROUP = int(os.getenv("GROUP_CHAT_ID")) if os.getenv("GROUP_CHAT_ID") else None

WORKERS = ["Giova","Stefi","Fede","Daniela","Anastasia","Ros","Marti"]
DAYS = ["lunedì","martedì","mercoledì","giovedì","venerdì","sabato","domenica"]
TZ = pytz.timezone("Europe/Rome")

DATA = "data_colpoturno"
ROT = f"{DATA}/rotazioni.json"
ASS = f"{DATA}/assenze.json"
PREF = f"{DATA}/preferenze.json"

if not os.path.exists(DATA): os.makedirs(DATA)

load = lambda p,d : json.load(open(p,"r",encoding="utf-8")) if os.path.exists(p) else d
save = lambda p,d : open(p,"w",encoding="utf-8").write(json.dumps(d,indent=2,ensure_ascii=False))

rot = load(ROT,{"history":[]})
ass = load(ASS,{})
pref = load(PREF,{})

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("BOT")

# ===========================
# CORE GENERATOR
# ===========================
def idx(g):
    m={"lun":0,"lunedì":0,"mar":1,"martedì":1,"mer":2,"mercoledì":2,
       "gio":3,"giovedì":3,"ven":4,"venerdì":4,"sab":5,"sabato":5,
       "dom":6,"domenica":6}
    return m.get(g.lower().strip(),None)

def pairs(w):
    return [(d1,d2) for d1 in range(7) for d2 in range(d1+1,7)
            if abs(d2-d1)>=3 and d1 not in ass.get(w,[]) and d2 not in ass.get(w,[])]

def gen(max=5000):
    from random import shuffle
    last=set()
    if rot["history"]:
        for d in rot["history"][-1]["schedule"]:
            if len(d)==2:last.add(frozenset(d))

    order=WORKERS[:];shuffle(order)
    order=sorted(order,key=lambda w:len(pairs(w)))

    for _ in range(max):
        slot=[2]*7;assign={}
        for w in order:
            ps=pairs(w)[:];shuffle(ps)
            ok=None
            for d1,d2 in ps:
                if slot[d1]>0 and slot[d2]>0:
                    ok=(d1,d2);break
            if not ok:break
            assign[w]=ok;slot[ok[0]]-=1;slot[ok[1]]-=1
        if any(s>0 for s in slot):continue

        out=[[] for _ in range(7)]
        for w,(a,b) in assign.items():out[a].append(w);out[b].append(w)

        rep=0
        for d in out:
            if len(d)==2 and frozenset(d) in last:rep+=1

        if rep<=1:return out
    return None

def fmt(s): return "\n".join(f"*{DAYS[i]}*: {', '.join(d)}" for i,d in enumerate(s))

# ===========================
# COMMANDS
# ===========================
async def start(update,ctx): await update.message.reply_text("Bot attivo ✔",parse_mode="Markdown")

async def rigenera(update,ctx):
    sch=gen()
    if not sch:return await update.message.reply_text("Impossibile generare.")
    rot["history"].append({"when":str(datetime.datetime.now()),"schedule":sch});save(ROT,rot)
    await update.message.reply_text("*Nuova settimana:*\n\n"+fmt(sch),parse_mode="Markdown")

async def oggi(update,ctx):
    if not rot["history"]:return await update.message.reply_text("Nessuna pianificazione.")
    d=datetime.datetime.now(TZ).weekday()
    sch=rot["history"][-1]["schedule"][d]
    await update.message.reply_text(f"Oggi {DAYS[d]} → {', '.join(sch)}",parse_mode="Markdown")

async def unknown(update,ctx):
    await update.message.reply_text("Comando non valido ❌")

# ===========================
# MAIN
# ===========================
async def run():
    if not TOKEN:return print("❌ BOT_TOKEN mancante")
    app=Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start",start))
    app.add_handler(CommandHandler("rigenera",rigenera))
    app.add_handler(CommandHandler("oggi",oggi))
    app.add_handler(MessageHandler(filters.COMMAND,unknown))

    scheduler = AsyncIOScheduler(timezone=TZ)
    scheduler.add_job(lambda: asyncio.create_task(rigenera_auto(app)),
                      "cron",day_of_week="sun",hour=20,minute=0)
    scheduler.add_job(lambda: asyncio.create_task(today_auto(app)),
                      "cron",hour=7,minute=30)
    scheduler.start()

    print("BOT ONLINE 🚀")
    await app.run_polling()

async def rigenera_auto(app):
    sch=gen()
    if n







