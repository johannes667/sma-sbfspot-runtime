import os, subprocess
from datetime import datetime
from config import SBFSPOT_CFG
from parser import parse_output
from storage import write_state, save_sample, init_db
from mqtt_client import publish_state, publish_discovery

def now_iso(): return datetime.now().astimezone().isoformat(timespec='seconds')

def main():
    init_db(); publish_discovery()
    if not os.path.exists(SBFSPOT_CFG):
        state={'status':'config_missing','timestamp':now_iso(),'last_error':f'{SBFSPOT_CFG} fehlt'}
        write_state(state); publish_state(state); return
    try:
        proc=subprocess.run(['SBFspot','-finq','-nocsv',f'-cfg:{SBFSPOT_CFG}'], cwd='/', text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=240)
        output=proc.stdout or ''
        parsed=parse_output(output)
        ok=proc.returncode==0 and parsed.get('raw_ok')
        state={'status':'online' if ok else 'error','timestamp':now_iso(),**{k:v for k,v in parsed.items() if k!='raw_ok'},'last_error':'' if ok else output[-4000:]}
    except Exception as e:
        state={'status':'error','timestamp':now_iso(),'last_error':str(e)}
    write_state(state); publish_state(state)
    if state.get('status')=='online': save_sample(state)
    print(f"collector_status={state.get('status')}")
    if state.get('last_error'): print(state.get('last_error'))
if __name__=='__main__': main()
