#!/usr/bin/env python
# -*- coding: utf-8 -*-


import zmq

import threading
import time

class Relay:

    def __init__(self):
        ''' Create and connect sockets '''
        self.context = zmq.Context(1)

        self.sub_internet = self.context.socket(zmq.SUB)
        # Bind the address to listen to CATS
        self.sub_internet.bind('tcp://*:5556')
        self.sub_internet.setsockopt(zmq.SUBSCRIBE,'casu-')
        #self.sub_internet.setsockopt(zmq.SUBSCRIBE,'casu-007')
        print('Internet subscriber bound!')

        self.pub_internet = self.context.socket(zmq.PUB)
        # Bind the address to publish to CATS
        self.pub_internet.bind('tcp://*:5555')
        print('Internet publisher bound!')

        self.pub_local = self.context.socket(zmq.PUB)
        self.pub_local.bind('tcp://*:10105')
        print('Local publisher bound!')

        self.sub_local = self.context.socket(zmq.SUB)
        self.sub_local.connect('tcp://bbg-001:10103')
        self.sub_local.connect('tcp://bbg-001:10104')
        self.sub_local.setsockopt(zmq.SUBSCRIBE,'cats')
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
            [name, msg, sender, data] = self.sub_internet.recv_multipart()
            now = time.time()

            if (name == 'casu-001'):
                names = ['casu-022', ]
            if (name == 'casu-002'):
                names = ['casu-023', ]
            for name in names:
                m = 'Received from cats: ' + name + ';' + msg + ';' + sender + ';' + data
                print m
                self.pub_local.send_multipart([name,msg,sender,data])
                with open(self.logfile_name, "a") as lf:
                    lf.write("{}; {}\n".format(now, m))

    def recieve_from_local(self):
        while not self.stop:
            [name, msg, sender, data] = self.sub_local.recv_multipart()
            now = time.time()
            if (sender == 'casu-022'):
                sender = 'casu-001'
            if (sender == 'casu-023'):
                sender = 'casu-002'
            m = 'Received from arena: ' + name + ';' + msg + ';' + sender + ';' + data
            print m
            self.pub_internet.send_multipart([name,msg,sender,data])
            with open(self.logfile_name, "a") as lf:
                lf.write("{}; {}\n".format(now, m))

if __name__ == '__main__':

    relay = Relay()

    cmd = 'a'
    while cmd != 'q':
        cmd = raw_input('To stop the program press q<Enter>')

    relay.stop = True
