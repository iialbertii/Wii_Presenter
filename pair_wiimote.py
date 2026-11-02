"""Pair a Wii Remote / Wii Remote Plus with Windows without typing a PIN.

Windows asks for a PIN you cannot type: the Wii Remote's PIN is a Bluetooth
address written as raw bytes. This script sends that PIN itself through the
Windows Bluetooth API (the same trick Dolphin uses), then switches on the
remote's HID service so presenter_mvp.py can find it.

Run:   py pair_wiimote.py           then press the red Sync button (permanent pairing)
       py pair_wiimote.py --guest   then hold 1+2 instead (temporary pairing)
Needs: Windows 8 or newer, nothing to pip install.
"""
import argparse
import ctypes
import sys
import time
from ctypes import wintypes as wt

if sys.platform != "win32":
    sys.exit("This script is for Windows. On Linux the remote pairs without a PIN.")

bt = ctypes.WinDLL("bthprops.cpl")
kernel32 = ctypes.WinDLL("kernel32")


# ---- Windows Bluetooth structures (bluetoothapis.h) -------------------------
class BLUETOOTH_ADDRESS(ctypes.Union):
    _fields_ = [("ullLong", ctypes.c_ulonglong), ("rgBytes", ctypes.c_ubyte * 6)]


class SYSTEMTIME(ctypes.Structure):
    _fields_ = [(n, wt.WORD) for n in ("wYear", "wMonth", "wDayOfWeek", "wDay",
                                       "wHour", "wMinute", "wSecond", "wMilliseconds")]


class BLUETOOTH_DEVICE_INFO(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("Address", BLUETOOTH_ADDRESS),
                ("ulClassofDevice", wt.ULONG), ("fConnected", wt.BOOL),
                ("fRemembered", wt.BOOL), ("fAuthenticated", wt.BOOL),
                ("stLastSeen", SYSTEMTIME), ("stLastUsed", SYSTEMTIME),
                ("szName", wt.WCHAR * 248)]


class BLUETOOTH_DEVICE_SEARCH_PARAMS(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("fReturnAuthenticated", wt.BOOL),
                ("fReturnRemembered", wt.BOOL), ("fReturnUnknown", wt.BOOL),
                ("fReturnConnected", wt.BOOL), ("fIssueInquiry", wt.BOOL),
                ("cTimeoutMultiplier", ctypes.c_ubyte), ("hRadio", wt.HANDLE)]


class BLUETOOTH_FIND_RADIO_PARAMS(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD)]


class BLUETOOTH_RADIO_INFO(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("address", BLUETOOTH_ADDRESS),
                ("szName", wt.WCHAR * 248), ("ulClassofDevice", wt.ULONG),
                ("lmpSubversion", wt.USHORT), ("manufacturer", wt.USHORT)]


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wt.DWORD), ("Data2", wt.WORD), ("Data3", wt.WORD),
                ("Data4", ctypes.c_ubyte * 8)]


# {00001124-0000-1000-8000-00805F9B34FB} = Bluetooth HID service
HID_SERVICE = GUID(0x00001124, 0x0000, 0x1000,
                   (ctypes.c_ubyte * 8)(0x80, 0x00, 0x00, 0x80, 0x5F, 0x9B, 0x34, 0xFB))
BLUETOOTH_SERVICE_ENABLE = 0x01
ERROR_NO_MORE_ITEMS = 259            # AuthenticateDevice: "already authenticated"

