import unittest
import sqlite3
from unittest.mock import patch
import xml.etree.ElementTree as ET
from controller import Controller,reading,station_rows,center,PRIMARY_LOCATION,SECONDARY_LOCATION

def tree(items):
    root=ET.Element('hierarchy')
    for text,desc in items:ET.SubElement(root,'node',{'text':text,'content-desc':desc})
    return root
class Tests(unittest.TestCase):
    def test_scrolls_to_site_header_and_next_scan_goes_down(self):
        c=Controller.__new__(Controller);c.scan_directions={PRIMARY_LOCATION:'up'}
        top=tree([(PRIMARY_LOCATION,'locationName')]);top[0].set('bounds','[23,175][563,205]')
        with patch.object(c,'screen',return_value=top),patch.object(c,'adb') as adb:
            self.assertIs(c.scroll_to_top(PRIMARY_LOCATION,tree([('BAE607195','')])),top)
            adb.assert_called_once_with('shell','input','swipe','380','620','380','1300','200')
            self.assertEqual(c.scan_directions[PRIMARY_LOCATION],'down')
            c.scroll_to_top(PRIMARY_LOCATION,top)
            self.assertEqual(adb.call_count,1)
    def test_four_primary_scans_then_one_secondary(self):
        c=Controller.__new__(Controller);state={}
        c.get=lambda key:state.get(key)
        c.save=lambda key,value:state.update({key:value})
        with patch.object(c,'scan') as scan:
            sites=[c.scheduled_scan() for _ in range(10)]
        self.assertEqual(sites,([PRIMARY_LOCATION]*4+[SECONDARY_LOCATION])*2)
        self.assertEqual(scan.call_count,10)
        self.assertEqual(state['primary_scans_since_secondary'],0)
    def test_failed_scan_does_not_advance_rotation(self):
        c=Controller.__new__(Controller);c.get=lambda key:4
        with patch.object(c,'scan',side_effect=RuntimeError('UI unavailable')),patch.object(c,'save') as save:
            with self.assertRaises(RuntimeError):c.scheduled_scan()
            save.assert_not_called()
    def test_secondary_scan_has_no_polling_delay(self):
        c=Controller.__new__(Controller);state={'primary_scans_since_secondary':4}
        c.get=lambda key:state.get(key)
        c.save=lambda key,value:state.update({key:value})
        with patch.object(c,'scan'),patch('controller.stamp',return_value=1000):
            self.assertEqual(c.scheduled_scan(),SECONDARY_LOCATION)
            self.assertEqual(c.next_scan,1000)
            self.assertEqual(c.scheduled_scan(),PRIMARY_LOCATION)
            self.assertEqual(c.next_scan,1005)
    def test_active_charge_keeps_time_between_station_scans(self):
        c=Controller.__new__(Controller);c.active=True;c.get=lambda key:0;c.save=lambda *args:None
        with patch.object(c,'scan'),patch('controller.stamp',return_value=1000):
            c.scheduled_scan();self.assertEqual(c.next_scan,1030)
    def test_reuses_open_site_without_navigation(self):
        c=Controller.__new__(Controller)
        root=tree([(PRIMARY_LOCATION,'locationName')])
        with patch.object(c,'screen',return_value=root),patch.object(c,'tab') as tab:
            self.assertIs(c.location(),root);tab.assert_not_called()
    def test_reuses_scrolled_site_only_with_matching_station_mapping(self):
        c=Controller.__new__(Controller);c.visible_location=PRIMARY_LOCATION
        c.db=sqlite3.connect(':memory:');self.addCleanup(c.db.close)
        c.db.execute('CREATE TABLE station_locations(id TEXT PRIMARY KEY,location TEXT)')
        c.db.execute('INSERT INTO station_locations VALUES(?,?)',('BAE607154',PRIMARY_LOCATION))
        root=ET.Element('hierarchy');ET.SubElement(root,'node').append(tree([('BAE607154',''),('Available','')]))
        with patch.object(c,'screen',return_value=root),patch.object(c,'tab') as tab:
            self.assertIs(c.location(),root);tab.assert_not_called()
        c.db.execute('UPDATE station_locations SET location=?',(SECONDARY_LOCATION,))
        with patch.object(c,'screen',return_value=root),patch.object(c,'tab',side_effect=RuntimeError('must navigate')):
            with self.assertRaisesRegex(RuntimeError,'must navigate'):c.location()
    def test_secondary_scan_keeps_location_and_does_not_trigger_gateway_alert(self):
        c=Controller.__new__(Controller);c.db=sqlite3.connect(':memory:')
        self.addCleanup(c.db.close)
        c.db.executescript('CREATE TABLE stations(id TEXT PRIMARY KEY,status TEXT,checked INTEGER); CREATE TABLE station_locations(id TEXT PRIMARY KEY,location TEXT);')
        c.session=None;c.candidate='BAE607191';c.error=None
        c.event=lambda *a:None;c.adb=lambda *a:None
        root=ET.Element('hierarchy');ET.SubElement(root,'node').append(tree([('BAE600275',''),('Available','')]))
        with patch.object(c,'location',return_value=root) as location,patch.object(c,'screen',return_value=root),patch.object(c,'availability_alert') as alert:
            self.assertEqual(c.scan(location=SECONDARY_LOCATION),{'BAE600275':'Available'})
            location.assert_called_once_with(SECONDARY_LOCATION);alert.assert_not_called()
        self.assertEqual(c.db.execute('SELECT location FROM station_locations').fetchone()[0],SECONDARY_LOCATION)
        self.assertEqual(c.candidate,'BAE607191')
        with patch.object(c,'location',return_value=root) as location:
            c.scan('BAE600275');location.assert_called_once_with(SECONDARY_LOCATION)
    def test_location_verifies_selected_site(self):
        c=Controller.__new__(Controller)
        with patch.object(c,'tab',return_value=tree([('Favorite','')])),patch.object(c,'choose'),patch.object(c,'screen',return_value=tree([(PRIMARY_LOCATION,'')])):
            with self.assertRaisesRegex(RuntimeError,'Selected location'):
                c.location(SECONDARY_LOCATION)
    def test_backfill_keeps_grouped_sessions_separate(self):
        from history_backfill import records
        root=ET.Element('hierarchy')
        for station,start,energy in [('BAE607191','11:33 AM','4.99 kWh'),('BAE607172','10:39 AM','0.10 kWh')]:
            card=ET.SubElement(root,'node')
            card.append(tree([(v,'') for v in ['Date','September 16, 2026','Charging Time','2 min 13 seconds','Energy',energy,'Start Time',start,'End Time','1:33 PM','Serial Number',station]]))
        entries=list(records(root).values())
        self.assertEqual(len(entries),2)
        self.assertEqual({e['station']:e['kwh'] for e in entries},{'BAE607191':4.99,'BAE607172':0.1})
    def test_backfill_rejects_incomplete_detail(self):
        from history_backfill import records
        self.assertEqual(records(tree([(v,'') for v in ['Date','September 16, 2026','Serial Number','BAE607172']])),{})
    def test_completed_beats_stale_power(self):
        r=reading(tree([('Completed',''),('Please unplug the connector',''),('2.96 kW','currentSpeedValue'),('0.59 kWh','energyDeliveredVal')]))
        self.assertEqual(r['state'],'stopped')
    def test_zero_is_not_stop(self):
        self.assertEqual(reading(tree([('0.00 kW','currentSpeedValue')]))['state'],'waiting for data')
    def test_ended_popup(self):
        self.assertEqual(reading(tree([('Start Charge',''),('You are all charged up!','')]))['state'],'ended')
    def test_row_identity(self):
        root=ET.Element('hierarchy')
        for ident,status in [('BAE607172','Connected'),('BAE607191','In Use')]:
            row=ET.SubElement(root,'node')
            row.append(tree([(ident,''),('PORT-1','')]))
            ET.SubElement(row,'node',{'text':status})
        rows=station_rows(root)
        self.assertEqual(rows['BAE607172'][0],'Connected')
        self.assertEqual(rows['BAE607191'][0],'In Use')
    def test_no_guess_when_clipped(self):
        self.assertEqual(station_rows(tree([('BAE607172','')])),{})
    def test_hidden_target(self):
        with self.assertRaises(ValueError):center(ET.Element('node',bounds='[0,0][0,0]'))
    def test_availability_only(self):
        c=Controller.__new__(Controller);calls=[];saved=[]
        c.get=lambda key:{'armed':True}
        c.run=lambda *args,**kw:calls.append(args)
        c.save=lambda *args:saved.append(args)
        c.event=lambda *args:None
        c.availability_alert({'BAE607191':'Connected','BAE607172':'In Use'})
        self.assertFalse(calls)
        c.availability_alert({'BAE607172':'Available'})
        self.assertEqual(calls[0][:3],('termux-tts-speak','-s','ALARM'))
        self.assertFalse(saved[0][1]['armed'])
    def test_completion_speech_and_repeat(self):
        c=Controller.__new__(Controller);calls=[]
        c.session={'state':'stopped'};c.alarm=0
        c.run=lambda *a,**k:calls.append(a)
        with patch('controller.Path.exists',return_value=False),patch('controller.notify') as notice:
            with patch('controller.stamp',return_value=1000):
                c.completion_alert();c.completion_alert()
            self.assertEqual(len(calls),1)
            self.assertEqual(calls[0][:3],('termux-tts-speak','-s','ALARM'))
            with patch('controller.stamp',return_value=1300):c.completion_alert()
            self.assertEqual(len(calls),2)
            self.assertEqual(notice.call_count,2)
    def test_completion_suppressed_unless_confirmed_and_unacknowledged(self):
        c=Controller.__new__(Controller);c.alarm=0
        with patch.object(c,'run') as speak,patch('controller.notify'),patch('controller.stamp',return_value=1000):
            with patch('controller.Path.exists',return_value=False):
                for state in ('charging','waiting for data','ended'):
                    c.session={'state':state};c.completion_alert()
            c.session={'state':'stopped'}
            with patch('controller.Path.exists',return_value=True):c.completion_alert()
            speak.assert_not_called()
    def test_completion_failure_does_not_spam_or_skip_notification(self):
        c=Controller.__new__(Controller);c.alarm=0;c.session={'state':'stopped'}
        with patch.object(c,'run',side_effect=RuntimeError('tts failed')) as speak,patch('controller.notify') as notice,patch('controller.Path.exists',return_value=False),patch('controller.stamp',return_value=1000):
            c.completion_alert();c.completion_alert()
            self.assertEqual(speak.call_count,1);notice.assert_called_once()
    def test_recovery_escalates_without_charge_actions(self):
        c=Controller.__new__(Controller);calls=[]
        c.ui_failures=0;c.recovery_level=0;c.last_recovery=0;c.device='127.0.0.1:33703'
        c.session={'state':'stopped'};c.run=lambda *a,**k:None
        c.adb=lambda *a:(calls.append(a) or ('device' if a==('get-state',) else ''))
        c.event=lambda *a:None
        with patch('controller.time.sleep'),patch('controller.stamp',return_value=1000):
            c.recover_ui('missing');c.recover_ui('missing');self.assertFalse(calls)
            c.recover_ui('missing');self.assertNotIn(('shell','am','force-stop','com.blinknetwork.mobile2'),calls)
            before=len(calls);c.recover_ui('missing');self.assertEqual(len(calls),before)
        with patch('controller.time.sleep'),patch('controller.stamp',return_value=1061):c.recover_ui('missing')
        self.assertIn(('shell','am','force-stop','com.blinknetwork.mobile2'),calls)
        self.assertEqual(c.session,{'state':'stopped'})
        self.assertFalse(any('tap' in a for a in calls))
    def test_recovery_does_not_restart_app_without_adb(self):
        c=Controller.__new__(Controller);calls=[]
        c.ui_failures=2;c.recovery_level=1;c.last_recovery=0;c.device='offline'
        c.run=lambda *a:None;c.adb=lambda *a:(calls.append(a) or 'offline')
        with self.assertRaises(RuntimeError):c.recover_ui('offline')
        self.assertEqual(calls,[('get-state',)])
if __name__=='__main__':unittest.main()
