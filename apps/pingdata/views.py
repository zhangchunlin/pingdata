# coding=utf-8
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
    def __begin__(self):
        self.cntz = pendulum.timezone("Asia/Shanghai")

    @expose('')
    def index(self):
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
        last_minute = dt.minute-(dt.minute % everyxmin)
        nextdt = dt.set(minute=last_minute, second=0).add(minutes=everyxmin)
        next_waiting_secs = (nextdt-dt).seconds
        return nextdt.int_timestamp, nextdt.to_datetime_string(), next_waiting_secs

    def api_add_data(self):
        d = request.values.to_dict()
        dt = pendulum.now()
        d["submit_timestamp"] = dt.int_timestamp
        d["submit_datetime_str"] = dt.to_datetime_string()
        ret = self._save_data(d)
        return json({"ret": ret, "msg": "data save ok!"})

    def _save_data(self, d):
        if not d:
            log.error("bad data: %s" % (d))
            return ERR_BAD_PARAM
        timestamp = d.get("timestamp")
        if not timestamp:
            log.error("bad data without timestamp: %s" % (d))
            return ERR_BAD_PARAM
        cndt = self.cntz.convert(pendulum.from_timestamp(int(timestamp)))
        datestr = cndt.format("YYYYMMDD")
        fname = "%s_%s" % (d.get("ip_from"), d.get("ip_to"))
        dpath = os.path.join(settings.PINGDATA.data_dir, datestr)
        if not os.path.exists(dpath):
            log.info("make new dir: %s" % (dpath))
            os.makedirs(dpath)
        fpath = os.path.join(dpath, fname)
        with open(fpath, "a") as f:
            f.write(json_.dumps(d))
            f.write("\n")
            return 0
        return ERR_FAIL_TO_SAVE

    def api_get_options(self):
        date = request.values.get("date")
        if not date:
            log.error("bad param: date = %s" % (date))
            return json([])
        dpath = os.path.join(settings.PINGDATA.data_dir,
                             "".join(date.split("-")))
        if not os.path.isdir(dpath):
            log.warn("dir %s not exists" % (dpath))
            return json([])
        options = []
        for i in os.listdir(dpath):
            l = i.split("_")
            if not len(l) == 2:
                log.error("unknown file '%s' found in '%s'" % (i, dpath))
                continue
            options.append({"value": i, "label": i})
        return json(options)

    def api_get_chart_data(self):
        selected = json_.loads(request.values.get("selected"))
        date = request.values.get("date")
        dname = "".join(date.split("-"))

        series = []
        dimensions = ["time_str"]
        raw_source = {}
        for fname in sorted(selected):
            fpath = os.path.join(settings.PINGDATA.data_dir, dname, fname)
            if os.path.isfile(fpath):
                dimensions.append(fname)
                with open(fpath) as f:
                    source_data = {"from_to": fname}
                    for l in f:
                        if l:
                            d = json_.loads(l)
                            time_str = d["datetime_str"][-8:]
                            time_str_data = raw_source.get(time_str)
                            if not time_str_data:
                                time_str_data = {}
                                raw_source[time_str] = time_str_data
                            time_str_data[fname] = d["lostp"]
                    series.append({"type": "line"})
        source = []
        for time_str in sorted(raw_source.keys()):
            d = raw_source[time_str]
            d["time_str"] = time_str
            for k in list(d.keys()):
                if d[k] == '0':
                    del d[k]
            source.append(d)
        return json({
            "series": series,
            "dimensions": dimensions,
            "source": source
        })
