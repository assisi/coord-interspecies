#!/usr/bin/env python
# -*- coding: utf-8 -*-


import zmq
import threading
import time

#ADDR_PUB_INET = "tcp://172.27.34.3:4255"  # cats-workstation (fishtrack) # cats-workstation (fishtrack)
# cats-workstation (fishtrack) MUST CONNECT/SUB to this address
ADDR_PUB_INET = "tcp://10.42.1.94:5555"    # this is the emission port of relay
# this should be <graz>:5555
ADDR_SUB_INET = "tcp://51.254.39.242:5556" # streamyfish.com (via ssh)


ADDR_PUB_LOCAL = 'tcp://127.0.0.1:10105' # should match port of msg_addr in fish-tank=>cats
#ADDR_SUB_INET = 'tcp://127.0.0.1:5557' # material that is PUBLISHED by cats arrives here
#ADDR_PUB_INET = 'tcp://127.0.0.1:5558' # data to be SENT TO CATS goes out this way

DO_PUB_LOCAL = True


class Relay(object):

    def __init__(self):
        ''' Create and connect sockets '''
        self.context = zmq.Context(1)

        self.sub_internet = self.context.socket(zmq.SUB)
        # Bind the address to listen to CATS
        #self.sub_internet.bind('tcp://*:5556')
        #NOT SEEMINGLY NECESSARY to bind.
        # we CONNECT to cats to listen
        self.sub_internet.connect(ADDR_SUB_INET)
        self.sub_internet.setsockopt(zmq.RCVTIMEO, 1000)
        self.sub_internet.setsockopt(zmq.SUBSCRIBE,'casu-')
        print('Internet subscriber connected! listen on {}'.format(ADDR_SUB_INET))


        self.pub_internet = self.context.socket(zmq.PUB)
        # Bind the address to publish to CATS
        self.pub_internet.bind(ADDR_PUB_INET)
        #self.pub_internet.connect(ADDR_PUB_INET)
        #self.pub_internet.setsockopt(zmq.RCVTIMEO, 1000)
        print('Internet publisher bound! port {}'.format(ADDR_PUB_INET))

        if DO_PUB_LOCAL:
            self.pub_local = self.context.socket(zmq.PUB)
            self.pub_local.bind(ADDR_PUB_LOCAL)
            print('Local publisher bound, port {}!'.format(ADDR_PUB_LOCAL))

        self.sub_local = self.context.socket(zmq.SUB)
        self.sub_local.connect('tcp://bbg-001:10103')
        self.sub_local.connect('tcp://bbg-001:10104')
        self.sub_local.setsockopt(zmq.SUBSCRIBE,'cats')
        self.sub_local.setsockopt(zmq.RCVTIMEO, 1000)
        print('Local subscribers bound!')

        self.incoming_thread = threading.Thread(target = self.recieve_from_internet)
        self.outgoing_thread = threading.Thread(target = self.recieve_from_local)

        self.stop = False
        self.logfile_name = "relay_msgs.log"
        self.start_time = time.time()
        with open(self.logfile_name, "w") as lf:
            lf.write("# Started at {}".format(time.time()))




        self.incoming_thread.start()
        self.outgoing_thread.start()

    def recieve_from_internet(self):
        while not self.stop:
            try:
                [name, msg, sender, data] = self.sub_internet.recv_multipart()
            except zmq.ZMQError as e:
                if e.errno == zmq.EAGAIN:
                    continue

            now = time.time()

            if (name == 'casu-001'):  names = ['casu-031', ]
            if (name == 'casu-002'):  names = ['casu-032', ]
            for name in names:
                m = 'Received from cats: ' + name + ';' + msg + ';' + sender + ';' + data
                print m
                if DO_PUB_LOCAL:
                    self.pub_local.send_multipart([name,msg,sender,data])
                with open(self.logfile_name, "a") as lf:
                    lf.write("{}; {}\n".format(now, m))

    def recieve_from_local(self):
        while not self.stop:
            try:
                [name, msg, sender, data] = self.sub_local.recv_multipart()
            except zmq.ZMQError as e:
                if e.errno == zmq.EAGAIN:
                    continue
            now = time.time()
            if (sender == 'casu-031'):
                sender = 'casu-001'
            if (sender == 'casu-032'):
                sender = 'casu-002'
            m = 'Received from arena: ' + name + ';' + msg + ';' + sender + ';' + data
            print m
            self.pub_internet.send_multipart([name,msg,sender,data])
            with open(self.logfile_name, "a") as lf:
                lf.write("{}; {}\n".format(now, m))

if __name__ == '__main__':

    relay = Relay()

    try:
        while True:
            time.sleep(0.25)
    except KeyboardInterrupt:
        print "donw. bye"

    #cmd = 'a'
    #while cmd != 'q':
    #    cmd = raw_input('To stop the program press q<Enter>')

    relay.stop = True
    print "trying to close join"
    relay.incoming_thread.join()
    print "trying to join #2"
    relay.outgoing_thread.join()
    print "closed trehads/"

