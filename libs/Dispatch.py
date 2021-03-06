# -*- coding: utf-8 -*-
'''
Created on June 30, 2012

@author: moloch

    Copyright [2012] [Redacted Labs]

    Licensed under the Apache License, Version 2.0 (the "License");
    you may not use this file except in compliance with the License.
    You may obtain a copy of the License at

        http://www.apache.org/licenses/LICENSE-2.0

    Unless required by applicable law or agreed to in writing, software
    distributed under the License is distributed on an "AS IS" BASIS,
    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
    See the License for the specific language governing permissions and
    limitations under the License.
'''


import os
import thread
import logging
import ConfigParser

from models import dbsession
from models import Job, User
from threading import Lock
from datetime import datetime
from libs.Singleton import Singleton
from libs.ConfigManager import ConfigManager


@Singleton
class Dispatch(object):
    ''' Dispatcher class, handles queue and RPC calls '''

    def __init__(self):
        self.__config__()
        self.is_busy = False
        self.mutex = Lock()

    def __config__(self):
        self.config = ConfigManager.Instance()

    def check_queue(self):
        ''' Starts a job or leaves it in the queue (thread safe) '''
        self.mutex.acquire()
        queue = list(Job.queue())  # Create a copy of the queue
        for job in queue:
            if len(job) == 0:
                job.status = u"COMPLETED"
                dbsession.add(job)
                dbsession.flush()
            else:
                weapon_systems = WeaponSystem.ready_system(
                    job.hashes[0].algorithm)
                if weapon_systems != None and 0 < len(weapon_systems):
                    thread.start_new_thread(
                        self.__crack__, (job, weapon_systems[0],))
        self.mutex.release()

    def __crack__(self, job, weapon_system):
        '''
        Does the actual password cracking, before calling this function you should
        ensure the weapon system is online and not busy
        '''
        user = User.by_id(job.user_id)
        if user == None or job == None:
            logging.error("Invalid job passed to dispatcher.")
        else:
            job.status = u"IN_PROGRESS"
            dbsession.add(job)
            dbsession.flush()
            algo = job.hashes[0].algorithm
            job.started = datetime.now()
            try:
                ssh_keyfile = NamedTemporaryFile()
                ssh_keyfile.write(weapon_system.ssh_key)
                ssh_keyfile.seek(0)
                ssh_context = SshContext(weapon_system.ip_address,
                                         user=weapon_system.ssh_user, keyfile=ssh_keyfile.name)
                rpc_connection = rpyc.ssh_connect(
                    ssh_context, self.service_port)
                hashes = job.to_list()
                results = rpc_connection.root.exposed_crack_list(
                    job.id, job.to_list(), algo, weapon_system.cpu_count)
            except:
                logging.exception("Connection to remote weapon system failed, check parameters")
            finally:
                ssh_keyfile.close()
            if results != None:
                job.save_results(results)
            job.completed = True
            job.finished = datetime.now()
            dbsession.add(job)
            dbsession.flush()
            self.__next__()

    def __next__(self):
        ''' Called when a weapon system completes a job '''
        if 0 < Job.qsize():
            self.check_queue()
