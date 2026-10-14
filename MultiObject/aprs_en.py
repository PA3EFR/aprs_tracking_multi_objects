#!/usr/bin/env python3
"""APRS Tracker - CORRECT NOTATION (multi-object, simultaneous)"""

import aprslib
import time
import random
import math
import re
import os
import threading
import datetime


SPEED_RANGES = {
    'car': (50, 120),
    'bike': (10, 25),
    'walk': (1, 5)
}

WAYPOINTS_FILE_TEMPLATE = "Waypoints_{call}.txt"
APRS_CODES_FILE = "APRS_Codes.txt"


# Matches lines such as:
# 49.98172°N 6.08968°E
# Also matches lines with an explicit minus sign before the number,
# e.g.: 50.39012°N -0.02114°E
COORD_RE = re.compile(
    r'(-?[\d.]+)\s*°?\s*([NS])\s+(-?[\d.]+)\s*°?\s*([EW])'
)


# Lock so the console output of multiple objects does not get interleaved
PRINT_LOCK = threading.Lock()


def safe_print(*args, **kwargs):
    with PRINT_LOCK:
        print(*args, **kwargs)


def read_aprs_codes(path=APRS_CODES_FILE):
    """
    Reads APRS passcodes from APRS_Codes.txt.

    Expects lines such as:
        pa3efr 22196
        pd1eho 23212

    Callsigns are processed case-insensitively.
    Any SSID is ignored.

    Empty lines and lines starting with '#' are ignored.
    """
    codes = {}

    if not os.path.isfile(path):
        return codes

    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()

            if not line or line.startswith("#"):
                continue

            parts = line.split()

            if len(parts) < 2:
                continue

            callsign = parts[0].upper().split("-")[0]
            code = parts[1].strip()

            codes[callsign] = code

    return codes


def get_aprs_passcode(call):
    """
    Determine the APRS passcode for a callsign.

    First, APRS_Codes.txt is searched using the callsign
    without SSID.

    For example:
        PA3EFR
        PA3EFR-1
        PA3EFR-9

    all look up:
        PA3EFR

    Only when the callsign is not present in APRS_Codes.txt
    is the user asked to enter a passcode.
    """
    base_call = call.split("-")[0].upper()

    codes = read_aprs_codes()

    if base_call in codes:
        print(
            f"Passcode for {call} found in "
            f"{APRS_CODES_FILE}: {codes[base_call]}.\n"
        )
        return codes[base_call]

    print(
        f"Callsign {base_call} is not in "
        f"{APRS_CODES_FILE}."
    )

    return input(
        f"Go to https://www.iz3mez.it/aprs-passcode/ for the passcode. "
        f"Passcode for {call}: "
    ).strip()


