#!/usr/bin/env python
# -*- coding: utf-8 -*-

'''
a shell for CASU controller with basic functions including
- setup
- config file parsing
- logfile handling

Expectation is that custom variants will be derived from this, implementing
specific experimental regimes as required.

'''

from assisipy import casu
import os
import yaml
import time, datetime
import numpy as np
import calibration

#{{{ push_data_1d utility
def push_data_1d(arr, new):
    '''
    shift elements along one, and push new data onto the front. In-place
    operation. (since np.roll does not operate in-place, wrap as a function)

    '''
    # we can't seem to use roll because it requires knowing the variable name
    # ahead of time and thus is not flexible.  MAybe I missed a trick but even
    # attempting to spoof a pass-by-reference doesn't gain flexibility.
    # (http://stackoverflow.com/a/986145)
    # so instead, rely on the array mechanism and reassign parts.
    l = len(arr)
    arr[1:] = arr[0:l-1]
    arr[0] = new

#}}}

class BaseCASUCtrl(object):
    #{{{ class-level defaults for externally-set params
    MANUAL_CALIB_OVERRIDE = False # if leaving the bees in arena, while developing
    MANUAL_CALIB_SETPOINT = 720.0
    DEV_VERB = 5
    DEV_VERB_deep = 0
    VERB = 1

    AVG_HIST_LEN = 60
    HIST_LEN = 60
    MAX_MSG_AGE = 20
    MAX_SENSORS = 6.0
    SELF_WEIGHT = 1.0
    MIN_TEMP = 28.0
    MAX_TEMP = 36.0

    ENABLE_TEMP = True
    REF_DEVIATE = 0.5
    MAIN_LOOP_INTERVAL = 0.2
    REF_UPDATE_INTERVAL = 10.0
    ENABLE_SUPPRESS_LOW = False
    EXOG_SIGNAL_WEAK_WEIGHT    = 1.5
    EXOG_SIGNAL_STRONG_WEIGHT  = 0.0
    EXOG_BONUS_START_MINS      = 10.0
    EXP_CAMODEL_DELTATEMPS     = False  # Tref target relative(1) or absolute(0)
    EXOG_BIAS = 0.0

    SHOW_CALIB_LED_MINS = 0.5
    SYNCFLASH = True
    SYNC_INTERVAL = 20.0
    FREQ_RPT_INPUTS = 1

    INIT_NOHEAT_PERIOD_MINS  = 0.0
    INIT_FIXHEAT_PERIOD_MINS = 0.0
    INIT_FIXHEAT_TEMP        = 28.0
    DT_MAX                   = 0.25

    TREF_REACH_TOLERANCE     = 0.25
    SEED_FIXHEAT_PERIOD_MINS = 0.0
    SEED_FIXHEAT_TEMP        = 28.0

    WEIGHT_INVERT_TIME_MINS  = 5.0
    WEIGHT_INVERT_FACTOR     = -1.0
    WEIGHT_INVERT_ENABLE     = False

    FISH_INPUT_NETWORK  = {}
    FISH_OUTPUT_NETWORK = {}
    FISH_HIST_LEN = 120

    #}}}

    #{{{ initialiser
    # parts
    # 1. load config / override settings.
    # 2. setup logging
    # 3. calibration

    def _init_casu_name(self, casu_name):
        # identify casu name
        self._rtc_pth, self._rtc_fname = os.path.split(casu_name)
        if self._rtc_fname.endswith('.rtc'):
            self.name = self._rtc_fname[:-4]
        else:
            self.name = self._rtc_fname

        self.name_num = (''.join(_ for _ in self.name if _.isdigit()))


    def _init_config(self, conf_file):
        # read all the configuration
        self.parse_conf(conf_file)

        # derived params/variables.
        self.T_RANGE  = self.MAX_TEMP - self.MIN_TEMP
        if self.AVG_HIST_LEN > self.HIST_LEN:
            print "[W] AVG_HIST_LEN of {} does not fit into {} len buffers, increasing".format(self.AVG_HIST_LEN, self.HIST_LEN)
            self.HIST_LEN = self.AVG_HIST_LEN

    def _init_logging(self, logpath):
        # set up logging
        self.logpath = logpath
        if self.logpath is None:
            self.logpath = "."

        self._logtime= time.strftime("%H:%M:%S-%Z", time.gmtime())
        self.logfile = os.path.join(
            self.logpath, "{}-{}.log".format(self.name, self._logtime))
        self.setup_logger(append=False, delimiter=';')

    def _init_calibration(self, calib_conf, cal_logname="temp_calib_log"):
        '''
        uses aux library for calibration regime; populates self.calib_data dict
        '''
        # run calibration procedure
        self.calibrator = calibration.CalibrateSensors(
            casu_name=self.name, logname=cal_logname, conf_file=calib_conf)

        self.calibrator.calibrate()
        self.calibrator.write_levels_to_file()
        self.calib_data = dict(self.calibrator.calib_data)
        if self.MANUAL_CALIB_OVERRIDE:
            for i in xrange(len(self.calib_data['IR'])):
                self.calib_data['IR'][i] = float(self.MANUAL_CALIB_SETPOINT)

        if self.verb > 1:
            print "[I]{} we have IR calib thresholds of".format(self.name)
            print "[" + ",".join("{:.1f}".format(elem) for elem in self.calib_data['IR']) + "]"

        self.calibrator._casu.set_diagnostic_led_rgb(b=0.25, r=0, g=0)
        self.INIT_LED = True
        # see/set value of self.SHOW_CALIB_LED_MINS if default 0.5m not useful

    def _init_common(self, casu_name, logpath, conf_file=None, calib_conf=None):
        # basic setup - configuration, sensor calibration, loggin
        self._init_casu_name(casu_name)
        self._init_config(conf_file)
        self._init_states()
        self._init_calibration(calib_conf=calib_conf, cal_logname="temp_calib_log")
        self._init_logging(logpath)
        self._init_synclog()
        # now attach to the casu device. (already attaced in the calib stage)
        self._casu = self.calibrator._casu
        self.__stopped = False

    def _init_synclog(self):
        # should only be done after log is parsed - also logpath
        if self.SYNCFLASH:
            fn_synclog = '{}/{}-{}.sync.log'.format(
                self.logpath, self.name, self._logtime)
            self.synclog = open(fn_synclog, 'w', 0)
            self.synclog.write("# started at {}\n".format(time.time()))
            self.sync_cnt = 0
            self.last_synchflash_time = time.time()





    def __init__(self, casu_name, logpath,
                 conf_file=None, calib_conf=None):
        self._init_common(casu_name, logpath, conf_file=conf_file,
                          calib_conf=calib_conf)

        self.init_upd_time = time.time()



    #}}}

    #{{{ parse external config
    def parse_conf(self, conf_file):
        self._ext_conf = {}
        if conf_file is not None:
            with open(conf_file) as f:
                self._ext_conf = yaml.safe_load(f)

        for var in [
                'MANUAL_CALIB_OVERRIDE',
                'DEV_VERB',
                'DEV_VERB_deep',
                'VERB',
                'AVG_HIST_LEN',
                'HIST_LEN',
                'MAX_MSG_AGE',
                'MAX_SENSORS',
                'SELF_WEIGHT',
                'MIN_TEMP',
                'MAX_TEMP',
                'ENABLE_TEMP',
                'REF_DEVIATE',
                'REF_UPDATE_INTERVAL',
                'ENABLE_SUPPRESS_LOW',
                'SHOW_CALIB_LED_MINS',
                'MAIN_LOOP_INTERVAL',
                'SYNCFLASH',
                'SYNC_INTERVAL',
                'EXP_CAMODEL_DELTATEMPS',
                'EXOG_BIAS',
                'INIT_NOHEAT_PERIOD_MINS',
                'INIT_FIXHEAT_PERIOD_MINS',
                'INIT_FIXHEAT_TEMP',
                'DT_MAX',
                'TREF_REACH_TOLERANCE',
                'FREQ_RPT_INPUTS',
                'EXOG_SIGNAL_WEAK_WEIGHT',
                'EXOG_BONUS_START_MINS',
                'EXOG_SIGNAL_STRONG_WEIGHT',
                'SEED_FIXHEAT_PERIOD_MINS',
                'SEED_FIXHEAT_TEMP',
                'WEIGHT_INVERT_TIME_MINS',
                'WEIGHT_INVERT_FACTOR' ,
                'WEIGHT_INVERT_ENABLE',
                'FISH_INPUT_NETWORK',
                'FISH_HIST_LEN',
                'FISH_OUTPUT_NETWORK',

                ]:

            defval = getattr(self, var)
            confval = self._ext_conf.get(var, None)
            if confval is not None:
                print "[DD] setting {} from file to {} (default={})".format(
                        var, confval, defval)

                setattr(self, var, confval)
            else:
                setattr(self, var, defval) # probably unecessary - verify

        self.verb = self.VERB
    #}}}

    #{{{ logging
    def setup_logger(self, append=False, delimiter=';'):
        mode = 'a' if append else 'w'
        self._log_LINE_END = os.linesep # platform-independent line endings
        self._log_delimiter = delimiter
        try:
            #self.log_fh = open(self.logfile, mode, 0) # 3rd value is buflen =wrote immediately.
            self.log_fh = open(self.logfile, mode)
        except IOError as e:
            print "[F] cannot open logfile ({})".format(e)
            raise

        pass
    def write_logline(self, ty=None, suffix=''):
        '''
        add a line to the logfile, forom various different types -
        - temperatures (measured, next setpoint, current setpoint)
        - IR sensors (measured plus super-threshold)
        - processed IR data (current value, avg etc)
        - contribution to heating state (avg data of self plus neighbours, sum)

        different loglines contain differet components but they all use
        ty;timestamp;<readings...;><nl>

        any reading can have a suffix appended/

        '''
        now = time.time()

        fields = []
        if ty == "IR":
            fields += ["ir_array", now]
            ir_levels = np.array(self._casu.get_ir_raw_value(casu.ARRAY))[0:6]
            #fields += ir_levels
            # syntax change?!
            fields.extend(ir_levels)

        elif ty == "HEAT":
            fields += ["temperatures", now]
            for sensor in [casu.TEMP_L, casu.TEMP_R, casu.TEMP_B, casu.TEMP_F,]:
                #casu.TEMP_WAX, casu.TEMP_CASU]:
                _t = self._casu.get_temp(sensor)
                fields.append(_t)

            _sp, onoff = self._casu.get_peltier_setpoint()
            fields.append(_sp)
            fields.append(int(onoff))
        elif ty == "MODE":
            # lets write this manualy for more flexibility
            fields += ['state', now, self.state, self._states[self.state]]

        elif ty == "HEAT_CALCS":
            # most of the info comes from the suffix.
            fields += ["heat_calcs", now]

        elif ty == "NH_DATA":
            fields += ["nh_data", now]

        # elif ...

        s = self._log_delimiter.join([str(f) for f in fields])
        if len(suffix):
            s += self._log_delimiter + suffix
        s += self._log_LINE_END
        self.log_fh.write(s)
        self.log_fh.flush()



    def _cleanup_log(self):
        self.log_fh.close()
        print "[I] finished logging to {}.".format(self.logfile)

    #}}}

    #{{{ stop
    def stop(self):
        self._casu.set_diagnostic_led_rgb(0.2, 0.2, 0.2)
        if not self.__stopped:
            s = "# {} Finished at: {}".format(
                self.name, datetime.datetime.fromtimestamp(time.time()))
            self.log_fh.write(s + "\n")
            self._cleanup_log()
            self._casu.stop()
            self.__stopped = True

    def _init_states(self):
        self._states = {
            1: 'STATE_FIXED_TEMP',
            2: 'STATE_INIT_NOHEAT',
            3: 'STATE_HEAT_PROPTO',
        }

    #}}}
    #{{{ read sensors
    def measure_ir_sensors(self):
        ir_levels = np.array(self._casu.get_ir_raw_value(casu.ARRAY))
        count = 0

        # need to ignore the last one because it should not be used
        for i, (val, t) in enumerate(zip(ir_levels, self.calib_data['IR'])):
            if i < 6: # ignore last one
                if (val > t): count += 1

        self.current_count = float(count / self.MAX_SENSORS)

    def get_actual_temp(self):
        return self._casu.get_temp(casu.TEMP_WAX)

    def get_est_ring_temp(self):
        _T = []
        for sensor in [casu.TEMP_L, casu.TEMP_R, casu.TEMP_B, casu.TEMP_F]:
            _t = self._casu.get_temp(sensor)
            if _t > 2.0 and _t < 50.0: # value is probably ok
                _T.append(_t)
        if len(_T):
            T = np.array(_T)
            return T.mean()
        else:
            return -1.0
    #}}}

    #{{{ basic temp control
    def set_fixed_temp(self, temp=None):
        '''
        set to a target temperature `temp`. If no argument provided, the value
        used is `self.INIT_FIXHEAT_TEMP`
        '''
        # if we have a fixed temperature, we assert it, or check it is already
        # asserted.
        # check temp is ok
        if temp is None:
            target_temp = self.INIT_FIXHEAT_TEMP
        else:
            target_temp = temp
        _tref, _on = self._casu.get_peltier_setpoint()
        if _tref == target_temp and _on is True:
            # nothing to do
            pass
        else:
            self._casu.set_temp(target_temp)
            self.current_Tref = target_temp
            self._active_peliter = True
            # update the info on it
            now = time.time()
            self.last_temp_update_time = now
            tstr = time.strftime("%H:%M:%S-%Z", time.gmtime())
            print "[I][{}] requested new fixed temp @{} from {:.2f} to {:.2f}".format(
                    self.name, tstr, self.prev_Tref, self.current_Tref)
            self.prev_Tref = self.current_Tref

    def unset_temp(self):
        self._casu.temp_standby()
        self._active_peliter = False

    #}}}

    #{{{ emit flash pulse to help align videos
    def sync_flash(self):
        if self.SYNCFLASH:
            now = time.time()
            if now - self.last_synchflash_time > self.SYNC_INTERVAL:
                # update time (sync to beginning of flash)
                self.last_synchflash_time = now
                # record pre
                s = "{}; {}; {};".format(now, self.sync_cnt, "start")
                self.synclog.write(s + "\n")
                self.synclog.flush()
                print "[D] synch {}".format(s)
                # FLASH
                self._sync_flash()
                # RECORD post
                now2 = time.time()
                self.synclog.write("{}; {}; {}; \n".format(now2, self.sync_cnt, "end"))
                self.sync_cnt += 1

    def _sync_flash(self, dur_mult=1.0, log=True):
        '''
        by default a 0.4s cycle of R/G/B (blocking).
        Increase duration by setting dur_mult >1
        '''
        # read current state
        rgb = self._casu.get_diagnostic_led_rgb()
        self._casu.set_diagnostic_led_rgb(r=1.0)
        time.sleep(0.05)
        self._casu.set_diagnostic_led_rgb()
        time.sleep(0.05)

        self._casu.set_diagnostic_led_rgb(g=1.0)
        time.sleep(0.10)
        self._casu.set_diagnostic_led_rgb()
        time.sleep(0.05)

        self._casu.set_diagnostic_led_rgb(b=1.0)
        time.sleep(0.15)
        self._casu.set_diagnostic_led_rgb()
        time.sleep(0.05)

        # put back original state
        self._casu.set_diagnostic_led_rgb(*rgb)
    #}}}