P = ctypes.POINTER
bt.BluetoothFindFirstRadio.argtypes = [P(BLUETOOTH_FIND_RADIO_PARAMS), P(wt.HANDLE)]
bt.BluetoothFindFirstRadio.restype = wt.HANDLE
bt.BluetoothFindRadioClose.argtypes = [wt.HANDLE]
bt.BluetoothGetRadioInfo.argtypes = [wt.HANDLE, P(BLUETOOTH_RADIO_INFO)]
bt.BluetoothGetRadioInfo.restype = wt.DWORD
bt.BluetoothFindFirstDevice.argtypes = [P(BLUETOOTH_DEVICE_SEARCH_PARAMS), P(BLUETOOTH_DEVICE_INFO)]
bt.BluetoothFindFirstDevice.restype = wt.HANDLE
bt.BluetoothFindNextDevice.argtypes = [wt.HANDLE, P(BLUETOOTH_DEVICE_INFO)]
bt.BluetoothFindNextDevice.restype = wt.BOOL
bt.BluetoothFindDeviceClose.argtypes = [wt.HANDLE]
bt.BluetoothRemoveDevice.argtypes = [P(BLUETOOTH_ADDRESS)]
bt.BluetoothRemoveDevice.restype = wt.DWORD
bt.BluetoothAuthenticateDevice.argtypes = [wt.HWND, wt.HANDLE, P(BLUETOOTH_DEVICE_INFO),
                                           P(wt.WCHAR), wt.ULONG]
bt.BluetoothAuthenticateDevice.restype = wt.DWORD
bt.BluetoothSetServiceState.argtypes = [wt.HANDLE, P(BLUETOOTH_DEVICE_INFO), P(GUID), wt.DWORD]
bt.BluetoothSetServiceState.restype = wt.DWORD
kernel32.CloseHandle.argtypes = [wt.HANDLE]

HINTS = {
    5: "access denied - open the Command Prompt with 'Run as administrator' and retry",
    121: "timed out - the remote stopped being discoverable",
    258: "timed out - the remote stopped being discoverable",
    1167: "the remote is not connected",
    1223: "cancelled",
    1460: "timed out - the remote stopped being discoverable",
}


# ---- helpers -----------------------------------------------------------------
def fmt(addr):
    """Address bytes are stored backwards; print them the usual way."""
    return ":".join(f"{b:02X}" for b in reversed(bytes(addr.rgBytes)))


def describe(err):
    return HINTS.get(err) or ctypes.FormatError(err).strip()


def open_radio():
    params = BLUETOOTH_FIND_RADIO_PARAMS(ctypes.sizeof(BLUETOOTH_FIND_RADIO_PARAMS))
    radio = wt.HANDLE()
    find = bt.BluetoothFindFirstRadio(ctypes.byref(params), ctypes.byref(radio))
    if not find:
        sys.exit("No Bluetooth adapter found. Is Bluetooth switched on?")
    bt.BluetoothFindRadioClose(find)
    info = BLUETOOTH_RADIO_INFO()
    info.dwSize = ctypes.sizeof(info)
    err = bt.BluetoothGetRadioInfo(radio, ctypes.byref(info))
    if err:
        sys.exit(f"Could not read the Bluetooth adapter: {describe(err)}")
    return radio, info


def find_devices(radio, inquiry, remembered):
    """List nearby/known devices. inquiry=True scans the air for ~2.5 s."""
    params = BLUETOOTH_DEVICE_SEARCH_PARAMS(
        dwSize=ctypes.sizeof(BLUETOOTH_DEVICE_SEARCH_PARAMS),
        fReturnAuthenticated=remembered, fReturnRemembered=remembered,
        fReturnUnknown=True, fReturnConnected=True,
        fIssueInquiry=inquiry, cTimeoutMultiplier=2 if inquiry else 0,
        hRadio=radio.value)
    found = []
    info = BLUETOOTH_DEVICE_INFO()
    info.dwSize = ctypes.sizeof(info)
    find = bt.BluetoothFindFirstDevice(ctypes.byref(params), ctypes.byref(info))
    if not find:
        return found
    try:
        while True:
            found.append(BLUETOOTH_DEVICE_INFO.from_buffer_copy(info))
            info = BLUETOOTH_DEVICE_INFO()
            info.dwSize = ctypes.sizeof(info)
            if not bt.BluetoothFindNextDevice(find, ctypes.byref(info)):
                break
    finally:
        bt.BluetoothFindDeviceClose(find)
    return found


