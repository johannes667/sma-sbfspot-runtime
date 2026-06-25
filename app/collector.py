import os, subprocess
from datetime import datetime
from config import SBFSPOT_CFG
from parser import parse_output
from storage import write_state, save_sample, init_db
from mqtt_client import publish_state, publish_discovery
def now(): return datetime.now().astimezone().isoformat(timespec='seconds')
def main():
    init_db(); publish_discovery()
    if not os.path.exists(SBFSPOT_CFG):
        s={'status':'config_missing','timestamp':now(),'last_error':f'{SBFSPOT_CFG} fehlt'}; write_state(s); publish_state(s); return
    proc=subprocess.run(['SBFspot','-finq','-nocsv',f'-cfg:{SBFSPOT_CFG}'],cwd='/',text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=180)
    out=proc.stdout or ''
    parsed=parse_output(out)
    ok=proc.returncode==0 and parsed.get('raw_ok')
    state={'status':'online' if ok else 'error','timestamp':now(),**{k:v for k,v in parsed.items() if k!='raw_ok'},'last_error':'' if ok else out[-4000:]}
    write_state(state); publish_state(state)
    if ok: save_sample(state)
    print(out); print('collector_status='+state['status'])
if __name__=='__main__': main()
