#!/usr/bin/env python
# -*- coding: utf-8 -*-

#{{{ imports
import argparse
import time
import numpy as np
#from assisipy import casu ## lib is used directly only in mini_enh

import libcas
from mini_enh import Enhancer

#{{{ definitions for color output and states
ERR = '\033[41m'
BLU = '\033[34m'
ENDC = '\033[0m'


STATE_FIXED_TEMP  = 1
STATE_INIT_NOHEAT = 2
STATE_HEAT_PROPTO = 3
#}}}

#}}}


#{{{ EnhancerDualInput
class EnhancerDualInput(Enhancer):
    '''
    This class takes inputs from
    - other bee-casus; assumed to be already time-averaged, and in [0,1)
    - fish casus/fish population states; assumed to be instantaneous data
      and binary directions.

    - to decide on the target temperature, there are two modes
      a) relative: we increase or decrease current temperature according
         to whether the balance of inputs is +ve or -ve
      b) absolute: we set the (internal) target to some value in [28, 36]
         according to the overall weighted sum.

    - data is emitted to other bee-casus that are in the neighbourhood,
      and also to the fish side (see two methods emit_to_bee_nh() and
      emit_to_fish_nh()).  Note that the data shared among the bee-casu network
      is all prefixed so to distinguish the type of input.

    '''
    # inherit everything from bee-only 'enhancer' class
    MSG_PREFIX_BEECASU = "bee-casu-avg|"

    # methods that need to be updated are
    # 1. receiving and filtering messages
    #    - we can only obtain the sender ID and the payload
    #    - the other fields are not used (target, and "device"/message type)
    #
    # 2. latching and weighting data
    #    - we need circular buffers for every expected incoming CATS message
    #    - we need to (re-)use the time-averaging method (new param?)
    #    - we need a weighting system for fish inputs as well.
    #
    # 3. initialising buffers
    #    - to latch data for each incoming, need to know the labels
    #    - to weight the data, we also need to have a map of label:weight
    #    - so do we also need an extra config file? Or just put in the
    #      existing casu conf file for now.
    #      Latter is ok to get started; we should anticipate the need to
    #      process these files to verify that the combined network is
    #      what we intend.

    #{{{ initialisation
    # the init needed is the same as a bee-only system, except that
    # we also need to:
    # - read the fish -> bee network
    # - initialise memory for each incoming channel (raw plus smooth)
    #
    # accordingly, re-implement: _init_hist_vars, _init_neighbourhood
    # both are called by __init__

    #{{{ memory initialiser -- reimplemented
    def _init_hist_vars(self):
        '''
        variables (arrays/dicts of arrays) for historical records
        - of bee casu inputs, and states
        - of fish casu inputs and anything else from CATS
        '''
        # bee data
        self.bee_hist = {} # record the bee counts from each relevant source
        self.bee_hist['self'] = np.zeros(self.HIST_LEN,)

        self.smoothed_bee_hist = {}  # keep track of time-averaged data
        self.smoothed_bee_hist['self'] = 0.0

        self.state_contribs = {}     # keep track of contributions to temp
        self.state_contribs['self'] = 0.0
        self.contrib_parts = {}
        self.contrib_parts['self'] = (self.SELF_WEIGHT, 0.0)

        # fish-side data
        self.fish_hist = {} # record the fish directions
        self.smoothed_fish_hist = {}  # keep track of time-averaged data
        self.state_contribs_from_fish = {} # different comp in fsh/bee data
    #}}}
    #{{{ neighbourhood setup -- bee inherited, fish added here.
    def _init_neighbourhood(self):
        self._init_beecasu_neighbourhood() # as per the bee-only sys
        self._init_fishcasu_neighbourhood() # custom for this variant

    def _init_fishcasu_neighbourhood(self):
        # at present, easiest way to get this into code, in a semi
        # dynamic way is via the casu .conf file.
        # note that the nbg file includes the link only from the whole
        # CATS system, and so can't be considered useful for each possible
        # data source that arrives on this pathway.
        self.fish_inmap  = dict(self.FISH_INPUT_NETWORK)
        self.fish_outmap = dict(self.FISH_OUTPUT_NETWORK)

        self.fish_most_recent_rx = {}

        for neigh in self.fish_inmap:
            self.fish_most_recent_rx[neigh] = {
                    'when'  : self.ts,
                    'count' : 0.0,
                    'tomem' : False,
                    'drn'   : 'Undef', # CW/CCW/ Undef
                    }
            self.fish_hist[neigh] = np.zeros(self.FISH_HIST_LEN,)
            self.smoothed_fish_hist[neigh] = 0.0
            self.state_contribs_from_fish[neigh] = 0.0

    #}}}

    #}}}

    #{{{ communication
    # if all casus in this network use a prefix in the payload, we can
    # remain agnostic as to the form of CASU name, and still determine
    # whether data is fish-type or bee-type.
    #{{{ update_interactions
    def update_interactions(self):
        # read incoming messages
        bee_cnts, fish_cnts = self.recv_all_incoming()

        # update buffers for all neighbours in BEE-CASU network
        for src, count in bee_cnts.items():
            if src in self.most_recent_rx:
                self.most_recent_rx[src]['when']  = self.ts
                self.most_recent_rx[src]['count'] = float(count)
                self.most_recent_rx[src]['tomem'] = False
                #print "[D4buf] {} buffered msg count from {} (val={:.2f})".format(self.name, src, count)
            else:
                print "[W] {} recv data from {}, unexpectedly".format(self.name, src)
        # update buffers for all neighbours in FISH-SIDE network
        conv_map = {'CW': 1.0, 'CCW': -1.0} # for display - should be elseshere!

        for src, drn in fish_cnts.items():
            _hv = self.smoothed_fish_hist.get(src, -51) # grab the smoothed value from memory
            print "[DFmsg]{} fish msg rx from {}. payload: {} ({}; avg={:.3f})".format(
                self.name, src, drn, conv_map.get(drn, -99), _hv)
            if src in self.fish_most_recent_rx:
                count = conv_map.get(drn, 0.0)
                #if   drn == "CW" : count = conv_map.get( #count = 1.0
                #elif drn == "CCW": #count = 0.0
                #else:
                if drn not in conv_map.keys():
                    print "[DFmsg] {} received badly defined fish data? {}".format(self.name, drn)
                    continue  # skip to next message.

                self.fish_most_recent_rx[src]['when'] = self.ts
                self.fish_most_recent_rx[src]['count'] = count
                self.fish_most_recent_rx[src]['tomem'] = False
            else:
                print "[Wf] {} recv fish side data from {}, unexpectedly".format(self.name, src)

    #}}}
    #{{{ handle  moving averages
    def update_averages(self):
        self.update_bee_averages()
        self.update_fish_averages()

    def update_fish_averages(self):
        # put newest data into buffers
        for neigh, data in self.fish_most_recent_rx.items():
            if data['tomem'] is False and (self.ts - data['when']) < self.MAX_MSG_AGE:
                libcas.push_data_1d(self.fish_hist[neigh], data['count'])
                data['tomem'] = True
            else:
                if data['tomem'] is False:
                    # we must be with out of date info. Emit a message
                    print "[W]{} old info (data from {}; now:{} => age={}, thr {} [already transferred? {}])".format(
                        self.name, data['when'], self.ts, self.ts - data['when'],
                        self.MAX_MSG_AGE, data['tomem'])

        # now compute average over last samples.
        valid = min(self.ts, self.FISH_HIST_LEN)

        for neigh in self.fish_hist:
            vd = np.array(self.fish_hist[neigh][0:valid])
            self.smoothed_fish_hist[neigh] = vd.mean()


    def update_bee_averages(self):
        # buffer neighbour data
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

        self.state_contribs = {}     # keep track of contributions to temp

        for neigh in self.smoothed_bee_hist: # including 'self' here
            if neigh == 'self':
                w = self.SELF_WEIGHT
            else:
                w = self.in_map[neigh].get('w')

            v = self.smoothed_bee_hist[neigh]
            self.state_contribs[neigh] = w * v


        valid = min(self.ts, self.AVG_HIST_LEN)

        for neigh in self.bee_hist: # including 'self' here
            vd = np.array(self.bee_hist[neigh][0:valid])
            self.smoothed_bee_hist[neigh] = vd.mean()
    #}}}

    #{{{ tx_count
    def tx_count(self, dest, suppression=False):
        x_tx =  float(self.smoothed_bee_hist['self']) # default - send signal
        if suppression: x_tx = 0.0 # if this node is currently suppr, send zero.
        s = "{} {:.3f}".format(self.MSG_PREFIX_BEECASU, x_tx)
        if self.verb > 2 or (suppression is True and self.verb > 1):
            print "\t[i]==> {} send msg ({} by): '{}' bees, to {} (s {:.2f}| i{:.2f} |tx {:.2f})".format(
                self.name, len(s), s, dest, self.smoothed_bee_hist['self'],
                self.unclipped_activation, x_tx)

        self._casu.send_message(dest, s)
    #}}}
    #{{{ emit_to_neighbours
    def emit_to_neighbours(self):
        self.emit_to_bee_nh()
        self.emit_to_fish_nh()

    def emit_to_fish_nh(self):
        '''
        for every target node in the fish network, send the time-averaged own signal.
        (note: this is NOT necessarily indicative of the overall winner, since
        the signal could be surpressed by multiple inhibition inputs for instance)

        '''
        #self._casu.send_message('cats', str(self.smoothed_bee_hist['self']))
        for neigh, enable  in self.fish_outmap.items():
            if enable:
                #print "[D4ftx] sending {} to {}.".format(self.name, str(self.smoothed_bee_hist['self']), neigh)
                self._casu.send_message(neigh, str(self.smoothed_bee_hist['self']))

    #}}}

    #{{{ recv_all_incoming
    def recv_all_incoming(self, retry_cnt=0):
        '''
        this returns two maps, one fish and one bee.
        '''
        bee_msgs = {}
        fish_msgs = {}
        try_cnt = 0
        while True:
            msg = self._casu.read_message()

            if msg:
                txt = msg['data'].strip()
                src = msg['sender']
                # work out the type, and add to relevant map.
                if txt.startswith(self.MSG_PREFIX_BEECASU):
                    txt = txt.lstrip(self.MSG_PREFIX_BEECASU) # remove pre
                    # should just have a number now; discard anything trailing
                    nb = float(txt.split()[0])
                    bee_msgs[src] = nb

                    if self.verb > 1:
                        print "\t[i]<== {3} recv msg ({2} by): '{1}' bees, {4} from {0} {5}".format(
                            msg['sender'], nb, len(msg['data']), self.name, BLU, ENDC)
                else:
                    # all other messages fish related
                    #print('[Dmsg] Rx-fish: {} from {}'.format(msg['data'], msg['sender']) )
                    data = msg['data'].split(',')
                    for item in data:
                        (fish,direction) = item.split(':')
                        fish_msgs[fish] = direction.strip()

            else:
                # buffer emptied, return
                try_cnt += 1
                if try_cnt > retry_cnt:
                    break

        return bee_msgs, fish_msgs
    #}}}

    #}}}

    #{{{ compute_state_contribs
    def compute_state_contribs(self):
        self.state_contribs = {}     # keep track of contributions to temp
        self.contrib_parts = {} # for logging it turns out I want v, w too
        # bee side
        for neigh in self.smoothed_bee_hist: # including 'self' here
            if neigh == 'self':
                w = self.SELF_WEIGHT
                v = self.smoothed_bee_hist[neigh]
            else: # incoming data is already smoothed
                w = self.in_map[neigh].get('w')
                v = self.bee_hist[neigh][0] # newest at front.

            self.state_contribs[neigh] = w * v
            self.contrib_parts[neigh] = (w,v)

        # --- fish side ---
        # there is no "self" here - but the weights are contained in the
        # conf file.
        for neigh in self.smoothed_fish_hist:
            v = self.smoothed_fish_hist[neigh]
            w = self.fish_inmap.get(neigh, 0.0) # TODO: warn if not presnt?
            self.state_contribs[neigh] = w * v
            self.contrib_parts[neigh] = (w,v)

        #TODO: should check whether any keys are common to the 2 dicts
        #    : since this would mask one set of signals


    #}}}
    #{{{ compute_activation_level
    def compute_activation_level(self):
        activation_level = 0.0
        if self.EXOG_BIAS != 0:
            activation_level += self.EXOG_BIAS
        _nh_fields = [ len(self.state_contribs), ]
        for neigh, contrib in self.state_contribs.items():
            activation_level += contrib
            w, v = self.contrib_parts[neigh] # short handles
            if self.DEV_VERB and ((self.ts % self.FREQ_RPT_INPUTS) == 0):
                print "\t{:14}: {:+.2f} {:+.2f} | w={:+.2f}".format(
                        neigh, v, contrib, w)
            # log line. data length varies due to #edges
            #>>>ty, time, num_neigh,
            #  <who, weight, raw, contrib, > for each edge. <<<
            _nh_fields += [neigh,  w, v, contrib]

        self.write_logline(ty="NH_DATA", suffix=
                self._log_delimiter.join([str(f) for f in _nh_fields]))

        self.unclipped_activation = float(activation_level)
        # clip in [0, 1]
        activation_level = sorted([0.0, self.unclipped_activation, 1.0])[1]

        if self.DEV_VERB and ((self.ts % self.FREQ_RPT_INPUTS) == 0):
            print "\t" + "="*40
            print BLU + "\t{} summation={:.3f} (clipped={:.2f})".format(
                self.name, self.unclipped_activation, activation_level) + ENDC
            print "\t" + "="*40

        return activation_level
    #}}}

#}}}

if __name__ == '__main__':
    #{{{ args
    parser = argparse.ArgumentParser()
    parser.add_argument('name', )
    parser.add_argument('-c', '--conf', type=str, default=None)
    parser.add_argument('-o', '--output', type=str, default=None)
    parser.add_argument('--nbg', type=str, default=None)
    args = parser.parse_args()
    #}}}

    # instantiate object with config file
    c = EnhancerDualInput( args.name, logpath=args.output,
            conf_file=args.conf, nbg_file=args.nbg)

    if c.verb > 0: print "bee bifurcation enhancer - bee and fish inputs. Connected to {}".format(c.name)
    # execute main loop that handles the hang-up interrupt ok
    try:
        while True:
            time.sleep(c.MAIN_LOOP_INTERVAL)
            c.one_cycle()
    except KeyboardInterrupt:
        print "shutting down casu {}".format(c.name)
        c.stop()

    c.stop()
    if c.verb > 0: print "nuevo2-in bifurcation enhancer {} - done".format(c.name)




