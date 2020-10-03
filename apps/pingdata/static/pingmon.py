#! /usr/bin/env python

import os
import sys
import re
import argparse
import asyncio
import aiohttp
import urllib
import time
import logging

logging.basicConfig(level=logging.INFO,
                format='%(asctime)s %(levelname)s %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S')
log = logging.getLogger(__name__)

ERR_EMPTY_CONFIG = 1

class PingMonitor(object):
    def __init__(self):
        rawstr = r"""(\d*) packets transmitted, (\d*) received, (\d*)% packet loss, time (\d*)ms"""
        self.cobj = re.compile(rawstr)
    
    def main(self):
        parser = argparse.ArgumentParser()
        parser.add_argument('-s','--server-url', default="http://localhost:8000", help = 'server url')
        self.args = parser.parse_args()

        self.url_get_cfg = urllib.parse.urljoin(self.args.server_url, "pingdata/api_get_ping_cfg")
        self.url_add_data = urllib.parse.urljoin(self.args.server_url, "pingdata/api_add_data")

        self.loop = asyncio.get_event_loop()
        self.loop.run_until_complete(self.pingmon())

    async def pingmon(self):
        async with aiohttp.ClientSession() as session:
            self.session = session
            while True:
                async with session.get(self.url_get_cfg, verify_ssl = False) as resp:
                    cfg = await resp.json()
                    self.cfg_rsp = cfg
                    self.pingcfg = cfg.get("pingcfg")
                    self.ip = cfg.get("ip_from")
                    next_waiting_secs = cfg["next_waiting_secs"]
                    if next_waiting_secs>0:
                        log.info("sleep %s seconds before next ping"%(next_waiting_secs))
                        await asyncio.sleep(next_waiting_secs)

                    ip_to = cfg.get("ip_to", [])
                    if not ip_to:
                        log.error("empty config from server")
                        sys.exit(ERR_EMPTY_CONFIG)
                    for i in ip_to:
                        task = asyncio.create_task(self.pinghost(i))
            log.error("finished")

    async def pinghost(self, host):
        timestamp = self.cfg_rsp["next_timestamp"]
        datetime_str = self.cfg_rsp["next_datetime_str"]

        log.info("+%s %s %s"%(self.ip, host, datetime_str))
        cmd = "ping %s -c %s"%(host, self.pingcfg.get("c", 10))

        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf8")
        mobj = self.cobj.search(stdout)
        l = mobj.groups()
        if len(l)==4:
            sent, receive, lostp, timems = l
            log.info("-%s %s %s %s %s %s %s"%(self.ip, host, datetime_str, sent, receive, lostp, timems))
            task = asyncio.create_task(self.submit_data(dict(
                ip_from=self.ip, ip_to=host, timestamp=timestamp, datetime_str = datetime_str,
                sent=sent, receive=receive, lostp=lostp, timems=timems,
            )))
        else:
            log.error("cannot found ping result in stdout")

    async def submit_data(self, data):
        retry = self.pingcfg.get("retry", 6)
        retry_wait_secs = self.pingcfg.get("retry_wait_secs", 20)
        for i in range(retry):
            try:
                async with self.session.post(self.url_add_data, data=data, verify_ssl = False) as resp:
                    if resp.status != 200:
                        log.error("get resp '%s', status: %s"%(await resp.text(), resp.status))
                        await asyncio.sleep(retry_wait_secs)
                        continue
                    respd = await resp.json()
                    if respd and respd.get("ret")==0:
                        log.info(" update ok: %s %s %s"%(data.get("ip_from"), data.get("ip_to"), data.get("datetime_str")))
                        break
                    else:
                        log.error("get resp: %s"%(respd))
            except Exception as e:
                log.error("post get error: %s"%(e))
                await asyncio.sleep(retry_wait_secs)
                continue
            log.error("fail to submit data: %s %s %s"%(data.get("ip_from"), data.get("ip_to"), data.get("datetime_str")))
            await asyncio.sleep(retry_wait_secs)

if __name__ == "__main__":
    o = PingMonitor()
    o.main()
