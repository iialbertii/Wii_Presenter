"""Phase 3: Wii Remote Plus as a slide clicker (A = next, B = back, D-pad = arrows).

Setup:  pip install hidapi pynput   (pair the remote in Windows first)
Run:    python presenter_mvp.py     (Ctrl+C to quit)
"""
import hid
from pynput.keyboard import Controller, Key

NINTENDO_VID = 0x057E
WIIMOTE_PIDS = {0x0306, 0x0330}          # 0x0330 = Wii Remote Plus (RVL-CNT-01-TR)

# Bit masks for the two "core buttons" bytes (WiiBrew); first byte = low 8 bits
BUTTONS = {
    "LEFT": 0x0001, "RIGHT": 0x0002, "DOWN": 0x0004, "UP": 0x0008,
    "PLUS": 0x0010, "TWO": 0x0100, "ONE": 0x0200, "B": 0x0400,
    "A": 0x0800, "MINUS": 0x1000, "HOME": 0x8000,
}
BUTTON_BITS = 0x9F1F                     # ignore the accelerometer bits mixed in
REPORTS_WITH_BUTTONS = {0x20, 0x21, 0x22, *range(0x30, 0x38), 0x3E, 0x3F}

keyboard = Controller()
TAP = {"A": Key.right, "B": Key.left}               # one keystroke per press
HOLD = {"UP": Key.up, "DOWN": Key.down,             # held for as long as the button is
        "LEFT": Key.left, "RIGHT": Key.right}


def on_button(name, pressed):
    if name in TAP and pressed:
        keyboard.tap(TAP[name])
    elif name in HOLD:
        if pressed:
            keyboard.press(HOLD[name])
        else:
            keyboard.release(HOLD[name])


def find_wiimote():
    for info in hid.enumerate(NINTENDO_VID, 0):
        if info["product_id"] in WIIMOTE_PIDS:
            return info["path"]
    raise SystemExit("No Wii Remote found - pair it in Bluetooth settings first.")


def main():
    dev = hid.device()
    dev.open_path(find_wiimote())
    dev.write([0x11, 0x10])              # player LED 1 on (stops the blinking)
    dev.write([0x12, 0x00, 0x30])        # report buttons only, and only on change

    held = 0
    while True:
        report = dev.read(32, 500)       # wait up to 500 ms; [] if nothing arrived
        if not report:
            continue
        if report[0] == 0x20:            # status report: re-arm reporting (WiiBrew rule)
            dev.write([0x12, 0x00, 0x30])
        if report[0] not in REPORTS_WITH_BUTTONS:
            continue
        state = (report[1] | (report[2] << 8)) & BUTTON_BITS
        for name, mask in BUTTONS.items():
            if (state ^ held) & mask:
                on_button(name, bool(state & mask))
        held = state


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:            # Ctrl+C: quit quietly
        pass
    finally:
        for key in HOLD.values():        # never leave an arrow key stuck down
            keyboard.release(key)
