#coding=utf-8
from uliweb import expose, functions, settings
import pendulum
import logging
import os
import json as json_

log = logging.getLogger('pingdata')

ERR_BAD_PARAM = 1
ERR_FAIL_TO_SAVE = 2

@expose('/pingdata')
class PingData(object):
    @expose('')
    def index():
        return {}
    
    def api_get_ping_cfg(self):
        ip = request.environ['REMOTE_ADDR']
        next_timestamp, next_datetime_str, next_waiting_secs = self._get_next_waiting_secs()
        return json({
            "ip_from": ip,
            "ip_to": settings.PINGDEST.get(ip),
            "pingcfg": dict(settings.PINGCFG),
            "next_timestamp": next_timestamp,
            "next_datetime_str": next_datetime_str,
            "next_waiting_secs": next_waiting_secs,
        })
    
    def _get_next_waiting_secs(self):
        dt = pendulum.now()
        everyxmin = settings.PINGCFG.everyxmin
        last_minute = dt.minute-(dt.minute%everyxmin)
        nextdt = dt.set(minute = last_minute, second = 0).add(minutes=everyxmin)
        next_waiting_secs = (nextdt-dt).seconds
        return nextdt.int_timestamp, nextdt.to_datetime_string(), next_waiting_secs
    
    def api_add_data(self):
        d = request.values.to_dict()
        dt = pendulum.now()
        d["submit_timestamp"] = dt.int_timestamp
        d["submit_datetime_str"] = dt.to_datetime_string()
        ret = self._save_data(d)
        return json({"ret": ret, "msg":"data save ok!"})

    def _save_data(self, d):
        if not d:
            log.error("bad data: %s"%(d))
            return ERR_BAD_PARAM
        timestamp = d.get("timestamp")
        if not timestamp:
            log.error("bad data without timestamp: %s"%(d))
            return ERR_BAD_PARAM
        dt = pendulum.from_timestamp(int(timestamp))
        datestr = dt.format("YYYYMMDD")
        fname = "%s_%s"%(d.get("ip_from"),d.get("ip_to"))
        dpath = os.path.join(settings.PINGDATA.data_dir, datestr)
        if not os.path.exists(dpath):
            log.info("make new dir: %s"%(dpath))
            os.makedirs(dpath)
        fpath = os.path.join(dpath, fname)
        with open(fpath, "a") as f:
            f.write( json_.dumps(d))
            f.write("\n")
            return 0
        return ERR_FAIL_TO_SAVE
