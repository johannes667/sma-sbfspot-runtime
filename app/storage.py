import json, os, sqlite3
from config import STATE_FILE, DB_FILE, DATA_DIR
def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    with sqlite3.connect(DB_FILE) as con:
        con.execute('CREATE TABLE IF NOT EXISTS samples (ts TEXT PRIMARY KEY, power_w REAL, energy_today_kwh REAL, energy_total_kwh REAL, temperature_c REAL, pdc1_w REAL, pdc2_w REAL, efficiency_percent REAL)')
        con.commit()
def write_state(state):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp=STATE_FILE+'.tmp'
    with open(tmp,'w',encoding='utf-8') as f: json.dump(state,f,indent=2,ensure_ascii=False)
    os.replace(tmp,STATE_FILE)
def read_state():
    try:
        with open(STATE_FILE,encoding='utf-8') as f: return json.load(f)
    except Exception as e: return {'status':'waiting','timestamp':None,'last_error':str(e)}
def save_sample(s):
    init_db()
    with sqlite3.connect(DB_FILE) as con:
        con.execute('INSERT OR REPLACE INTO samples VALUES (?,?,?,?,?,?,?,?)',(s.get('timestamp'),s.get('power_w'),s.get('energy_today_kwh'),s.get('energy_total_kwh'),s.get('temperature_c'),s.get('pdc1_w'),s.get('pdc2_w'),s.get('efficiency_percent')))
        con.commit()
def history(limit=288):
    init_db()
    with sqlite3.connect(DB_FILE) as con:
        con.row_factory=sqlite3.Row
        rows=con.execute('SELECT * FROM samples ORDER BY ts DESC LIMIT ?', (limit,)).fetchall()
    return [dict(r) for r in reversed(rows)]
