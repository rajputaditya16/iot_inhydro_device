import os, sys, glob, time, threading, fcntl
for path in glob.glob('/usr/lib/python3*/dist-packages'):
    if path not in sys.path: sys.path.append(path)

import dbus, dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

print("==========================================")
print("  BLUETOOTH LIVE DEBUGGER (BLOCKING FIX)  ")
print("==========================================")

DBusGMainLoop(set_as_default=True)
bus = dbus.SystemBus()

# 1. Configure Adapter
try:
    adapter_obj = bus.get_object('org.bluez', '/org/bluez/hci0')
    adapter_props = dbus.Interface(adapter_obj, 'org.freedesktop.DBus.Properties')
    adapter_props.Set('org.bluez.Adapter1', 'Powered', dbus.Boolean(True))
    adapter_props.Set('org.bluez.Adapter1', 'Discoverable', dbus.Boolean(True))
    adapter_props.Set('org.bluez.Adapter1', 'Pairable', dbus.Boolean(True))
    adapter_props.Set('org.bluez.Adapter1', 'DiscoverableTimeout', dbus.UInt32(0))
    print("✅ Adapter configured: Powered=True, Discoverable=True, Pairable=True")
except Exception as e:
    print(f"❌ Adapter config error: {e}")

# 2. Auto-Accept Agent
class BluetoothAgent(dbus.service.Object):
    @dbus.service.method('org.bluez.Agent1', in_signature='', out_signature='')
    def Release(self): pass

    @dbus.service.method('org.bluez.Agent1', in_signature='os', out_signature='')
    def AuthorizeService(self, device, uuid): return

    @dbus.service.method('org.bluez.Agent1', in_signature='o', out_signature='s')
    def RequestPinCode(self, device): return '0000'

    @dbus.service.method('org.bluez.Agent1', in_signature='o', out_signature='u')
    def RequestPasskey(self, device): return dbus.UInt32(0)

    @dbus.service.method('org.bluez.Agent1', in_signature='ouq', out_signature='')
    def DisplayPasskey(self, device, passkey, entered): pass

    @dbus.service.method('org.bluez.Agent1', in_signature='os', out_signature='')
    def DisplayPinCode(self, device, pincode): pass

    @dbus.service.method('org.bluez.Agent1', in_signature='ou', out_signature='')
    def RequestConfirmation(self, device, passkey): return

    @dbus.service.method('org.bluez.Agent1', in_signature='o', out_signature='')
    def RequestAuthorization(self, device): return

    @dbus.service.method('org.bluez.Agent1', in_signature='', out_signature='')
    def Cancel(self): pass

try:
    agent_path = '/inhydro/test_agent'
    agent = BluetoothAgent(bus, agent_path)
    manager_a = dbus.Interface(bus.get_object('org.bluez', '/org/bluez'), 'org.bluez.AgentManager1')
    try: manager_a.UnregisterAgent(agent_path)
    except: pass
    manager_a.RegisterAgent(agent_path, 'NoInputNoOutput')
    manager_a.RequestDefaultAgent(agent_path)
    print("✅ Auto-Pairing Agent Active (NoInputNoOutput)")
except Exception as e:
    print(f"Notice Agent: {e}")

# 3. Profile Implementation with Blocking FD Fix
class BluezProfile(dbus.service.Object):
    @dbus.service.method('org.bluez.Profile1', in_signature='oha{sv}', out_signature='')
    def NewConnection(self, path, fd, properties):
        fd_int = fd.take()
        # Set FD to blocking mode to avoid [Errno 11] Resource temporarily unavailable (EAGAIN)
        flags = fcntl.fcntl(fd_int, fcntl.F_GETFL)
        fcntl.fcntl(fd_int, fcntl.F_SETFL, flags & ~os.O_NONBLOCK)
        
        print(f"\n🎉 NEW CONNECTION ACCEPTED! (FD: {fd_int})")
        print(f"   Device Path: {path}")
        threading.Thread(target=self.handle_client, args=(fd_int,), daemon=True).start()

    @dbus.service.method('org.bluez.Profile1', in_signature='o', out_signature='')
    def RequestDisconnection(self, path):
        print(f"⚠️ Disconnect Requested: {path}")

    def handle_client(self, fd_int):
        try:
            welcome = (
                "\r\n=================================\r\n"
                "--- INHYDRO CONTROLLER TEST ---\r\n"
                "COMMANDS: PING | SCAN | STATUS\r\n"
                "=================================\r\n\r\n"
            )
            os.write(fd_int, welcome.encode('utf-8'))
            print("📤 Sent Welcome Banner!")

            buf = ""
            while True:
                raw = os.read(fd_int, 1024)
                if not raw:
                    print("📱 Phone disconnected cleanly.")
                    break
                print(f"📥 RAW BYTES RECEIVED: {raw}")
                buf += raw.decode('utf-8', errors='ignore')
                
                lines = []
                while "\n" in buf or "\r" in buf:
                    if "\r\n" in buf: line, buf = buf.split("\r\n", 1)
                    elif "\n" in buf: line, buf = buf.split("\n", 1)
                    else: line, buf = buf.split("\r", 1)
                    lines.append(line)

                if not lines and buf.strip():
                    lines.append(buf)
                    buf = ""

                for line in lines:
                    cmd = line.strip()
                    if not cmd: continue
                    print(f"🎯 EXECUTING COMMAND: '{cmd}'")
                    
                    if cmd.upper() in ["PING", "1"]:
                        resp = "\r\n[PONG] SYSTEM ALIVE & READY!\r\n\r\n"
                        os.write(fd_int, resp.encode('utf-8'))
                        print("📤 Sent PONG response!")
                    else:
                        resp = f"\r\n[ACK] Received: '{cmd}'\r\n\r\n"
                        os.write(fd_int, resp.encode('utf-8'))
                        print(f"📤 Sent ACK response for: {cmd}")
        except Exception as e:
            print(f"❌ Handle Client Error: {e}")
        finally:
            try: os.close(fd_int)
            except: pass

profile_path = '/test/spp_profile_blocking'
try:
    profile = BluezProfile(bus, profile_path)
    manager_p = dbus.Interface(bus.get_object('org.bluez', '/org/bluez'), 'org.bluez.ProfileManager1')
    try: manager_p.UnregisterProfile(profile_path)
    except: pass
    opts = {
        'AutoConnect': dbus.Boolean(True),
        'Role': 'server',
        'Name': 'Serial Port',
        'Service': '00001101-0000-1000-8000-00805F9B34FB',
        'Channel': dbus.UInt16(1),
        'RequireAuthentication': dbus.Boolean(False),
        'RequireAuthorization': dbus.Boolean(False)
    }
    manager_p.RegisterProfile(profile_path, '00001101-0000-1000-8000-00805F9B34FB', opts)
    print("✅ Registered SPP Profile with Blocking FD Fix!")
except Exception as e:
    print(f"❌ Profile registration error: {e}")

print("📡 Waiting for phone connection in Serial Bluetooth Terminal...")
mainloop = GLib.MainLoop()
mainloop.run()
