# AbletonMCP/init.py
from __future__ import absolute_import, print_function, unicode_literals
from _Framework.ControlSurface import ControlSurface
import socket, json, threading, time, traceback, os, subprocess

try: import Queue as queue
except ImportError: import queue

DEFAULT_PORT = 9877
HOST = "localhost"

def create_instance(c_instance): return AbletonMCP(c_instance)

class AbletonMCP(ControlSurface):
    def __init__(self, c_instance):
        ControlSurface.__init__(self, c_instance)
        self.log_message("AbletonMCP Initializing...")
        self.server = None
        self.client_threads = []
        self.server_thread = None
        self.running = False
        self._song = self.song()
        self.start_server()
        self.show_message("AbletonMCP: Listening on " + str(DEFAULT_PORT))

    def disconnect(self):
        self.running = False
        if self.server:
            try: self.server.close()
            except: pass
        ControlSurface.disconnect(self)

    def start_server(self):
        try:
            self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server.bind((HOST, DEFAULT_PORT))
            self.server.listen(5)
            self.running = True
            self.server_thread = threading.Thread(target=self._server_thread)
            self.server_thread.daemon = True
            self.server_thread.start()
        except Exception as e: self.log_message("Server error: " + str(e))

    def _server_thread(self):
        self.server.settimeout(1.0)
        while self.running:
            try:
                client, addr = self.server.accept()
                t = threading.Thread(target=self._handle_client, args=(client,))
                t.daemon = True
                t.start()
                self.client_threads.append(t)
            except socket.timeout: continue
            except: break

    def _handle_client(self, client):
        client.settimeout(None)
        buffer = ''
        try:
            while self.running:
                data = client.recv(8192)
                if not data: break
                try: buffer += data.decode('utf-8')
                except AttributeError: buffer += data
                try:
                    command = json.loads(buffer)
                    buffer = ''
                    resp = self._process_command(command)
                    try: client.sendall(json.dumps(resp).encode('utf-8'))
                    except AttributeError: client.sendall(json.dumps(resp))
                except ValueError: continue
        finally: client.close()

    def _get_track_by_index(self, idx):
        all_tracks = list(self._song.tracks) + list(self._song.return_tracks) + [self._song.master_track]
        return all_tracks[idx]

    def _process_command(self, cmd):
        c_type = cmd.get("type", "")
        params = cmd.get("params", {})
        res = {"status": "success", "result": {}}
        try:
            if c_type == "get_database_status": res["result"] = self._get_database_status()
            elif c_type == "search_samples": res["result"] = self._search_samples(params.get("search_term", ""), params.get("max_results", 200))
            elif c_type in ["get_session_info", "get_track_info", "create_midi_track", "create_audio_track", "create_clip", "delete_clip", "add_notes_to_clip", "fire_clip", "load_sample_by_name", "delete_track", "duplicate_track", "create_return_track", "create_scene", "delete_scene", "duplicate_scene", "capture_and_insert_scene", "set_track_name", "stop_all_clips", "trigger_session_record", "set_track_monitoring", "tap_tempo", "jump_by", "scrub_by", "duplicate_clip_to_arrangement", "set_track_frozen", "create_take_lane"]:
                q = queue.Queue()
                def task():
                    try:
                        r = None
                        if c_type == "get_session_info": r = {"tempo": self._song.tempo, "track_count": len(self._song.tracks)}
                        elif c_type == "get_track_info":
                            t = self._get_track_by_index(params.get("track_index", 0))
                            r = {"name": t.name, "clip_slots": [{"has_clip": s.has_clip} for s in t.clip_slots] if hasattr(t, "clip_slots") else []}
                        elif c_type == "create_midi_track": self._song.create_midi_track(params.get("index", -1)); r = {"done": True}
                        elif c_type == "create_audio_track": self._song.create_audio_track(params.get("index", -1)); r = {"done": True}
                        elif c_type == "delete_track": self._song.delete_track(params.get("track_index", 0)); r = {"done": True}
                        elif c_type == "duplicate_track": self._song.duplicate_track(params.get("track_index", 0)); r = {"done": True}
                        elif c_type == "create_return_track": self._song.create_return_track(); r = {"done": True}
                        elif c_type == "create_scene": self._song.create_scene(params.get("index", -1)); r = {"done": True}
                        elif c_type == "delete_scene": self._song.delete_scene(params.get("scene_index", 0)); r = {"done": True}
                        elif c_type == "duplicate_scene": self._song.duplicate_scene(params.get("scene_index", 0)); r = {"done": True}
                        elif c_type == "capture_and_insert_scene": self._song.capture_and_insert_scene(); r = {"done": True}
                        elif c_type == "stop_all_clips": self._song.stop_all_clips(); r = {"done": True}
                        elif c_type == "trigger_session_record": self._song.trigger_session_record(); r = {"done": True}
                        elif c_type == "tap_tempo": self._song.tap_tempo(); r = {"done": True}
                        elif c_type == "jump_by": self._song.jump_by(params.get("beats", 1.0)); r = {"done": True}
                        elif c_type == "scrub_by": self._song.scrub_by(params.get("beats", 1.0)); r = {"done": True}
                        elif c_type == "duplicate_clip_to_arrangement":
                            t = self._get_track_by_index(params.get("track_index", 0))
                            slot = t.clip_slots[params.get("clip_index", 0)]
                            t.duplicate_clip_to_arrangement(slot, params.get("target_time", 0.0))
                            r = {"done": True}
                        elif c_type == "set_track_frozen":
                            t = self._get_track_by_index(params.get("track_index", 0))
                            if hasattr(t, "is_frozen"):
                                t.is_frozen = params.get("frozen", True)
                                r = {"frozen": t.is_frozen}
                            else: r = {"error": "Track does not support freezing"}
                        elif c_type == "create_take_lane":
                            t = self._get_track_by_index(params.get("track_index", 0))
                            if hasattr(t, "create_take_lane"):
                                t.create_take_lane()
                                r = {"done": True}
                            else: r = {"error": "Track does not support take lanes"}
                        elif c_type == "set_track_monitoring":
                            t = self._get_track_by_index(params.get("track_index", 0))
                            if hasattr(t, "current_monitoring_state"):
                                t.current_monitoring_state = params.get("state", 1) # 0: In, 1: Auto, 2: Off
                                r = {"state": t.current_monitoring_state}
                            else: r = {"error": "Track does not support monitoring"}
                        elif c_type == "set_track_name": 
                            t = self._get_track_by_index(params.get("track_index", 0))
                            t.name = params.get("name", t.name)
                            r = {"name": t.name}
                        elif c_type == "delete_clip":
                            t = self._get_track_by_index(params.get("track_index", 0))
                            slot = t.clip_slots[params.get("clip_index", 0)]
                            if slot.has_clip: slot.delete_clip(); r = {"deleted": True}
                            else: r = {"deleted": False}
                        elif c_type == "create_clip":
                            t = self._get_track_by_index(params.get("track_index", 0))
                            t.clip_slots[params.get("clip_index", 0)].create_clip(params.get("length", 4.0))
                            r = {"done": True}
                        elif c_type == "add_notes_to_clip":
                            t = self._get_track_by_index(params.get("track_index", 0))
                            clip = t.clip_slots[params.get("clip_index", 0)].clip
                            notes = []
                            for n in params.get("notes", []):
                                notes.append((n.get("pitch", 60), n.get("start_time", 0.0), n.get("duration", 0.25), n.get("velocity", 100), False))
                            clip.set_notes(tuple(notes))
                            r = {"done": True}
                        elif c_type == "fire_clip":
                            t = self._get_track_by_index(params.get("track_index", 0))
                            t.clip_slots[params.get("clip_index", 0)].fire()
                            r = {"done": True}
                        elif c_type == "load_sample_by_name":
                            t = self._get_track_by_index(params.get("track_index", 0))
                            found = self._search_browser(params.get("sample_name", ""))
                            if found:
                                self._song.view.selected_track = t
                                self.application().browser.load_item(found)
                                r = {"loaded": True}
                            else: r = {"error": "not found"}
                        q.put({"s": "success", "r": r})
                    except Exception as e: q.put({"s": "error", "m": str(e)})
                self.schedule_message(0, task)
                tr = q.get(timeout=10.0)
                if tr["s"] == "error": res = {"status": "error", "message": tr["m"]}
                else: res["result"] = tr["r"]
        except Exception as e: res = {"status": "error", "message": str(e)}
        return res

    def _search_browser(self, name):
        app = self.application()
        for cat in [app.browser.samples, app.browser.user_folders]:
            res = self._recursive_search(cat, name)
            if res: return res
        return None

    def _recursive_search(self, obj, name, depth=0):
        if depth > 10: return None
        if hasattr(obj, "name") and obj.name == name: return obj
        if hasattr(obj, "children"):
            for c in obj.children:
                r = self._recursive_search(c, name, depth + 1)
                if r: return r
        return None

    def _get_database_status(self):
        db = os.path.expanduser("~/Library/Application Support/Ableton/Live Database/Live-files-12201.db")
        count = subprocess.check_output(['sqlite3', db, "SELECT COUNT(*) FROM files WHERE file_type = 2002875949;"], text=True).strip()
        return {"samples": int(count)}

    def _search_samples(self, term, limit=200):
        db = os.path.expanduser("~/Library/Application Support/Ableton/Live Database/Live-files-12201.db")
        likes = " AND ".join(["name LIKE '%{0}%'".format(w.replace("'", "''")) for w in term.split()])
        out = subprocess.check_output(['sqlite3', db, "SELECT name FROM files WHERE {0} AND file_type = 2002875949 LIMIT {1};".format(likes, limit)], text=True).strip()
        return {"samples": [{"name": l} for l in out.split('\n')] if out else []}