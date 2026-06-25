import re
PATTERNS={
 'power_w':[r'SPOT_PACTOT\s*:\s*([-+]?\d+(?:[.,]\d+)?)'],
 'pac1_w':[r'SPOT_PAC1\s*:\s*([-+]?\d+(?:[.,]\d+)?)'],
 'pac2_w':[r'SPOT_PAC2\s*:\s*([-+]?\d+(?:[.,]\d+)?)'],
 'pac3_w':[r'SPOT_PAC3\s*:\s*([-+]?\d+(?:[.,]\d+)?)'],
 'energy_today_kwh':[r'SPOT_ETODAY\s*:\s*([-+]?\d+(?:[.,]\d+)?)',r'EToday:\s*([-+]?\d+(?:[.,]\d+)?)kWh'],
 'energy_total_kwh':[r'SPOT_ETOTAL\s*:\s*([-+]?\d+(?:[.,]\d+)?)',r'ETotal:\s*([-+]?\d+(?:[.,]\d+)?)kWh'],
 'pdc1_w':[r'SPOT_PDC1\s*:\s*([-+]?\d+(?:[.,]\d+)?)'],
 'pdc2_w':[r'SPOT_PDC2\s*:\s*([-+]?\d+(?:[.,]\d+)?)'],
 'dc_voltage_1_v':[r'SPOT_UDC1\s*:\s*([-+]?\d+(?:[.,]\d+)?)'],
 'dc_voltage_2_v':[r'SPOT_UDC2\s*:\s*([-+]?\d+(?:[.,]\d+)?)'],
 'dc_current_1_a':[r'SPOT_IDC1\s*:\s*([-+]?\d+(?:[.,]\d+)?)'],
 'dc_current_2_a':[r'SPOT_IDC2\s*:\s*([-+]?\d+(?:[.,]\d+)?)'],
 'ac_voltage_1_v':[r'SPOT_UAC1\s*:\s*([-+]?\d+(?:[.,]\d+)?)'],
 'ac_current_1_a':[r'SPOT_IAC1\s*:\s*([-+]?\d+(?:[.,]\d+)?)'],
 'frequency_hz':[r'SPOT_FREQ\s*:\s*([-+]?\d+(?:[.,]\d+)?)'],
 'temperature_c':[r'Device Temperature:\s*([-+]?\d+(?:[.,]\d+)?)'],
 'operation_time_h':[r'SPOT_OPERTM\s*:\s*([-+]?\d+(?:[.,]\d+)?)'],
 'feed_in_time_h':[r'SPOT_FEEDTM\s*:\s*([-+]?\d+(?:[.,]\d+)?)'],
}
def num(v):
    try:
        x=float(v.replace(',','.'))
        return int(x) if x.is_integer() else x
    except Exception: return None
def parse_output(text):
    data={}
    for k, pats in PATTERNS.items():
        data[k]=None
        for p in pats:
            m=re.search(p,text,re.I)
            if m:
                data[k]=num(m.group(1)); break
    if data.get('pdc1_w') is not None and data.get('pdc2_w') is not None:
        data['pdc_total_w']=data['pdc1_w']+data['pdc2_w']
    else: data['pdc_total_w']=None
    pdc=data.get('pdc_total_w'); pac=data.get('power_w')
    data['efficiency_percent']=round((pac/pdc)*100,2) if pdc and pac is not None and pdc>0 else None
    m=re.search(r'Serial Nr:.*?\((\d+)\)',text) or re.search(r'SN:\s*(\d+)',text)
    data['serial']=m.group(1) if m else None
    data['raw_ok']='INFO: Done.' in text or any(data.get(k) is not None for k in ('power_w','energy_today_kwh'))
    return data
