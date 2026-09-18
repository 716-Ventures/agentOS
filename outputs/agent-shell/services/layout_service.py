#!/usr/bin/python3
"""Shared activity surfaces, revisioned operations, durable undo and event history."""
import json
import os
from pathlib import Path
import pwd
import socket
import sqlite3
import struct
import time
from common import listen, read_line, send, connect
from layout_state import canonical, surface, leaves, apply

SOCKET='/run/agent-os-layout/api.sock'
DATABASE='/var/lib/agent-os-layout/state.sqlite3'


class LayoutStore:
    def __init__(self,path):
        self.db=sqlite3.connect(path)
        self.db.executescript('''PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS layouts(activity INTEGER PRIMARY KEY,revision INTEGER NOT NULL,body TEXT NOT NULL,undo TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,activity INTEGER,revision INTEGER,at REAL,actor TEXT,uid INTEGER,action TEXT);''')
        self.leases={}

    def busy(self,activity):
        return any(a==activity and expiry>time.monotonic() for (a,uid,token),expiry in self.leases.items())

    def snapshot(self,activity):
        row=self.db.execute('SELECT revision,body,undo FROM layouts WHERE activity=?',(activity,)).fetchone()
        if row is None:raise ValueError('Layout not initialized')
        state=json.loads(row[1])
        return {**state,'activity':activity,'revision':row[0],'can_undo':bool(json.loads(row[2])),
                'input_busy':self.busy(activity),'surfaces':[dict(p,kind='terminal_view') for p in leaves(state['tree'])]}

    def handle(self,req,uid,actor):
        if not isinstance(req,dict):raise ValueError('Expected a request object')
        activity=req.get('activity')
        if type(activity) is not int or not 1<=activity<=2147483647:raise ValueError('Invalid activity')
        op=req.get('op')
        if op=='ensure':
            if self.db.execute('SELECT 1 FROM layouts WHERE activity=?',(activity,)).fetchone() is None:
                if actor=='agent' and req.get('seed') is not None:raise ValueError('Only a terminal client can import a legacy layout')
                default=surface();state=canonical(req.get('seed') or {'tree':default,'focus':default['id'],'zoom':None})
                with self.db:
                    self.db.execute('INSERT INTO layouts VALUES(?,0,?,?)',(activity,json.dumps(state),'[]'))
                    self.db.execute('INSERT INTO events(activity,revision,at,actor,uid,action) VALUES(?,0,?,?,?,?)',
                        (activity,time.time(),actor,uid,json.dumps({'operation':'import' if req.get('seed') else 'create'})))
            return self.snapshot(activity)
        if op=='snapshot':return self.snapshot(activity)
        if op=='editing':
            if actor=='agent':raise ValueError('An agent cannot acquire a human input lease')
            token=req.get('client_id');active=req.get('active')
            if not isinstance(token,str) or not 1<=len(token)<=64 or type(active) is not bool:raise ValueError('Invalid input lease')
            self.leases={key:expiry for key,expiry in self.leases.items() if expiry>time.monotonic()}
            key=(activity,uid,token)
            if active:self.leases[key]=time.monotonic()+3
            else:self.leases.pop(key,None)
            return {'input_busy':self.busy(activity)}
        if op=='events':
            after=req.get('after_revision',-1)
            if type(after) is not int or after< -1:raise ValueError('Invalid event cursor')
            rows=self.db.execute('SELECT revision,at,actor,uid,action FROM events WHERE activity=? AND revision>? ORDER BY revision LIMIT 100',(activity,after))
            return [{'revision':r[0],'at':r[1],'actor':r[2],'uid':r[3],'action':json.loads(r[4])} for r in rows]
        if op!='apply':raise ValueError('Unknown layout operation')
        old=self.snapshot(activity)
        if type(req.get('expected_revision')) is not int or req['expected_revision']!=old['revision']:
            raise ValueError('Layout changed. Refresh layout_snapshot and use the new revision; this action was not applied.')
        if actor=='agent' and self.busy(activity):raise ValueError('The user is typing. No layout change was applied; leave the arrangement alone for now.')
        action=req.get('action')
        if not isinstance(action,dict):raise ValueError('Expected an action object')
        history=json.loads(self.db.execute('SELECT undo FROM layouts WHERE activity=?',(activity,)).fetchone()[0])
        before=canonical(old)
        if action=={'operation':'undo'}:
            if not history:raise ValueError('There is no layout change to undo')
            new=history.pop()
        else:
            new=apply(before,action)
            # Selection and binding updates must not bury structural layout undo.
            if action['operation'] in ('split','close','resize','swap','zoom','restore','view'):
                history=(history+[before])[-20:]
        revision=old['revision']+1
        with self.db:
            self.db.execute('UPDATE layouts SET revision=?,body=?,undo=? WHERE activity=?',
                            (revision,json.dumps(new),json.dumps(history),activity))
            self.db.execute('INSERT INTO events(activity,revision,at,actor,uid,action) VALUES(?,?,?,?,?,?)',
                            (activity,revision,time.time(),actor,uid,json.dumps(action)))
        return self.snapshot(activity)


def main():
    store=LayoutStore(DATABASE);agent_uid=pwd.getpwnam('agentos-ai').pw_uid
    server=listen(SOCKET)
    while True:
        conn,_=server.accept()
        with conn:
            conn.settimeout(2)
            try:
                uid=struct.unpack('3i',conn.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))[1]
                with conn.makefile('rb') as f:req=read_line(f)
                result=store.handle(req,uid,'agent' if uid==agent_uid else 'user')
                send(conn,{'ok':True,'result':result})
            except (ValueError,KeyError,TypeError,OSError,sqlite3.Error) as exc:
                try:send(conn,{'ok':False,'error':str(exc) if isinstance(exc,ValueError) else 'Layout service could not complete the request'})
                except OSError:pass

if __name__=='__main__':main()
