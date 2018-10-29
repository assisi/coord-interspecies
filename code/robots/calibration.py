#!/usr/bin/env python
# -*- coding: utf-8 -*-

from assisipy import casu
import time, os
from numpy import array
import argparse
import yaml


class CalibrateSensors(object):
    TSTR_FMT = "%Y/%m/%d-%H:%M:%S-%Z"

    def __init__(self, casu_name, logname, conf_file=None, DO_LOG=True):

        self._rtc_pth, self._rtc_fname = os.path.split(casu_name)
        if self._rtc_fname.endswith('.rtc'):
            self.name = self._rtc_fname[:-4]
        else:
            self.name = self._rtc_fname

        self.parse_conf(conf_file)

        self.logname = logname

        self._casu = casu.Casu(rtc_file_name=os.path.join(self._rtc_pth, self.name + ".rtc"), log=DO_LOG)
        self.calib_data = {}
        self.update_calib_time(time.time())
        self.calib_data['IR'] = []

    def update_calib_time(self, now_time):
        self.calib_data['date'] = time.strftime(self.TSTR_FMT, time.gmtime(now_time))
        self.calib_data['date_raw'] = now_time


    def parse_conf(self, conf_file):
        self._conf = {}
        if conf_file is not None:
            with open(conf_file) as f:
                self._conf = yaml.safe_load(f)

        self.use_diag_led = self._conf.get('use_diag_led', True)
        self.verb         = self._conf.get('verbose', 0)

        _ir = self._conf.get('IR', {})
        self.calib_steps  = _ir.get('calib_steps', 30)
        self.calib_gain   = _ir.get('calib_gain', 1.2)
        self.t_interval   = _ir.get('t_interval', 0.1)
        self.min_thresh   = _ir.get('min_thresh', 3.14)

        if self.verb > 4: print "[I] read config from {}".format(conf_file)



    def calibrate(self):
        '''
        wrapper for all calibration procedures.
        '''
        self.calibrate_ir()


    def calibrate_ir(self):
        '''
        read IR sensors several times, take the highest reading seen
        as the threshold (with a multiplier)


        '''
        base_ir_thresholds = array([self.min_thresh] * 7) # default values
        if self.use_diag_led:
            self._casu.set_diagnostic_led_rgb(b=1, r=0, g=0)

        # read sensors
        for stp in xrange(self.calib_steps):
            if self.verb > 4: print "calib step {}".format(stp)
            for i, v in enumerate(self._casu.get_ir_raw_value(casu.ARRAY)):
                if v > base_ir_thresholds[i]:
                    base_ir_thresholds[i] = v

            time.sleep(self.t_interval*0.9)
            if self.use_diag_led:
                self._casu.set_diagnostic_led_rgb(b=0, r=0.1, g=0.1)
            time.sleep(self.t_interval*0.1)
            if self.use_diag_led:
                self._casu.set_diagnostic_led_rgb(b=1, r=0, g=0)


        # compute calibrate values
        self.ir_thresholds = base_ir_thresholds * self.calib_gain
        self.calib_data['IR'] = self.ir_thresholds.tolist()
        if self.verb > 4: print "[I] will dump these values:", self.calib_data['IR']

        self.update_calib_time(time.time())

        # finish procedure
        if self.use_diag_led:
            self._casu.set_diagnostic_led_rgb(b=0, r=0, g=0)
            self._casu.diagnostic_led_standby()


    def write_levels_to_file(self):
        '''
        Write an array of IR levels to calibration file

        '''
        _dump = {self.name:self.calib_data}
        s = yaml.safe_dump(_dump, default_flow_style=False)
        with open(self.logname, "w") as f:
            f.write(s + "\n")



if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('name', )
    parser.add_argument('-c', '--conf', type=str, default=None)
    parser.add_argument('-o', '--output', type=str, default=None)
    args = parser.parse_args()

    c = CalibrateSensors(args.name, logname=args.output, conf_file=args.conf)
    if c.verb > 0: print "Calibration - connected to {}".format(c.name)
    try:
        c.calibrate()
        c.write_levels_to_file()
    except KeyboardInterrupt:
        c._casu.stop()

    if c.verb > 0: print "Calibration {} - done".format(c.name)
    s = "{:.1f},".join([str(elem) for elem in c.calib_data['IR']])
    if c.verb > 1: print "  IR values: [{}]".format(s)