def read_waypoints(path):
    """
    Reads waypoints from a file with blocks of
    (at least) 3 lines per point:

      1: *NN-X "name" hinzugefügt
      2: UTM line (ignored)
      3: GPS position, e.g.: 49.98172°N 6.08968°E

    The file may contain any number of waypoints.
    Every line that matches the coordinate pattern is taken
    as a waypoint, in the order in which they appear in the
    file.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"Waypoints file not found: {path}"
        )

    wp = []

    with open(path, encoding="utf-8") as f:
        for line in f:
            m = COORD_RE.search(line)

            if not m:
                continue

            # If the number already has an explicit minus sign,
            # that takes precedence.
            lat = float(m.group(1))

            if lat >= 0 and m.group(2) == "S":
                lat = -lat

            lon = float(m.group(3))

            if lon >= 0 and m.group(4) == "W":
                lon = -lon

            wp.append((lat, lon))

    if len(wp) < 2:
        raise ValueError(
            f"Too few waypoints found in {path} "
            f"({len(wp)})"
        )

    # In the file the last waypoint is at the top,
    # so reverse the order.
    wp.reverse()

    return wp


def get_object_input(index, total):
    print("\n" + "=" * 60)
    print(f"Object {index}/{total}")
    print("=" * 60)

    call = input("Callsign: ").strip().upper()

    # First look up the passcode automatically in APRS_Codes.txt.
    # Only for an unknown callsign is the user asked to enter
    # the passcode.
    code = get_aprs_passcode(call)

    print("1=Car 2=Bike 3=Walk")

    t = {
        '1': 'car',
        '2': 'bike',
        '3': 'walk'
    }[input("Choice: ").strip()]

    iv = int(input("Interval (s): "))

    first_upload = input(
        "At what time should the first waypoint be uploaded to aprs.fi "
        "(format hh:mm)?   "
        "[now]: "
    ).strip()

    # "now" or empty input means: no delay.
    # With a time (HH:MM), the script waits until that local time.
    if (
        not first_upload
        or first_upload.lower() in ("now", "direct")
    ):
        first_upload = None
    else:
        try:
            datetime.datetime.strptime(first_upload, "%H:%M")
        except ValueError:
            raise ValueError(
                "Invalid time. Use HH:MM, for example 21:30, "
                "or leave empty for immediate start."
            )

    comment = input("Comment: ").strip()

    # The waypoints file is derived from the callsign
    # without SSID.
    #
    # For example:
    #   PD1EHO-1
    #   PD1EHO-8
    #
    # becomes:
    #   Waypoints_pd1eho.txt
    base_call = call.split("-")[0]

    path = WAYPOINTS_FILE_TEMPLATE.format(
        call=base_call.lower()
    )

    wp = read_waypoints(path)

    print(f"\n{len(wp)} waypoints loaded from {path}:")

    for i, (la, lo) in enumerate(wp, 1):
        print(f"  {i}: {la:.6f},{lo:.6f}")

    return {
        "call": call,
        "code": code,
        "comment": comment,
        "type": t,
        "interval": iv,
        "first_upload": first_upload,
        "waypoints": wp,
    }


def get_input():
    print(
        "=" * 60 +
        "\nAPRS Tracker (multi-object)\n" +
        "=" * 60
    )

    n = int(input("How many objects do you want to track? "))

    if n < 1:
        raise ValueError(
            "There must be at least 1 object"
        )

    objects = [
        get_object_input(i, n)
        for i in range(1, n + 1)
    ]

    return objects


def dist(a, b):
    R = 6371

    dlat = math.radians(b[0] - a[0])
    dlon = math.radians(b[1] - a[1])

    x = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(a[0]))
        * math.cos(math.radians(b[0]))
        * math.sin(dlon / 2) ** 2
    )

    return R * 2 * math.atan2(
        math.sqrt(x),
        math.sqrt(1 - x)
    )


def lerp(a, b, n, variation=0.25):
    """
    Interpolates n+1 points between a and b
    (including start and end point).

    Instead of always using exactly equal step sizes,
    each intermediate step gets a random weight
    of (1-variation) to (1+variation) times the
    average step size.

    After normalization the start and end point
    still fall exactly on a and b.
    """
    if n <= 0:
        return [a, b]

    weights = [
        random.uniform(1 - variation, 1 + variation)
        for _ in range(n)
    ]

    total = sum(weights)

    fracs = [0.0]
    acc = 0.0

    for w in weights:
        acc += w
        fracs.append(acc / total)

    return [
        (
            a[0] + (b[0] - a[0]) * f,
            a[1] + (b[1] - a[1]) * f
        )
        for f in fracs
    ]


def estimate_object_duration(obj):
    """
    Estimates the total travel time (in seconds) of one object,
    based on the average speed of the chosen transport type.
    This is only an estimate: during the actual trip the speed
    per segment is chosen randomly within SPEED_RANGES, so the
    real duration may differ.
    """
    wp = obj["waypoints"]
    t = obj["type"]

    avg_speed = sum(SPEED_RANGES[t]) / 2

    total_seconds = 0.0

    for i in range(len(wp) - 1):
        d = dist(wp[i], wp[i + 1])
        total_seconds += d / avg_speed * 3600

    return total_seconds


def format_duration(seconds):
    """Formats a number of seconds as H:MM:SS."""
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


def print_eta(objects):
    """
    Just before the first upload starts, prints an estimate
    of the total duration of the route and the (local) clock
    time at which the last upload will roughly take place.
    Because all objects are tracked simultaneously (in
    parallel threads), the total duration equals the longest
    individual trip.
    """
    print("\n" + "=" * 60)
    print("Time estimate (based on average speed)")
    print("=" * 60)

    max_duration = 0.0

    for obj in objects:
        duration = estimate_object_duration(obj)
        max_duration = max(max_duration, duration)

        eta = datetime.datetime.now() + datetime.timedelta(
            seconds=duration
        )

        print(
            f"  [{obj['call']}] estimated duration: "
            f"{format_duration(duration)} | "
            f"done around: {eta.strftime('%H:%M:%S')}"
        )

    overall_eta = datetime.datetime.now() + datetime.timedelta(
        seconds=max_duration
    )

    print("-" * 60)
    print(
        f"Total estimated duration of the route: "
        f"{format_duration(max_duration)}"
    )
    print(
        f"Expected last upload around: "
        f"{overall_eta.strftime('%H:%M:%S')} "
        f"(local PC time)"
    )
    print("=" * 60)


def aprs_pos(call, lat, lon, sym, comment):
    """
    APRS uncompressed position without timestamp.

    Format:
        !DDMM.mmN/DDDMM.mmE>comment
    """

    if not (-90.0 <= lat <= 90.0):
        raise ValueError(
            f"Invalid latitude: {lat}"
        )

    if not (-180.0 <= lon <= 180.0):
        raise ValueError(
            f"Invalid longitude: {lon}"
        )

    # Latitude: DDMM.mmN/S
    lat_abs = abs(lat)
    lat_deg = int(lat_abs)
    lat_min = (lat_abs - lat_deg) * 60.0
    lat_dir = "N" if lat >= 0 else "S"

    # Longitude: DDDMM.mmE/W
    lon_abs = abs(lon)
    lon_deg = int(lon_abs)
    lon_min = (lon_abs - lon_deg) * 60.0
    lon_dir = "E" if lon >= 0 else "W"

    lat_text = f"{lat_deg:02d}{lat_min:05.2f}{lat_dir}"
    lon_text = f"{lon_deg:03d}{lon_min:05.2f}{lon_dir}"

    # '/' = primary symbol table
    info = f"!{lat_text}/{lon_text}{sym}{comment}"

    packet = f"{call}>APRS,TCPIP*:{info}"

    return packet, info


def upload(call, code, pkt, log_prefix):
    ais = None

    try:
        ais = aprslib.IS(
            call,
            passwd=code,
            port=14580
        )

        ais.connect()
        ais.sendall(pkt)

        safe_print(f"{log_prefix}  ✓ OK")

        return True

    except Exception as e:
        safe_print(f"{log_prefix}  ✗ {e}")
        return False

    finally:
        try:
            if ais is not None:
                ais.close()
        except Exception:
            pass


def track_object(obj, results):
    """
    Walks through all segments of one object and sends
    the positions. Runs in its own thread.
    """
    call = obj["call"]
    code = obj["code"]
    comment = obj["comment"]
    t = obj["type"]
    iv = obj["interval"]
    first_upload = obj["first_upload"]
    wp = obj["waypoints"]

    # APRS symbol codes from the PRIMARY table ('/'):
    #
    #   '>' = Car
    #   'b' = Bike
    #   '[' = Jogger (walking figure)
    sym = {
        'car': '>',
        'bike': 'b',
        'walk': '['
    }[t]

    log_prefix = f"[{call}]"

    est_duration = estimate_object_duration(obj)
    est_eta = datetime.datetime.now() + datetime.timedelta(
        seconds=est_duration
    )

    safe_print(
        f"{log_prefix} start | "
        f"{comment} | {t} | {iv}s | "
        f"estimated duration: {format_duration(est_duration)} | "
        f"expected done: {est_eta.strftime('%H:%M:%S')}"
    )

    ok, tot = 0, 0
    first_upload_done = False

    for i in range(len(wp) - 1):
        a, b = wp[i], wp[i + 1]

        d = dist(a, b)

        s = random.uniform(
            *SPEED_RANGES[t]
        )

        dur = d / s * 3600

        n = max(
            1,
            int(dur / iv)
        )

        safe_print(
            f"{log_prefix} Seg {i + 1}: "
            f"{d:.2f}km @ {s:.1f}km/h = "
            f"{dur:.0f}s ({n} pts)"
        )

        for j, (la, lo) in enumerate(
            lerp(a, b, n)
        ):
            pkt, info = aprs_pos(
                call,
                la,
                lo,
                sym,
                comment
            )

            safe_print(
                f"{log_prefix}  Input: "
                f"{la:.6f}, {lo:.6f}"
            )

            safe_print(
                f"{log_prefix}  APRS: {info}"
            )

            # Only wait before the first waypoint. The remaining
            # waypoints then follow the normal interval.
            if not first_upload_done and first_upload:
                now = datetime.datetime.now()
                target = datetime.datetime.combine(
                    now.date(),
                    datetime.datetime.strptime(
                        first_upload, "%H:%M"
                    ).time()
                )

                # A time that has already passed today means tomorrow.
                if target <= now:
                    target += datetime.timedelta(days=1)

                wait_seconds = (target - now).total_seconds()
                safe_print(
                    f"{log_prefix}  First upload scheduled for "
                    f"{target.strftime('%Y-%m-%d %H:%M:%S')} "
                    f"(waiting {format_duration(wait_seconds)})"
                )
                time.sleep(wait_seconds)

            if upload(
                call,
                code,
                pkt,
                log_prefix
            ):
                ok += 1

            tot += 1
            first_upload_done = True

            if j < n:
                time.sleep(
                    iv * random.uniform(
                        0.8,
                        1.2
                    )
                )

    results[call] = (ok, tot)

    safe_print(
        f"{log_prefix} finished: "
        f"{ok}/{tot} OK | "
        f"aprs.fi/?call={call}"
    )


def main():
    objects = get_input()

    print(
        f"\n{len(objects)} object(s) will be tracked "
        f"simultaneously\n" +
        "=" * 60
    )

    print_eta(objects)

    results = {}
    threads = []

    for obj in objects:
        th = threading.Thread(
            target=track_object,
            args=(obj, results),
            daemon=True
        )

        threads.append(th)

    # Start all threads (almost) at the same time so the
    # objects can be followed simultaneously on aprs.fi,
    # regardless of their individual interval.
    for th in threads:
        th.start()

    for th in threads:
        th.join()

    print("\n" + "=" * 60)
    print("Summary:")

    for obj in objects:
        call = obj["call"]

        ok, tot = results.get(
            call,
            (0, 0)
        )

        print(
            f"  {call}: "
            f"{ok}/{tot} OK | "
            f"aprs.fi/?call={call}"
        )
    end_time = datetime.datetime.now()

    print("=" * 60)
    print(
        f"Finished at: {end_time.strftime('%Y-%m-%d %H:%M:%S')}"
    )
    print("=" * 60)


if __name__ == "__main__":
    main()