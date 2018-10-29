#!/usr/bin/env python
# -*- coding: utf-8 -*-

#{{{ imports
from assisipy import casu
import argparse
import time
import numpy as np
import pygraphviz as pgv
import libcas
import interactions

#{{{ definitions
ERR = '\033[41m'
BLU = '\033[34m'
ENDC = '\033[0m'


STATE_FIXED_TEMP  = 1
STATE_INIT_NOHEAT = 2
STATE_HEAT_PROPTO = 3
#}}}
#}}}

class Enhancer(libcas.BaseCASUCtrl):
    #{{{ initialiser
    def __init__(self, casu_name, logpath,
                 conf_file=None, calib_conf=None,
                 nbg_file=None,):

        # basic setup, including calibration, logpath, casu name,
        self._init_common(casu_name, logpath, conf_file=conf_file,
                          calib_conf=calib_conf)

        self.nbg_file = nbg_file
        self.weights_inverted = False
        self.ts = 0

        self._init_hist_vars()
        self._init_temp_vars()
        self._init_neighbourhood()
        # variables for state and timing
        self.state = STATE_INIT_NOHEAT
        self.old_state = 0 # set different to above so initial state is always logged
        self.init_upd_time = time.time()
        self.__stopped = False


    #}}}
    #{{{ init helpers
    def _init_hist_vars(self):
        '''
        variables (arrays/dicts of arrays) for historical records of casu inputs
        and states
        '''
        # data
        self.bee_hist = {} # record the bee counts from each relevant source
        self.bee_hist['self'] = np.zeros(self.HIST_LEN,)

        self.smoothed_bee_hist = {}  # keep track of time-averaged data
        self.smoothed_bee_hist['self'] = 0.0

        self.state_contribs = {}     # keep track of contributions to temp
        self.state_contribs['self'] = 0.0

    def _init_temp_vars(self):
        self._active_peliter   = False
        self.current_temp      = 28.0
        self.prev_temp         = 28.0
        self.inst_Ttgt         = 28.0
        self.current_Tref      = 28.0
        self.prev_Tref         = 28.0

        self.unclipped_activation = 0.0

        self.last_tref_change       = time.time()
        self.tref_changed = False
        self.last_temp_update_time  = time.time()

    def _init_neighbourhood(self):
        ''' top-level wrapper for all neighbourhoods required'''
        self._init_beecasu_neighbourhood() # for bee-casu interactions

    def _init_beecasu_neighbourhood(self):
        g_hier = pgv.AGraph(self.nbg_file)
        g_flat = interactions.flatten_AGraph(g_hier)

        self.in_map = interactions.get_inmap(g_flat, self.name)
        self.out_map = interactions.get_outmap(g_flat, self.name)

        self.most_recent_rx = {}
        for neigh in self.in_map:
            self.most_recent_rx[neigh] = { 'when' : self.ts, 'count': 0.0, 'tomem': False}

        for neigh in self.in_map :
            self.smoothed_bee_hist[neigh] = 0.0
            self.state_contribs[neigh] = 0.0
            self.bee_hist[neigh] = np.zeros(self.HIST_LEN,)

    #}}}


    #{{{ >> top-level cycle wrapper here <<
    def one_cycle(self):
        self.ts += 1
        self.update_info() # read own sensors and msgs from other casus
        self.emit_to_neighbours() # send own data to all neighbours

        self.update_outputs() # change actuators
        self.sync_flash() # periodically flash to synch vid and casu logs
    #}}}

    #{{{ update_info
    # reading inputs, basically. whether messages or sensors
    def update_info(self):
        #B. runtime
        #  1. read own local values of bees [whatever the source]
        self.measure_ir_sensors()
        #  2. receive updates from neighbours
        self.update_interactions()
        #  3. compute running averages (/re-compute)
        self.update_averages()
        self.compute_state_contribs()

        if self.DEV_VERB and ((self.ts % self.FREQ_RPT_INPUTS) == 0):
            print "[D]({}) {}. {:5.2f} ({:.0f} sensors) [{:.2f} avg]".format(
                    self.name, self.ts, self.current_count,
                    self.current_count * self.MAX_SENSORS,
                    self.smoothed_bee_hist['self'])
        # done - all up to date.
    #}}}
    #{{{ update_interactions
    def update_interactions(self):
        # read incoming messages
        neigh_cnts = self.recv_all_incoming()
        # update buffers for all neighbours
        for src, count in neigh_cnts.items():
            if src in self.most_recent_rx:
                self.most_recent_rx[src]['when']  = self.ts
                self.most_recent_rx[src]['count'] = float(count)
                self.most_recent_rx[src]['tomem'] = False
            else:
                print "[W] {} recv data from {}, unexpectedly".format(self.name, src)
    #}}}
    #{{{ update_averages
    def update_averages(self):
        self.update_bee_averages()

    def update_bee_averages(self):
        # if we have new data for a given neighbour (upstream), then push to buffer
        for neigh, data in self.most_recent_rx.items():
            if data['tomem'] is False and (self.ts - data['when']) < self.MAX_MSG_AGE:
                libcas.push_data_1d(self.bee_hist[neigh], data['count'] )
                data['tomem'] = True
            else:
                if data['tomem'] is False:
                    # we must be with out of date info. Emit a message
                    print "[W]{} old info (data from {}; now:{} => age={}, thr {} [already transferred? {}])".format(
                        self.name, data['when'], self.ts, self.ts - data['when'],
                        self.MAX_MSG_AGE, data['tomem'])

        # we always have an update for self, so put that in too.
        libcas.push_data_1d(self.bee_hist['self'], self.current_count)

        valid = min(self.ts, self.AVG_HIST_LEN)

        for neigh in self.bee_hist: # including 'self' here
            vd = np.array(self.bee_hist[neigh][0:valid])
            self.smoothed_bee_hist[neigh] = vd.mean()


    def compute_state_contribs(self):
        self.state_contribs = {}     # keep track of contributions to temp

        for neigh in self.smoothed_bee_hist: # including 'self' here
            if neigh == 'self':
                w = self.SELF_WEIGHT
            else:
                w = self.in_map[neigh].get('w')

            v = self.smoothed_bee_hist[neigh]
            self.state_contribs[neigh] = w * v

    #}}}
    #{{{ update_outputs
    def update_outputs(self):
        '''
        recompute the emission temp, update mode, change LEDs
        '''
        #  weighted sum over all input sensor data, and multiply by range
        clipped_activation_level = self.compute_activation_level()
        if 0: print "[I]{}|{} Computed activation summation as {:.2f}".format(
                self.name, self.ts, clipped_activation_level)
        activation_level = clipped_activation_level

        bonus = self.T_RANGE * activation_level

        # compute and record the internal target, internal Tref
        dT_mag, dT_sgn = self.clipped_dT(bonus)

        self.inst_Tref = self.inst_Tactual + dT_mag*dT_sgn
        self.dT_mag = dT_mag
        self.dT_sgn = dT_sgn

        # check whether it is ok to update yet or not
        Tref_update_allowed = self.check_tref_change_ok()

        if self.DEV_VERB and ((self.ts % self.FREQ_RPT_INPUTS) == 0):
            print "\t===={:4}====  {:.1f}% ({:.1f}oC) Tref: {:.1f}({:.0f}s) ==> {:.1f}|{:.1f}oC [{}]".format(
                self.ts, activation_level * 100.0, bonus, self.current_Tref,
                time.time() - self.last_tref_change, self._casu.get_temp(casu.TEMP_L),
                self._casu.get_temp(casu.TEMP_R), self.name)

        # if initial quiescent period has passed, allow LEDs and heaters on.
        self.update_state_and_temps(Tref_update_allowed, led_frac=activation_level)

        # write out logs for sensor values, and heat calcs
        _fields = [activation_level, bonus, ]
        self.write_logline(ty="HEAT_CALCS", suffix=self._log_delimiter.join([str(f) for f in _fields]) )
        self.write_logline(ty='IR')
        self.write_logline(ty='HEAT')
    #}}}

    #{{{ check_tref_change_ok
    def check_tref_change_ok(self, ):
        '''
        the internal target should be validated to ensure a change in Tref is
        warranted in this timestep.
        '''
        # then IF the conditions are met (3x/4x), allow updating of the Tref
        Tref_update_allowed = True
        _d_update_checks = { "Tref_reached" : True, "Tref_interval" : True,}

        # 1. did we (more or less) reach the Tref?
        dTref = self.current_Tref - self.inst_Tactual
        if abs(dTref) > self.TREF_REACH_TOLERANCE:
            if self._active_peliter:
                Tref_update_allowed = False
                _d_update_checks["Tref_reached"] = False
        # 2. was the last change long enough ago?
        now = time.time()
        elap_Tref = now - self.last_tref_change
        if elap_Tref < self.REF_UPDATE_INTERVAL:
            Tref_update_allowed = False
            _d_update_checks["Tref_interval"] = False


        # special override - if no temp has been set ever, allow
        if not self.tref_changed:
            Tref_update_allowed = True
            #print "[Id]{} first round override {:.2f} ({:.2f})".format(
            #    self.name_num, now-self.last_tref_change, self.last_tref_change)

        if Tref_update_allowed:
            # change what Tref says
            self.current_Tref = float(self.inst_Tref)
            self.last_tref_change = now

        # emit some new debug info.
        if self.DEV_VERB and ((self.ts % self.FREQ_RPT_INPUTS) == 0):
            print "[DD9]{} Ttgt {:.1f}C Tact: {:.1f}C, {}*{:.1f}. dTref {:.1f} ({:.1f}-{:.1f})".format(
                self.name, self.inst_Ttgt, self.inst_Tactual, self.dT_sgn,
                self.dT_mag, dTref, self.inst_Tactual, self.current_Tref,)

        return Tref_update_allowed
        #}}}
    #{{{ update_state_and_temps -- actually set the temperatures
    def update_state_and_temps(self, Tref_update_allowed, led_frac=None): #noqa
        '''
        change mode/state if time dictates this; if in a heat-setting mode then
        update the current target, if allowed.
        '''
        # record to logfile on cycles when it transitions
        now = time.time()
        elap = now - self.init_upd_time

        # also switch off LED if it is after 30 sec (or whatever config is).
        if self.INIT_LED is True:
            if elap > self.SHOW_CALIB_LED_MINS * 60.0:
                self._casu.set_diagnostic_led_rgb(r=0, g=0, b=0)
                self.INIT_LED = False

        # ===== IF IN FIXED TEMP, -> 1/2 blue ===== #
        if elap < (self.INIT_FIXHEAT_PERIOD_MINS * 60.0):
            # set the CASU to a fixed temperature.
            self.state = STATE_FIXED_TEMP

            if self.ENABLE_TEMP:
                self.set_fixed_temp()
            if self.DEV_VERB:
                print "[DD3] temp fixed heat -> {:.1f}, equalise arena. ({:.1f}s remain)".format(
                    self.INIT_FIXHEAT_TEMP, (self.INIT_FIXHEAT_PERIOD_MINS * 60.0) - elap)

        # ===== IF IN MAIN MODE, SET RED PROPTO TEMP ===== #
        elif elap > (self.INIT_NOHEAT_PERIOD_MINS * 60.0):
            self.state = STATE_HEAT_PROPTO
            #6. compute color to match the emission temp
            #   (just propto range of temp)
            if led_frac is not None:
                self._casu.set_diagnostic_led_rgb(r=led_frac, g=0, b=0)
            #7. set temp, set LEDs
            if self.ENABLE_TEMP:
                    # 2017 heat ctrl: => tests are above, within variable ""
                    if Tref_update_allowed:
                        if 0: print "[DD4] {}-{}: Tref update to {:.2f}.".format(
                            self.name, self.ts, self.current_Tref)
                        self.simple_update_temp_wrapper()

        # ===== if in DEBUG NO HEAT MODE, SET TO DK GREY. ===== #
        else:
            self.state = STATE_INIT_NOHEAT
            self._casu.set_diagnostic_led_rgb(r=0.2, g=0.2, b=0.2)
            if self.DEV_VERB:
                print "[DD2] temp no heat, free bee movement. ({:.1f}s remain)".format(
                         (self.INIT_NOHEAT_PERIOD_MINS * 60.0) - elap)

        #8. mode log entry for this timestep, if state changed
        if self.state != self.old_state:
            self.write_logline(ty="MODE")
        self.old_state = self.state
        #}}}
    #{{{ simple_update_temp_wrapper
    def simple_update_temp_wrapper(self):
        '''
        this wrapper assumes update was already "authorised"
        '''
        now = time.time()
        # 1. get current Tref
        # 2. compare with new tref
        tref_casu, state = self._casu.get_peltier_setpoint()
        # if not >0.05 apart, don't set.
        if state is False or abs(tref_casu - self.current_Tref) > 0.05:
            # allow
            self._casu.set_temp(self.current_Tref)
            self.tref_changed = True

        self._active_peliter = True
        self.last_temp_update_time = now # timer for the  wrapper
        tstr = time.strftime("%H:%M:%S-%Z", time.gmtime())
        if abs(self.prev_Tref - self.current_Tref) > (0.95*self.TREF_REACH_TOLERANCE):
            print "[I]{}|{} utw2 requested new temp @{} from {:.2f} to {:.2f}".format(
                    self.name, self.ts, tstr, self.prev_Tref, self.current_Tref)
        self.prev_Tref = self.current_Tref
    #}}}
    #{{{ compute_activation_level
    def compute_activation_level(self):
        activation_level = 0.0
        _nh_fields = [ len(self.smoothed_bee_hist.keys()), ]
        for neigh in self.smoothed_bee_hist.keys():
            if neigh == 'self':
                w = self.SELF_WEIGHT
            else:
                w = self.in_map[neigh].get('w')

            activation_level += self.state_contribs[neigh]
            #if self.DEV_VERB and ((self.ts % self.FREQ_RPT_INPUTS) == 0):
            #    print "\t{:14}: {:.2f} {:+.2f} | w={:+.2f}".format(
            #        neigh, self.smoothed_bee_hist[neigh],
            #        self.state_contribs[neigh], w)
            # each casu has different length data due to variable #edges
            #>>>ty, time, num_neigh, <who, weight, raw, contrib, > for each edge. <<<
            _nh_fields += [neigh, w, self.smoothed_bee_hist[neigh],
                    self.state_contribs[neigh]]

        self.write_logline(ty="NH_DATA", suffix=
                self._log_delimiter.join([str(f) for f in _nh_fields]))

        self.unclipped_activation = float(activation_level)
        # clip in [0, 1]
        activation_level = sorted([0.0, self.unclipped_activation, 1.0])[1]

        return activation_level
    #}}}
    #{{{ comms
    #{{{ recv_all_incoming
    def recv_all_incoming(self, retry_cnt=0):
        msgs = {}
        try_cnt = 0
        while True:
            msg = self._casu.read_message()

            if msg:
                txt = msg['data'].strip()
                src = msg['sender']
                nb =  float(txt.split()[0])
                msgs[src] = nb

                if self.verb > 1:
                    print "\t[i]<== {3} recv msg ({2} by): '{1}' bees, {4} from {0} {5}".format(
                        msg['sender'], nb, len(msg['data']), self.name, BLU, ENDC)
            else:
                # buffer emptied, return
                try_cnt += 1
                if try_cnt > retry_cnt:
                    break

        return msgs
    #}}}
    #{{{ emit_to_neighbours
    def emit_to_neighbours(self):
        self.emit_to_bee_nh()

    def emit_to_bee_nh(self):
        #  4. transmit values to each neighbour
        # should we emit a suppressed signal or a true one?
        sup_now = False
        if self.ENABLE_SUPPRESS_LOW:
            if self.unclipped_activation < (1.0/12.0):
                sup_now = True

        for phys_dest, linkname in self.out_map.iteritems():
            if 'cats' not in linkname:
                # link name is the destination for msg transmission
                self.tx_count(linkname, suppression=sup_now)
    #}}}
    #{{{ tx_count
    def tx_count(self, dest, suppression=False):
        x_tx =  float(self.smoothed_bee_hist['self']) # default - send signal
        if suppression: x_tx = 0.0 # if this node is currently suppr, send zero.
        s = "{:.3f}".format(x_tx)
        if self.verb > 2 or (suppression is True and self.verb > 1):
            print "\t[i]==> {} send msg ({} by): '{}' bees, to {} (s {:.2f}| i{:.2f} |tx {:.2f})".format(
                self.name, len(s), s, dest,
                self.smoothed_bee_hist['self'], self.unclipped_activation, x_tx)

        self._casu.send_message(dest, s)
    #}}}
    #}}}


if __name__ == '__main__':
    # args
    parser = argparse.ArgumentParser()
    parser.add_argument('name', )
    parser.add_argument('-c', '--conf', type=str, default=None)
    parser.add_argument('-o', '--output', type=str, default=None)
    parser.add_argument('--nbg', type=str, default=None)
    args = parser.parse_args()

    # instantiate object with config file
    c = Enhancer(args.name, logpath=args.output, conf_file=args.conf,
                 nbg_file=args.nbg)
    if c.verb > 0: print "nuevo bifurcation enhancer - connected to {}".format(c.name)

    # execute main loop that handles the hang-up interrupt ok
    try:
        while True:
            time.sleep(c.MAIN_LOOP_INTERVAL)
            c.one_cycle()
    except KeyboardInterrupt:
        print "shutting down casu {}".format(c.name)
        c.stop()

    c.stop()
    if c.verb > 0: print "nuevo bifurcation enhancer {} - done".format(c.name)

