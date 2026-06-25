import json, subprocess
from config import *
def _pub(topic,payload,retain=True):
    if not MQTT_ENABLE: return
    cmd=['mosquitto_pub','-h',MQTT_HOST,'-p',str(MQTT_PORT),'-t',topic,'-m',str(payload)]
    if retain and MQTT_RETAIN: cmd.append('-r')
    if MQTT_USER: cmd+=['-u',MQTT_USER]
    if MQTT_PASSWORD: cmd+=['-P',MQTT_PASSWORD]
    subprocess.run(cmd,check=False,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
def publish_state(s):
    if not MQTT_ENABLE: return
    _pub(f'{MQTT_BASE_TOPIC}/status', s.get('status','unknown'), True)
    for k,v in s.items():
        if k in ('last_error','raw_output') or v is None: continue
        if isinstance(v,(int,float,str)): _pub(f'{MQTT_BASE_TOPIC}/{k}', v, True)
def publish_discovery():
    if not (MQTT_ENABLE and HA_DISCOVERY): return
    device={'identifiers':[DEVICE_ID],'name':DEVICE_NAME,'manufacturer':'SMA','model':'SBFspot Bluetooth'}
    sensors={
      'power_w':('Leistung','W','power','measurement'), 'pac1_w':('AC Leistung L1','W','power','measurement'),
      'energy_today_kwh':('Energie Heute','kWh','energy','total_increasing'), 'energy_total_kwh':('Energie Gesamt','kWh','energy','total_increasing'),
      'temperature_c':('Temperatur','°C','temperature','measurement'), 'dc_voltage_1_v':('DC1 Spannung','V','voltage','measurement'),
      'dc_current_1_a':('DC1 Strom','A','current','measurement'), 'pdc1_w':('DC1 Leistung','W','power','measurement'),
      'dc_voltage_2_v':('DC2 Spannung','V','voltage','measurement'), 'dc_current_2_a':('DC2 Strom','A','current','measurement'),
      'pdc2_w':('DC2 Leistung','W','power','measurement'), 'frequency_hz':('Netzfrequenz','Hz','frequency','measurement'),
      'efficiency_percent':('Wirkungsgrad','%',None,'measurement')}
    for obj,(name,unit,dc,sc) in sensors.items():
        payload={'name':f'{DEVICE_NAME} {name}','unique_id':f'{DEVICE_ID}_{obj}','state_topic':f'{MQTT_BASE_TOPIC}/{obj}','availability_topic':f'{MQTT_BASE_TOPIC}/status','payload_available':'online','payload_not_available':'offline','unit_of_measurement':unit,'state_class':sc,'device':device}
        if dc: payload['device_class']=dc
        _pub(f'{HA_DISCOVERY_PREFIX}/sensor/{DEVICE_ID}/{obj}/config', json.dumps(payload), True)