def is_wiimote(dev):
    if dev.szName:
        return dev.szName.startswith("Nintendo RVL-CNT-01")
    return dev.ulClassofDevice in (0x002504, 0x000508)   # name not read yet


def enable_hid(radio, dev):
    err = bt.BluetoothSetServiceState(radio, ctypes.byref(dev), ctypes.byref(HID_SERVICE),
                                      BLUETOOTH_SERVICE_ENABLE)
    if err:
        print(f"  Note: enabling the HID service returned: {describe(err)}")
    return err == 0


def wait_for_hid(seconds=15):
    """If hidapi is installed, confirm the remote shows up as a HID device."""
    try:
        import hid
    except ImportError:
        return None
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if any(d["product_id"] in (0x0306, 0x0330) for d in hid.enumerate(0x057E, 0)):
            return True
        time.sleep(1)
    return False


# ---- main --------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--guest", action="store_true",
                    help="pair after holding 1+2 (temporary pairing)")
    ap.add_argument("--seconds", type=int, default=60, help="how long to keep searching")
    args = ap.parse_args()

    radio, radio_info = open_radio()
    try:
        print(f"Bluetooth adapter: {radio_info.szName or 'unnamed'} ({fmt(radio_info.address)})")

        # 1. Clear old, half-finished pairings - they make Windows ask for a PIN again.
        for dev in find_devices(radio, inquiry=False, remembered=True):
            if not is_wiimote(dev):
                continue
            if dev.fConnected:
                print(f"{dev.szName} ({fmt(dev.Address)}) is already connected.")
                enable_hid(radio, dev)
                print("Nothing else to do - run: py presenter_mvp.py")
                return 0
            bt.BluetoothRemoveDevice(ctypes.byref(dev.Address))
            print(f"Removed an old pairing for {fmt(dev.Address)}.")

        # 2. Search and pair.
        button = "HOLD 1 and 2 together" if args.guest else "PRESS the red Sync button under the battery cover"
        print(f"\nNow {button}.")
        print("The blue LEDs blink while it is searchable; if they stop, press again.\n")

        # Sync pairing uses the PC's address as PIN, 1+2 uses the remote's own.
        # If the first guess is rejected, the other one is tried next time.
        use_pc_address = not args.guest
        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline:
            print("  searching...")
            for dev in find_devices(radio, inquiry=True, remembered=False):
                if not is_wiimote(dev):
                    continue
                name = dev.szName or "Wii Remote"
                if dev.fConnected:
                    print(f"Found {name}, already connected.")
                    enable_hid(radio, dev)
                    return finish(args.guest)

                source = radio_info.address if use_pc_address else dev.Address
                pin = (wt.WCHAR * 6)(*[chr(b) for b in source.rgBytes])
                print(f"Found {name} ({fmt(dev.Address)}), pairing...")
                err = bt.BluetoothAuthenticateDevice(None, radio, ctypes.byref(dev), pin, 6)
                if err in (0, ERROR_NO_MORE_ITEMS):
                    enable_hid(radio, dev)
                    return finish(args.guest)

                print(f"  Pairing failed: {describe(err)}")
                bt.BluetoothRemoveDevice(ctypes.byref(dev.Address))   # clean up, retry
                use_pc_address = not use_pc_address
                print("  Trying again with the other PIN - press the button again.\n")
                break
        print("\nNo Wii Remote paired. Make sure the LEDs are blinking while it searches,")
        print("or try:  py pair_wiimote.py --guest   (and hold 1+2)")
        return 1
    finally:
        kernel32.CloseHandle(radio)


def finish(guest):
    print("\nPaired! The LEDs keep blinking until a program takes control - that's normal.")
    found = wait_for_hid()
    if found is False:
        print("Windows hasn't shown the remote as an input device yet; give it a few")
        print("seconds, or switch Bluetooth off and on.")
    if guest:
        print("1+2 pairing is temporary: run this again after the remote switches off.")
    else:
        print("Sync pairing should be permanent: after the presenter has connected once,")
        print("pressing any button should reconnect the remote.")
    print("Next: py presenter_mvp.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
