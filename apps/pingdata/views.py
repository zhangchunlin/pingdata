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
        date = date[:10]
        dpath = os.path.join(settings.PINGDATA.data_dir,
                             "".join(date.split("-")))
        if not os.path.isdir(dpath):
            log.warn("dir %s not exists" % (dpath))
            return json([])
        options = []
        for i in os.listdir(dpath):
            if i == "max.json":
                continue
            l = i.split("_")
            if not len(l) == 2:
                log.error("unknown file '%s' found in '%s'" % (i, dpath))
                continue
            options.append({"value": i, "label": i})
        return json(options)

    def api_get_chart_data(self):
        selected = json_.loads(request.values.get("selected"))
        date = request.values.get("date")
        date = date[:10]
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

    def api_get_chart_data_trend(self):
        start, end = json_.loads(request.values.get("date_range"))
        start, end = "".join(start[:10].split("-")), "".join(end[:10].split("-"))
        trend_data = self._get_trend(start, end)
        dimensions_set = set()
        source = []
        for dstr, data in trend_data:
            if not data:
                data = {}
            for k in data:
                if k not in dimensions_set:
                    dimensions_set.add(k)
            data["date_str"] = "%s-%s-%s"%(dstr[:4], dstr[4:6], dstr[6:8])
            source.append(data)
        dimensions = ["date_str"] + sorted(list(dimensions_set))
        return json({
            "series": [{"type": "line"}]*len(dimensions_set),
            "dimensions": dimensions,
            "source": source
        })
    
    def _get_trend(self, start, end):
        def get_dstr():
            dt = pendulum.from_format(start, "YYYYMMDD")
            delta = pendulum.from_format(end, "YYYYMMDD") - dt
            for i in range(delta.days+1):
                yield dt.format("YYYYMMDD")
                dt = dt.add(days=1)
        def get_data():
            data_dir = os.path.realpath(settings.PINGDATA.data_dir)
            def get_max_lost():
                for dstr in get_dstr():
                    dpath = os.path.join(data_dir, dstr)
                    assert(os.path.realpath(dpath).startswith(data_dir))
                    yield dstr, self._get_max_lost(dpath)
            return [(dstr, data) for dstr, data in get_max_lost()]
        return get_data()

    def _get_max_lost(self, dpath):
        if not os.path.exists(dpath):
            return
        need_to_generate = False
        max_fpath = os.path.join(dpath, "max.json")
        found = os.path.isfile(max_fpath)
        need_to_generate = not found
        def iter_data_fpath():
            for fname in os.listdir(dpath):
                if fname == "max.json":
                    continue
                yield fname, os.path.join(dpath, fname)

        if found:
            mt1 = os.stat(max_fpath).st_mtime
            for _, fpath in iter_data_fpath():
                if os.path.isfile(fpath):
                    if os.stat(fpath).st_mtime>mt1:
                        need_to_generate = True
        if need_to_generate:
            def iter_max_lost():
                for fname, fpath in iter_data_fpath():
                    with open(fpath) as f:
                        max_lost = 0
                        for l in f:
                            l = l.strip()
                            if l:
                                d = json_.loads(l)
                                lostp = int(d["lostp"])
                                if lostp > max_lost:
                                    max_lost = lostp
                        yield(fname, max_lost)
            d = dict((fname, max_lost) for fname, max_lost in iter_max_lost())
            json_.dump(d, open(max_fpath, "w"))
            return d
        else:
            return json_.load(open(max_fpath))
